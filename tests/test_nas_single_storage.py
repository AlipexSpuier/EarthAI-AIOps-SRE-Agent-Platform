"""Single-directory storage regressions on local temp files, not NAS power-loss tests."""

import asyncio
import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, Mock

import httpx
import paramiko
import pytest
import yaml
from fastapi.testclient import TestClient

import backend.storage_paths as storage_paths
from backend import engine, main, store, tools, usage

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Single-NAS-local-test-password!"


@pytest.fixture
def nas_store(monkeypatch, tmp_path):
    data = tmp_path / "mounted-nas"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    for name in (
        "EARTHAI_STATE_DIR", "EARTHAI_UPLOADS_DIR", "EARTHAI_MASTER_KEY",
        "EARTHAI_SQLITE_JOURNAL_MODE", "EARTHAI_BACKUP_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EARTHAI_DATA_DIR", str(data))
    monkeypatch.setenv("EARTHAI_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("EARTHAI_COOKIE_SECURE", "false")
    monkeypatch.setattr(store, "DATA_ROOT", data)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "earthai.db")
    monkeypatch.setattr(store, "_CONNECTIONS", {})
    monkeypatch.setattr(store, "_CONNECTION_LOCK", threading.Lock())
    monkeypatch.setattr(store, "_CONNECTION_LOCAL", threading.local())
    monkeypatch.setattr(store, "_cipher", lru_cache(maxsize=4)(store._cipher.__wrapped__))
    try:
        yield data
    finally:
        store.close_connections()
        store._cipher.cache_clear()


@pytest.fixture
def nas_app(nas_store, monkeypatch):
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", "DELETE")
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})

    async def idle_scheduler():
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "scheduler_loop", idle_scheduler)
    monkeypatch.setattr(engine, "provider_models", AsyncMock(return_value=["offline-model"]))
    guards = [
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected model request"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure execution"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected server connection"))),
        (httpx.AsyncClient, "send", AsyncMock(side_effect=AssertionError("unexpected external HTTP request"))),
        (paramiko.SSHClient, "connect", Mock(side_effect=AssertionError("unexpected SSH connection"))),
    ]
    for module, name, guard in guards:
        monkeypatch.setattr(module, name, guard)
    try:
        yield nas_store
    finally:
        for _, name, guard in guards:
            assert guard.call_count == 0, name


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def _python(data, source, *, mode="DELETE", args=()):
    env = {name: value for name, value in os.environ.items() if not name.startswith("EARTHAI_")}
    env.update({
        "EARTHAI_DATA_DIR": str(data), "EARTHAI_SQLITE_JOURNAL_MODE": mode,
        "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
    })
    result = subprocess.run(
        [sys.executable, "-B", "-c", dedent(source), *args], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    return result


def _resource_counts(owner):
    with store.connect() as db:
        return {row["kind"]: row["n"] for row in db.execute(
            "SELECT kind,count(*) n FROM entities WHERE owner=? GROUP BY kind", (owner,),
        )}


@pytest.mark.parametrize(("configured", "expected"), [(None, "WAL"), (" wal ", "WAL"), (" DeLeTe ", "DELETE")])
def test_default_and_normalized_journal_modes_preserve_single_data_layout(nas_store, monkeypatch, configured, expected):
    if configured is not None:
        monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", configured)
    assert storage_paths.paths() == (nas_store, nas_store, nas_store / "uploads")
    assert store.journal_mode() == expected
    store.init_db()
    with store.connect() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0].upper() == expected
        assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 0
    assert store.DB_PATH == nas_store / "earthai.db"
    assert store.DB_PATH.is_file()


