"""Team backup round trips use only local temporary data and the real backup script."""

import asyncio
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import zipfile
from contextlib import closing
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from textwrap import dedent
from typing import TypedDict
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import paramiko
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from backend import branding, defaults, engine, main, store, teams, text_tools, tools

ROOT = Path(__file__).resolve().parents[1]
TABLES = ("users", "entities", "platform_settings", "team_spaces", "team_members", "team_files", "audit")
PERSONAL = "个人原始附件。\n".encode()
SHARED = (b"active team payload\x00\xff\n", "归档团队原始附件。\n".encode())
SECRET = "temporary-backup-provider-secret"


class Actor(TypedDict):
    id: str
    email: str
    name: str
    role: str
    disabled: bool
    must_change_password: bool
    space_modules: list[str]
    team_invites_blocked: bool


@pytest.fixture
def backup_data(tmp_path, monkeypatch):
    data = tmp_path / "source"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    for name in tuple(os.environ):
        if name.startswith("EARTHAI_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("EARTHAI_DATA_DIR", str(data))
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", "DELETE")
    for name, value in (("DATA_ROOT", data), ("DATA", data), ("UPLOADS", uploads), ("DB_PATH", data / "earthai.db")):
        monkeypatch.setattr(store, name, value)
    monkeypatch.setattr(store, "_CONNECTIONS", {})
    monkeypatch.setattr(store, "_CONNECTION_LOCK", threading.Lock())
    monkeypatch.setattr(store, "_CONNECTION_LOCAL", threading.local())
    monkeypatch.setattr(store, "_cipher", lru_cache(maxsize=4)(store._cipher.__wrapped__))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})
    (data / "master.key").write_bytes(Fernet.generate_key())
    (data / "master.key").chmod(0o600)
    guards = [
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected paid model request"))),
        (text_tools, "complete", AsyncMock(side_effect=AssertionError("unexpected fallback model request"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure execution"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected infrastructure connection"))),
        (engine, "scheduler_loop", AsyncMock(side_effect=AssertionError("unexpected scheduler"))),
        (httpx.Client, "send", Mock(side_effect=AssertionError("unexpected external HTTP"))),
        (httpx.AsyncClient, "send", AsyncMock(side_effect=AssertionError("unexpected external HTTP"))),
        (paramiko.SSHClient, "connect", Mock(side_effect=AssertionError("unexpected SSH connection"))),
        (socket.socket, "connect", Mock(side_effect=AssertionError("unexpected network connection"))),
        (socket, "create_connection", Mock(side_effect=AssertionError("unexpected network connection"))),
    ]
    for target, name, guard in guards:
        monkeypatch.setattr(target, name, guard)
    try:
        yield data
    finally:
        store.close_connections()
        store._cipher.cache_clear()
        for _, name, guard in guards:
            assert guard.call_count == 0, name
        assert engine.TASKS == {} and engine.CANCEL_TOKENS == {}


def _actor(label) -> Actor:
    actor: Actor = {
        "id": store.uid(), "email": f"backup-{label}@example.test", "name": label, "role": "user",
        "disabled": False, "must_change_password": False, "space_modules": ["personal", "team"],
        "team_invites_blocked": False,
    }
    with store.connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (
            actor["id"], actor["email"], "unused-local-password-hash",
            store.dumps({key: value for key, value in actor.items() if key not in {"id", "email"}}), store.now(),
        ))
    return actor


def _seed():
    store.init_db()
    defaults.init_tables()
    with store.connect() as db:
        assert set(TABLES) <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if store.journal_mode() == "WAL":
            db.execute("PRAGMA wal_autocheckpoint=0")
            assert db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    actors = {role: _actor(role) for role in ("owner", "manager", "editor", "viewer", "outsider")}
    owner = actors["owner"]
    spaces, files = [], []
    for index, content in enumerate(SHARED):
        space = teams.create_space(owner, {"name": f"Backup team {index}", "description": "原始团队元数据"})
        for role in ("manager", "editor", "viewer"):
            teams.add_member(owner, space["id"], {"email": actors[role]["email"], "role": role})
        files.append(teams.upload_file(actors["editor"], space["id"], content, "shared.bin", "application/octet-stream"))
        spaces.append(space)
    teams.archive_space(owner, spaces[1]["id"])
    with BytesIO(PERSONAL) as stream:
        personal = asyncio.run(main.upload_file(UploadFile(file=stream, filename="personal.txt"), user=owner))
    provider = store.save_entity(owner["id"], "providers", {
        "name": "Offline backup provider", "base_url": "https://backup.example.invalid/v1", "api_key": store.seal(SECRET),
    })
    logo = branding.save_asset(b"\x89PNG\r\n\x1a\nlocal-backup-branding")
    branding.save({"name": "备份品牌", "icon_url": logo["url"]})
    assert store.unseal(provider["api_key"]) == SECRET
    return {"actors": actors, "spaces": spaces, "files": files, "personal": personal, "provider": provider}