@pytest.mark.parametrize("mode", ["WAL", "DELETE"])
@pytest.mark.parametrize("workers", [2, 3])
def test_every_new_concurrent_physical_connection_uses_full_sync(nas_store, monkeypatch, mode, workers):
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", mode)
    store.init_db()
    store.close_connections()
    assert not store._CONNECTIONS
    sqlite_connect = Mock(wraps=sqlite3.connect)
    monkeypatch.setattr(store.sqlite3, "connect", sqlite_connect)
    barrier = threading.Barrier(workers, timeout=10)

    def inspect_connection(_):
        with store.connect() as db:
            barrier.wait()
            assert store.current_connection() is db
            assert db.row_factory is sqlite3.Row
            assert db.execute("PRAGMA journal_mode").fetchone()[0].upper() == mode
            assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 20000
            identity = id(db)
            barrier.wait()
            return identity

    with ThreadPoolExecutor(max_workers=workers) as executor:
        identities = list(executor.map(inspect_connection, range(workers)))
    assert len(set(identities)) == workers
    assert sqlite_connect.call_count == workers
    assert list(store._CONNECTIONS) == [(os.getpid(), str(store.DB_PATH), mode)]
    assert next(iter(store._CONNECTIONS.values())).qsize() == workers
    assert store.current_connection() is None


@pytest.mark.parametrize("mode", ["", "OFF", "memory", "TRUNCATE", "PERSIST", "WAL; DROP TABLE users;--"])
def test_invalid_journal_mode_is_rejected_before_opening_database(nas_store, monkeypatch, mode):
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", mode)
    sqlite_connect = Mock(side_effect=AssertionError("invalid journal mode must not open a database"))
    monkeypatch.setattr(store.sqlite3, "connect", sqlite_connect)
    with pytest.raises(ValueError, match="只允许 WAL 或 DELETE"):
        store.init_db()
    with pytest.raises(ValueError, match="只允许 WAL 或 DELETE"):
        with store.connect():
            pytest.fail("invalid journal mode was accepted")
    sqlite_connect.assert_not_called()
    assert not store._CONNECTIONS
    assert list(nas_store.iterdir()) == [nas_store / "uploads"]


@pytest.mark.parametrize(("requested", "returned"), [("DELETE", "wal"), ("WAL", "delete")])
def test_init_refuses_mismatched_journal_mode_before_schema(nas_store, monkeypatch, requested, returned):
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", requested)
    db = Mock()
    db.execute.return_value.fetchone.return_value = (returned,)

    @contextmanager
    def mismatched_connection():
        yield db

    monkeypatch.setattr(store, "connect", mismatched_connection)
    with pytest.raises(RuntimeError, match=f"未能切换到 {requested}"):
        store.init_db()
    db.execute.assert_called_once_with(f"PRAGMA journal_mode={requested}")
    db.executescript.assert_not_called()
    assert not store.DB_PATH.exists()


def test_journal_mode_is_part_of_pool_identity(nas_store, monkeypatch):
    store.init_db()
    with store.connect() as wal_connection:
        assert wal_connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", "DELETE")
    with store.connect() as delete_connection:
        assert delete_connection is not wal_connection
    assert set(store._CONNECTIONS) == {
        (os.getpid(), str(store.DB_PATH), "WAL"), (os.getpid(), str(store.DB_PATH), "DELETE"),
    }
    monkeypatch.delenv("EARTHAI_SQLITE_JOURNAL_MODE")
    with store.connect() as reused:
        assert reused is wal_connection


def test_existing_uncheckpointed_wal_converts_to_delete_with_original_key(nas_store, monkeypatch):
    result = _python(nas_store, """
        import os
        import sqlite3
        from backend import store

        sealed = store.seal("legacy-provider-secret")
        db = sqlite3.connect(store.DB_PATH)
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.executescript('''
            CREATE TABLE users (
                id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
                data TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE entities (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE legacy_metadata (value TEXT NOT NULL);
        ''')
        stamp = store.now()
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (
            "legacy-owner", "legacy@example.test", store.password_hash("legacy-password"),
            store.dumps({"name": "Original user", "role": "user"}), stamp,
        ))
        db.execute("INSERT INTO entities VALUES (?,?,?,?,?,?)", (
            "legacy-provider", "legacy-owner", "providers",
            store.dumps({"name": "Original provider", "api_key": sealed}), stamp, stamp,
        ))
        db.execute("INSERT INTO legacy_metadata VALUES ('committed in WAL')")
        db.commit()
        print("committed legacy WAL", flush=True)
        os._exit(0)
    """, mode="WAL")
    assert "committed legacy WAL" in result.stdout
    wal = nas_store / "earthai.db-wal"
    assert wal.is_file() and wal.stat().st_size > 32
    original_key = (nas_store / "master.key").read_bytes()
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", "DELETE")
    manual_delete = Mock(side_effect=AssertionError("SQLite, not Python, must recover/remove WAL sidecars"))
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", manual_delete)
        patch.setattr(os, "unlink", manual_delete)
        patch.setattr(os, "remove", manual_delete)
        store.init_db()
        provider = store.get_entity("legacy-owner", "providers", "legacy-provider")
        assert provider is not None
        assert provider["name"] == "Original provider"
        assert store.unseal(provider["api_key"]) == "legacy-provider-secret"
        with store.connect() as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            user = db.execute("SELECT * FROM users").fetchone()
            assert user["id"] == "legacy-owner" and user["email"] == "legacy@example.test"
            assert store.password_matches("legacy-password", user["password"])
            assert db.execute("SELECT value FROM legacy_metadata").fetchall()[0][0] == "committed in WAL"
            assert db.execute("SELECT count(*) FROM entities").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    manual_delete.assert_not_called()
    assert (nas_store / "master.key").read_bytes() == original_key