def _rows():
    with store.connect() as db:
        return {table: sorted((list(row) for row in db.execute(f'SELECT * FROM "{table}"')), key=repr) for table in TABLES}


def _source_bytes():
    # WAL checkpoints may move committed pages into earthai.db without changing logical rows.
    database_files = {"earthai.db-wal", "earthai.db-shm"}
    if store.journal_mode() == "WAL":
        database_files.add("earthai.db")
    return {
        str(path.relative_to(store.DATA)): path.read_bytes()
        for path in store.DATA.rglob("*") if path.is_file() and path.name not in database_files
    }


def _child_env(data, backups=None):
    env = {name: value for name, value in os.environ.items() if not name.startswith("EARTHAI_")}
    env.update({
        "EARTHAI_DATA_DIR": str(data), "EARTHAI_SQLITE_JOURNAL_MODE": "DELETE",
        "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
    })
    if backups is not None:
        env["EARTHAI_BACKUP_DIR"] = str(backups)
    return env


def _backup(data, tmp_path):
    before_rows, before_bytes = _rows(), _source_bytes()
    backups = tmp_path / "private-backups"
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts" / "backup.py")], cwd=tmp_path,
        env=_child_env(data, backups), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "备份完成" in result.stdout
    archives = list(backups.glob("*.zip"))
    assert len(archives) == 1 and set(backups.iterdir()) == set(archives)
    assert backups.stat().st_mode & 0o777 == 0o700
    assert archives[0].stat().st_mode & 0o777 == 0o600
    with zipfile.ZipFile(archives[0]) as archive:
        manifest = {"data/" + name: content for name, content in before_bytes.items() if name != "earthai.db" and not name.endswith("-wal")}
        assert set(archive.namelist()) == {"data/earthai.db", *manifest}
        assert len(archive.namelist()) == len(set(archive.namelist()))
        assert archive.testzip() is None
        for name, content in manifest.items():
            assert archive.read(name) == content
        archive.extractall(tmp_path / "restored")
    restored = tmp_path / "restored" / "data"
    with closing(sqlite3.connect(restored / "earthai.db")) as db:
        assert db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {table: sorted((list(row) for row in db.execute(f'SELECT * FROM "{table}"')), key=repr) for table in TABLES} == before_rows
    assert _rows() == before_rows and _source_bytes() == before_bytes
    return restored


RESTORE_CHECK = """
    import hashlib
    import json
    import socket
    import sys
    from pathlib import Path

    def no_network(*args, **kwargs):
        raise AssertionError("unexpected network during offline restore")

    socket.socket.connect = no_network
    socket.create_connection = no_network
    from fastapi import HTTPException
    from backend import branding, store, teams

    expected = json.loads(Path(sys.argv[1]).read_text())
    def rows():
        with store.connect() as db:
            return {table: sorted((list(row) for row in db.execute(f'SELECT * FROM "{table}"')), key=repr)
                    for table in expected["rows"]}

    assert rows() == expected["rows"]
    store.init_db()
    teams.initialize()
    store.init_db()
    assert rows() == expected["rows"]
    with store.connect() as db:
        assert [row[0] for row in db.execute("PRAGMA quick_check")] == ["ok"]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        actors = {row["id"]: {**store.loads(row["data"]), "id": row["id"], "email": row["email"]}
                  for row in db.execute("SELECT id,email,data FROM users")}
    assert hashlib.sha256((store.DATA / "master.key").read_bytes()).hexdigest() == expected["key_sha256"]
    owner = actors[expected["actors"]["owner"]]
    provider = store.get_entity(owner["id"], "providers", expected["provider"])
    assert store.unseal(provider["api_key"]) == expected["secret"]
    assert branding.get()["name"] == "备份品牌"
    personal = store.get_entity(owner["id"], "files", expected["personal"])
    assert hashlib.sha256((store.UPLOADS / personal["storage_name"]).read_bytes()).hexdigest() == expected["personal_sha256"]
    active, archived = expected["spaces"]
    for role in ("owner", "viewer"):
        actor = actors[expected["actors"][role]]
        assert teams.get_space(actor, active)["role"] == role
        metadata, path = teams.download_file(actor, active, expected["files"][0]["id"])
        assert metadata["space_id"] == active
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["files"][0]["sha256"]
    outsider = actors[expected["actors"]["outsider"]]
    try:
        teams.download_file(outsider, active, expected["files"][0]["id"])
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("restored membership must still protect team files")
    assert teams.get_space(owner, archived)["archived"] is True
    assert teams.restore_space(owner, archived)["archived"] is False
    _, path = teams.download_file(actors[expected["actors"]["viewer"]], archived, expected["files"][1]["id"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["files"][1]["sha256"]
    assert hashlib.sha256((store.DATA / "master.key").read_bytes()).hexdigest() == expected["key_sha256"]
    store.close_connections()
    print("offline restore verified")
"""