def test_same_directory_preserves_auth_credentials_resources_usage_and_files_on_restart(nas_app):
    data = nas_app
    content = "Locally saved NAS attachment.\n单目录重启测试。\n".encode()
    with TestClient(main.app) as client:
        owner = _ok(client.post("/api/auth/register", json={
            "email": "single-nas@example.test", "password": PASSWORD, "name": "Single NAS user",
        }))["id"]
        token = client.cookies.get("earthai_session")
        provider = _ok(client.post("/api/providers", json={
            "name": "Offline provider", "base_url": "https://offline.example.invalid/v1",
            "api_key": "local-only-provider-secret", "models": ["offline-model"], "default_model": "offline-model",
        }))
        server = _ok(client.post("/api/servers", json={
            "name": "Offline server", "host": "192.0.2.20", "password": "local-only-server-secret",
        }))
        resources = []
        for kind in sorted(usage.KINDS):
            resource = next(item for item in _ok(client.get(f"/api/{kind}")) if item.get("default_template_id"))
            resources.append((kind, store.get_entity(owner, kind, resource["id"])))
        usage.record(owner, "offline-persistence-run", resources)
        file = _ok(client.post("/api/files", files={"file": ("attachment.txt", content, "text/plain")}))
        stored_file = store.get_entity(owner, "files", file["id"])
        stored_provider = store.get_entity(owner, "providers", provider["id"])
        stored_server = store.get_entity(owner, "servers", server["id"])
        assert stored_file is not None and stored_provider is not None and stored_server is not None
        encrypted_provider = stored_provider["api_key"]
        encrypted_password = stored_server["password"]
        assert encrypted_provider != "local-only-provider-secret"
        assert encrypted_password != "local-only-server-secret"
        assert store.unseal(encrypted_provider) == "local-only-provider-secret"
        assert store.unseal(encrypted_password) == "local-only-server-secret"
        assert (store.UPLOADS / stored_file["storage_name"]).read_bytes() == content
        original_key = (data / "master.key").read_bytes()
        counts = _resource_counts(owner)
        summary = usage.summary()
        assert summary["totals"] == dict.fromkeys(sorted(usage.KINDS), 1)
        with store.connect() as db:
            original_user = dict(db.execute("SELECT * FROM users WHERE id=?", (owner,)).fetchone())
            usage_rows = [dict(row) for row in db.execute("SELECT * FROM resource_usage ORDER BY kind")]
        expected = {
            "owner": owner, "token": token, "password": PASSWORD, "user": original_user,
            "provider_id": provider["id"], "provider_ciphertext": encrypted_provider,
            "server_id": server["id"], "server_ciphertext": encrypted_password,
            "counts": counts, "summary": summary, "usage_rows": usage_rows,
            "key_sha256": hashlib.sha256(original_key).hexdigest(),
            "storage_name": stored_file["storage_name"], "file_sha256": hashlib.sha256(content).hexdigest(),
        }
    assert not store._CONNECTIONS
    store._cipher.cache_clear()
    result = _python(data, """
        import hashlib
        import json
        import os
        import sys
        from backend import storage_paths, store, usage

        expected = json.loads(sys.argv[1])
        assert storage_paths.paths() == (store.DATA, store.DATA, store.DATA / "uploads")
        store.init_db()
        assert store.user_for_token(expected["token"])["id"] == expected["owner"]
        provider = store.get_entity(expected["owner"], "providers", expected["provider_id"])
        server = store.get_entity(expected["owner"], "servers", expected["server_id"])
        assert provider["api_key"] == expected["provider_ciphertext"]
        assert server["password"] == expected["server_ciphertext"]
        assert store.unseal(provider["api_key"]) == "local-only-provider-secret"
        assert store.unseal(server["password"]) == "local-only-server-secret"
        assert hashlib.sha256((store.DATA / "master.key").read_bytes()).hexdigest() == expected["key_sha256"]
        assert hashlib.sha256((store.UPLOADS / expected["storage_name"]).read_bytes()).hexdigest() == expected["file_sha256"]
        with store.connect() as db:
            user = dict(db.execute("SELECT * FROM users WHERE id=?", (expected["owner"],)).fetchone())
            assert user == expected["user"]
            assert store.password_matches(expected["password"], user["password"])
            counts = {row["kind"]: row["n"] for row in db.execute(
                "SELECT kind,count(*) n FROM entities WHERE owner=? GROUP BY kind", (expected["owner"],)
            )}
            assert counts == expected["counts"]
            assert [dict(row) for row in db.execute("SELECT * FROM resource_usage ORDER BY kind")] == expected["usage_rows"]
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
            assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert usage.summary() == expected["summary"]
        store.close_connections()
        print(json.dumps({"pid": os.getpid(), "data": str(store.DATA)}))
    """, args=(json.dumps(expected),))
    child = json.loads(result.stdout)
    assert child["pid"] != os.getpid()
    assert child["data"] == str(data)
    with TestClient(main.app) as restarted:
        restarted.cookies.set("earthai_session", token)
        assert _ok(restarted.get("/api/auth/me"))["id"] == owner
        assert restarted.post("/api/auth/login", json={
            "email": "single-nas@example.test", "password": "wrong-password",
        }).status_code == 401
        assert _ok(restarted.post("/api/auth/login", json={
            "email": "single-nas@example.test", "password": PASSWORD,
        }))["id"] == owner
        assert _resource_counts(owner) == counts
        assert usage.summary() == summary
        assert next(item for item in _ok(restarted.get("/api/providers")) if item["id"] == provider["id"]) == provider
        assert next(item for item in _ok(restarted.get("/api/servers")) if item["id"] == server["id"]) == server
        assert next(item for item in _ok(restarted.get("/api/files")) if item["id"] == file["id"]) == file
        download = restarted.get(f"/api/files/{file['id']}/download")
        assert download.status_code == 200 and download.content == content
        stored_provider = store.get_entity(owner, "providers", provider["id"])
        stored_server = store.get_entity(owner, "servers", server["id"])
        assert stored_provider is not None and stored_server is not None
        assert store.unseal(stored_provider["api_key"]) == "local-only-provider-secret"
        assert store.unseal(stored_server["password"]) == "local-only-server-secret"
    assert not store._CONNECTIONS
    assert (data / "master.key").read_bytes() == original_key
    assert {path.name for path in data.iterdir()} == {"earthai.db", "master.key", "uploads"}