@pytest.mark.parametrize("mode", ["WAL", "DELETE"])
def test_team_backup_script_round_trip_preserves_rows_bytes_key_and_restored_access(backup_data, tmp_path, monkeypatch, mode):
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", mode)
    sample = _seed()
    before_rows, before_bytes = _rows(), _source_bytes()
    for row in before_rows["team_files"]:
        name = row[5]
        assert Path(name).name == name and name.startswith("team-")
        UUID(name.removeprefix("team-"))
    if mode == "WAL":
        assert (backup_data / "earthai.db-wal").stat().st_size > 32
        with closing(sqlite3.connect(f"file:{store.DB_PATH}?immutable=1", uri=True)) as db:
            assert db.execute("SELECT count(*) FROM team_files").fetchone()[0] == 0
    restored = _backup(backup_data, tmp_path)
    expected = {
        "rows": before_rows, "actors": {role: actor["id"] for role, actor in sample["actors"].items()},
        "spaces": [space["id"] for space in sample["spaces"]],
        "files": [{"id": file["id"], "sha256": hashlib.sha256(content).hexdigest()} for file, content in zip(sample["files"], SHARED)],
        "personal": sample["personal"]["id"], "personal_sha256": hashlib.sha256(PERSONAL).hexdigest(),
        "provider": sample["provider"]["id"], "secret": SECRET,
        "key_sha256": hashlib.sha256(before_bytes["master.key"]).hexdigest(),
    }
    expectations = tmp_path / "private-restore-expectations.json"
    expectations.write_text(json.dumps(expected), encoding="utf-8")
    expectations.chmod(0o600)
    result = subprocess.run(
        [sys.executable, "-B", "-c", dedent(RESTORE_CHECK), str(expectations)], cwd=tmp_path,
        env=_child_env(restored), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "offline restore verified"
    assert _rows() == before_rows and _source_bytes() == before_bytes


def test_backup_collects_personal_and_archived_team_files_with_owner_modules_closed(backup_data, tmp_path):
    sample = _seed()
    owner = sample["actors"]["owner"]
    with store.connect() as db:
        row = db.execute("SELECT data FROM users WHERE id=?", (owner["id"],)).fetchone()
        values = {**store.loads(row[0]), "space_modules": [], "team_invites_blocked": True}
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(values), owner["id"]))
    with pytest.raises(HTTPException) as denied:
        teams.list_spaces(owner)
    assert denied.value.status_code == 403
    restored = _backup(backup_data, tmp_path)
    with closing(sqlite3.connect(restored / "earthai.db")) as db:
        assert store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner["id"],)).fetchone()[0])["space_modules"] == []
        assert db.execute("SELECT count(*) FROM team_spaces WHERE deleted_at IS NOT NULL").fetchone()[0] == 1
        names = [row[0] for row in db.execute("SELECT storage_name FROM team_files ORDER BY id")]
    assert len(names) == 2
    assert sorted((restored / "uploads" / name).read_bytes() for name in names) == sorted(SHARED)
    personal = store.get_entity(owner["id"], "files", sample["personal"]["id"])
    assert personal is not None
    assert (restored / "uploads" / personal["storage_name"]).read_bytes() == PERSONAL


def test_store_and_team_schema_initialization_is_idempotent_for_existing_backup_data(backup_data):
    _seed()
    before_rows, before_bytes = _rows(), _source_bytes()
    store.init_db()
    teams.initialize()
    store.init_db()
    assert _rows() == before_rows and _source_bytes() == before_bytes
    assert len(before_rows["team_spaces"]) == 2
    assert len(before_rows["team_members"]) == 8
    assert len(before_rows["team_files"]) == 2