def test_delete_recovers_hot_rollback_journal_after_process_exit_not_power_loss(nas_store):
    """os._exit tests SQLite process-crash recovery, not physical NAS power loss."""
    crashed = _python(nas_store, """
        import json
        import os
        from backend import store

        store.init_db()
        with store.connect() as db:
            db.execute("CREATE TABLE crash_markers (name TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE crash_pages (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("INSERT INTO crash_markers VALUES ('committed', 'original lowercase marker')")
            db.executemany("INSERT INTO crash_pages VALUES (?,?)", [(i, "a" * 8192) for i in range(384)])
        with store.connect() as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
            db.execute("PRAGMA cache_size=8")
            db.execute("PRAGMA cache_spill=ON")
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE crash_markers SET payload=upper(payload)")
            db.execute("INSERT INTO crash_markers VALUES ('uncommitted', 'MUST NOT SURVIVE')")
            db.execute("UPDATE crash_pages SET payload=upper(payload)")
            assert db.in_transaction
            journal = store.DATA / "earthai.db-journal"
            assert journal.stat().st_size > 512
            with journal.open("rb") as stream:
                assert stream.read(8) != bytes(8)
            print(json.dumps({"journal_size": journal.stat().st_size, "in_transaction": db.in_transaction}), flush=True)
            os._exit(0)
    """)
    crash_state = json.loads(crashed.stdout)
    journal = nas_store / "earthai.db-journal"
    assert crash_state["in_transaction"] is True
    assert journal.is_file() and journal.stat().st_size == crash_state["journal_size"] > 512
    assert not store._CONNECTIONS
    recovered = _python(nas_store, """
        import json
        from backend import store

        store.init_db()
        with store.connect() as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            assert [row[0] for row in db.execute("PRAGMA quick_check")] == ["ok"]
            markers = [list(row) for row in db.execute("SELECT name,payload FROM crash_markers ORDER BY name")]
            assert markers == [["committed", "original lowercase marker"]]
            assert db.execute("SELECT count(*) FROM crash_pages").fetchone()[0] == 384
            assert db.execute("SELECT count(*) FROM crash_pages WHERE payload != ?", ("a" * 8192,)).fetchone()[0] == 0
        store.close_connections()
        print(json.dumps({"quick_check": "ok", "markers": markers}))
    """)
    assert json.loads(recovered.stdout) == {"quick_check": "ok", "markers": [["committed", "original lowercase marker"]]}
    assert not journal.exists()


def test_unified_compose_leaves_existing_data_mount_to_platform():
    document = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert set(document) == {"services"}
    assert set(document["services"]) == {"earthai"}
    assert not (ROOT / "compose.nas.yaml").exists()
    service = document["services"]["earthai"]
    assert "volumes" not in service
    assert service["image"] == "earthai:latest"
    assert service["ports"] == ["0.0.0.0:8000:8000"]
    environment = service["environment"]
    assert environment["EARTHAI_DATA_DIR"] == "/app/data"
    assert environment["EARTHAI_SQLITE_JOURNAL_MODE"] == "DELETE"
    assert not {"EARTHAI_STATE_DIR", "EARTHAI_UPLOADS_DIR", "EARTHAI_NAS_DIR", "EARTHAI_LOCAL_STATE_DIR"} & environment.keys()
    assert "EARTHAI_NAS_DIR" not in (ROOT / ".env.example").read_text(encoding="utf-8")


def test_single_worker_root_and_container_safety_are_not_overridden():
    service = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]["earthai"]
    assert service["user"] == "0:0"
    assert service["init"] is True
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["cap_drop"] == ["ALL"]
    assert set(service["cap_add"]) == {"DAC_OVERRIDE", "FOWNER"}
    assert service["stop_grace_period"] == "150s"
    assert "command" not in service and "entrypoint" not in service
    assert not service.get("privileged", False)
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert [line for line in dockerfile.splitlines() if line.startswith("USER ")] == ["USER root"]
    command = json.loads(next(line.removeprefix("CMD ") for line in dockerfile.splitlines() if line.startswith("CMD ")))
    assert command[command.index("--workers") + 1] == "1"
    startup = shlex.split(next(line for line in (ROOT / "start.sh").read_text(encoding="utf-8").splitlines() if line.startswith("exec ")))
    assert startup[startup.index("--workers") + 1] == "1"
