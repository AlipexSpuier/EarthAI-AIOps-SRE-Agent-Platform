import asyncio
import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import zipfile
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
from pathlib import Path
from threading import Barrier, Event as ThreadEvent, Lock, get_ident
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import admin_catalog, defaults, engine, live_events, main, storage_paths, store, tools
from scripts import migrate_nas_state


ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Storage-performance-password!"


@pytest.fixture
def performance_store(monkeypatch, tmp_path):
    data_root = tmp_path / "nas"
    state = tmp_path / "state"
    uploads = data_root / "uploads"
    state.mkdir()
    uploads.mkdir(parents=True)
    store.close_connections()
    store._cipher.cache_clear()
    monkeypatch.setenv("EARTHAI_DATA_DIR", str(data_root))
    monkeypatch.setenv("EARTHAI_STATE_DIR", str(state))
    monkeypatch.setenv("EARTHAI_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("EARTHAI_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EARTHAI_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("EARTHAI_COOKIE_SECURE", "false")
    monkeypatch.setattr(store, "DATA_ROOT", data_root)
    monkeypatch.setattr(store, "DATA", state)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", state / "earthai.db")
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})

    async def idle_scheduler():
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "scheduler_loop", idle_scheduler)
    blocked = [
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected provider request"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure execution"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected server connection"))),
    ]
    for module, name, replacement in blocked:
        monkeypatch.setattr(module, name, replacement)
    store.init_db()
    try:
        yield state
    finally:
        store.close_connections()
        store._cipher.cache_clear()
        for _, name, replacement in blocked:
            assert replacement.call_count == 0, name


@pytest.fixture
def performance_client(performance_store):
    with TestClient(main.app) as client:
        yield client


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def _register(client):
    return _ok(client.post("/api/auth/register", json={
        "email": "storage@example.com", "password": PASSWORD, "name": "Storage test",
    }))


def _insert_user(id_):
    with store.connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (
            id_, f"{id_}@example.com", "unused-test-password-hash", store.dumps({"role": "user"}), store.now(),
        ))


def _profile(owner, **changes):
    with store.connect() as db:
        row = db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps({**store.loads(row["data"]), **changes}), owner))


@contextmanager
def _measure_storage(monkeypatch):
    store.close_connections()
    statements = []
    sqlite_connect = Mock(wraps=sqlite3.connect)
    checkout = Mock(wraps=store.connect)

    @contextmanager
    def traced_connect():
        with checkout() as db:
            db.set_trace_callback(statements.append)
            yield db

    with monkeypatch.context() as patch:
        patch.setattr(store.sqlite3, "connect", sqlite_connect)
        patch.setattr(store, "connect", traced_connect)
        try:
            yield statements, checkout, sqlite_connect
        finally:
            store.close_connections()


def _selects(statements):
    return [" ".join(sql.lower().split()) for sql in statements if sql.lstrip().upper().startswith("SELECT")]


def _grow_knowledge(owner, size=50):
    existing = store.list_entities(owner, "knowledge")
    added = []
    for index in range(len(existing), size):
        item = store.save_entity(owner, "knowledge", {"name": f"Storage knowledge {index}", "description": "local test"})
        with store.connect() as db:
            for document_index in range(2):
                text = f"Knowledge {index}, document {document_index}: " + "local evidence " * 120
                chunks = [text[start:start + 1400] for start in range(0, len(text), 1150)]
                doc_id = store.uid()
                db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", (
                    doc_id, owner, item["id"], f"{document_index}.txt", len(text.encode()), len(chunks), store.now(),
                ))
                db.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?)", [
                    (store.uid(), owner, item["id"], doc_id, f"{document_index}.txt", chunk) for chunk in chunks
                ])
        added.append(item)
    return added


def _grow_templates(size=50):
    existing = defaults.list_templates("knowledge")
    with store.connect() as db:
        for index in range(len(existing), size):
            item = defaults.save("knowledge", {"name": f"Storage template {index}"}, db=db)
            for document_index, length in enumerate((1150, 1151)):
                db.execute("INSERT INTO template_documents VALUES (?,?,?,?,?)", (
                    store.uid(), item["id"], f"{document_index}.txt", "文" * length, store.now(),
                ))
        defaults.sync_all(db)


def test_twenty_sequential_reads_open_at_most_one_sqlite_connection(performance_store, monkeypatch):
    store.close_connections()
    sqlite_connect = Mock(wraps=sqlite3.connect)
    monkeypatch.setattr(store.sqlite3, "connect", sqlite_connect)
    identities = set()
    for value in range(20):
        with store.connect() as db:
            identities.add(id(db))
            assert store.current_connection() is db
            assert db.row_factory is sqlite3.Row
            assert db.execute("SELECT ? AS value", (value,)).fetchone()["value"] == value
        assert store.current_connection() is None
    assert len(identities) == 1
    assert sqlite_connect.call_count <= 1


def test_checkout_enforces_foreign_keys_and_rolls_back_failed_transaction(performance_store):
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as db:
            identity = id(db)
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            db.execute("INSERT INTO users VALUES (?,?,?,?,?)", ("rolled-back", "rollback@example.com", "unused", "{}", store.now()))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", ("invalid-session", "missing-user", store.now()))
    with store.connect() as db:
        assert id(db) == identity
        assert not db.in_transaction
        assert db.execute("SELECT count(*) FROM users WHERE id='rolled-back'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert store.current_connection() is None


def test_checkout_rolls_back_base_exception_and_clears_callbacks(performance_store):
    trace = Mock()
    with pytest.raises(KeyboardInterrupt):
        with store.connect() as db:
            db.execute("INSERT INTO users VALUES (?,?,?,?,?)", ("interrupted", "interrupt@example.com", "unused", "{}", store.now()))
            raise KeyboardInterrupt
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        db.set_trace_callback(trace)
        db.set_authorizer(lambda *args: sqlite3.SQLITE_DENY)
    trace.reset_mock()
    with store.connect() as db:
        assert db.execute("SELECT 42").fetchone()[0] == 42
    trace.assert_not_called()


def test_nested_checkouts_are_exclusive_and_restore_current_connection(performance_store):
    with store.connect() as outer:
        with store.connect() as inner:
            assert inner is not outer
            assert store.current_connection() is inner
            assert inner.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.current_connection() is outer
        assert outer.execute("SELECT 1").fetchone()[0] == 1
    assert store.current_connection() is None


def test_database_path_switches_never_reuse_another_databases_connection(performance_store, monkeypatch, tmp_path):
    original_path = store.DB_PATH
    _insert_user("original")
    with store.connect() as original:
        original_identity = id(original)
    with monkeypatch.context() as patch:
        patch.setattr(store, "DB_PATH", tmp_path / "other.db")
        store.init_db()
        with store.connect() as other:
            assert id(other) != original_identity
            assert other.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        _insert_user("other")
    assert store.DB_PATH == original_path
    with store.connect() as original:
        assert id(original) == original_identity
        assert [row["id"] for row in original.execute("SELECT id FROM users")] == ["original"]


def test_concurrent_checkouts_have_unique_connections_while_held(performance_store):
    workers = 12
    barrier = Barrier(workers, timeout=10)
    lock = Lock()
    active = set()

    def read(_):
        with store.connect() as db:
            identity = id(db)
            with lock:
                assert identity not in active
                active.add(identity)
            barrier.wait()
            with lock:
                assert len(active) == workers
            barrier.wait()
            assert db.execute("SELECT 1").fetchone()[0] == 1
            with lock:
                active.remove(identity)
            return identity

    with ThreadPoolExecutor(max_workers=workers) as executor:
        identities = list(executor.map(read, range(workers)))
    assert len(set(identities)) == workers
    assert not active
    assert all(pool.qsize() <= 8 for pool in store._CONNECTIONS.values())


def test_close_connections_is_idempotent_and_does_not_load_credentials(performance_store, monkeypatch):
    with store.connect() as db:
        assert db.execute("SELECT 1").fetchone()[0] == 1
    credential_reader = Mock(side_effect=AssertionError("shutdown must not load credentials"))
    monkeypatch.setattr(store, "cipher", credential_reader)
    monkeypatch.setattr(Path, "read_text", credential_reader)
    store.close_connections()
    store.close_connections()
    assert not store._CONNECTIONS
    credential_reader.assert_not_called()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        db.execute("SELECT 1")


def test_app_shutdown_closes_pool_without_loading_credentials(performance_store, monkeypatch):
    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200
        with store.connect() as db:
            assert db.execute("SELECT 1").fetchone()[0] == 1
        credential_reader = Mock(side_effect=AssertionError("shutdown must not load credentials"))
        monkeypatch.setattr(store, "cipher", credential_reader)
    credential_reader.assert_not_called()
    assert not store._CONNECTIONS
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        db.execute("SELECT 1")


def test_fifty_knowledge_items_use_constant_queries_and_connections(performance_client, monkeypatch):
    client = performance_client
    owner = _register(client)["id"]
    with _measure_storage(monkeypatch) as (small_sql, small_checkout, small_connect):
        small = _ok(client.get("/api/knowledge"))
    assert len(small) == 50
    with store.connect() as db:
        expected = {row["template_id"]: (row["documents"], row["chunks"]) for row in db.execute(
            "SELECT template_id,count(*) documents,sum((length(content)+1149)/1150) chunks "
            "FROM template_documents GROUP BY template_id",
        )}
    assert {item["default_template_id"]: (item["document_count"], item["chunk_count"]) for item in small} == expected
    assert all(3 <= item["document_count"] <= 12 for item in small)
    assert 150 <= sum(item["document_count"] for item in small) <= 600
    added = _grow_knowledge(owner, size=100)
    _insert_user("unrelated")
    unrelated = store.save_entity("unrelated", "knowledge", {"name": "Other owner's knowledge"})
    with store.connect() as db:
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", (
            store.uid(), "unrelated", unrelated["id"], "private.txt", 100, 999, store.now(),
        ))
    with _measure_storage(monkeypatch) as (large_sql, large_checkout, large_connect):
        large = _ok(client.get("/api/knowledge"))
    assert len(large) == 100
    assert len(_selects(small_sql)) == len(_selects(large_sql)) == 4
    assert small_checkout.call_count == large_checkout.call_count == 4
    assert small_connect.call_count <= 1 and large_connect.call_count <= 1
    grouped = [sql for sql in _selects(large_sql) if "from documents" in sql]
    assert len(grouped) == 1 and "group by knowledge_id" in grouped[0]
    by_id = {item["id"]: item for item in large}
    assert unrelated["id"] not in by_id
    assert all(by_id[item["id"]]["document_count"] == 2 and by_id[item["id"]]["chunk_count"] == 4 for item in added)
    assert sum(item["document_count"] for item in large) == sum(item["document_count"] for item in small) + 100
    assert sum(item["chunk_count"] for item in large) == sum(item["chunk_count"] for item in small) + 200


def test_fifty_admin_knowledge_templates_aggregate_without_loading_each_body(performance_client, monkeypatch):
    client = performance_client
    _ok(client.post("/api/auth/login", json={"email": "admin", "password": "admin"}))
    _ok(client.post("/api/auth/password", json={"current_password": "admin", "new_password": PASSWORD}))
    body_loader = Mock(side_effect=AssertionError("list must not fetch template document bodies per item"))
    monkeypatch.setattr(admin_catalog, "document_details", body_loader)
    with _measure_storage(monkeypatch) as (small_sql, small_checkout, small_connect):
        small = _ok(client.get("/api/admin/defaults/knowledge"))
    assert len(small) == 50
    with store.connect() as db:
        expected = {row["template_id"]: (row["documents"], row["chunks"]) for row in db.execute(
            "SELECT template_id,count(*) documents,sum((length(content)+1149)/1150) chunks "
            "FROM template_documents GROUP BY template_id",
        )}
    assert {item["id"]: (item["document_count"], item["chunk_count"]) for item in small} == expected
    assert all(3 <= item["document_count"] <= 12 for item in small)
    assert 150 <= sum(item["document_count"] for item in small) <= 600
    _grow_templates(size=100)
    with _measure_storage(monkeypatch) as (large_sql, large_checkout, large_connect):
        large = _ok(client.get("/api/admin/defaults/knowledge"))
    assert len(large) == 100
    assert len(_selects(small_sql)) == len(_selects(large_sql)) == 4
    assert small_checkout.call_count == large_checkout.call_count == 3
    assert small_connect.call_count <= 1 and large_connect.call_count <= 1
    document_sql = [sql for sql in _selects(large_sql) if "from template_documents" in sql]
    assert len(document_sql) == 1
    assert "group by template_id" in document_sql[0]
    assert "length(content)" in document_sql[0]
    assert not document_sql[0].startswith(("select *", "select content", "select id,name,content"))
    body_loader.assert_not_called()
    added = [item for item in large if item["name"].startswith("Storage template ")]
    assert len(added) == 50
    assert all(item["document_count"] == 2 and item["chunk_count"] == 3 for item in added)
    assert sum(item["document_count"] for item in large) == sum(item["document_count"] for item in small) + 100
    assert sum(item["chunk_count"] for item in large) == sum(item["chunk_count"] for item in small) + 150
    assert all("content" not in item for item in large)


def test_gets_are_read_only_and_profile_and_permissions_are_never_cached(performance_client, monkeypatch):
    client = performance_client
    owner = _register(client)["id"]
    _ok(client.get("/api/agents"))
    with _measure_storage(monkeypatch) as (statements, _, _):
        for _ in range(3):
            _ok(client.get("/api/auth/me"))
            _ok(client.get("/api/agents"))
            _ok(client.get("/api/knowledge"))
    assert statements
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    _ok(client.patch("/api/auth/me", json={"name": "Updated immediately"}))
    assert _ok(client.get("/api/auth/me"))["name"] == "Updated immediately"
    _profile(owner, disabled=True)
    assert client.get("/api/agents").status_code == 403
    _profile(owner, disabled=False, role="admin")
    assert client.get("/api/agents").status_code == 403
    assert client.get("/api/admin/defaults/knowledge").status_code == 200
    _profile(owner, role="user")
    assert client.get("/api/admin/defaults/knowledge").status_code == 403
    assert client.get("/api/agents").status_code == 200
    _profile(owner, must_change_password=True)
    assert client.get("/api/agents").status_code == 403
    assert _ok(client.get("/api/auth/me"))["must_change_password"] is True


@pytest.mark.parametrize("state_override,uploads_override", [(False, False), (True, False), (False, True), (True, True)])
def test_storage_paths_preserve_legacy_layout_and_honor_overrides(monkeypatch, tmp_path, state_override, uploads_override):
    data = tmp_path / "nas"
    state = tmp_path / "local-state"
    uploads = tmp_path / "nas-uploads"
    monkeypatch.setenv("EARTHAI_DATA_DIR", str(data))
    monkeypatch.delenv("EARTHAI_STATE_DIR", raising=False)
    monkeypatch.delenv("EARTHAI_UPLOADS_DIR", raising=False)
    if state_override:
        monkeypatch.setenv("EARTHAI_STATE_DIR", str(state))
    if uploads_override:
        monkeypatch.setenv("EARTHAI_UPLOADS_DIR", str(uploads))
    assert storage_paths.paths() == (data, state if state_override else data, uploads if uploads_override else data / "uploads")


def test_storage_paths_unset_data_uses_repository_default_without_creating_it(monkeypatch):
    for name in ("EARTHAI_DATA_DIR", "EARTHAI_STATE_DIR", "EARTHAI_UPLOADS_DIR"):
        monkeypatch.delenv(name, raising=False)
    default = ROOT / "data"
    assert storage_paths.paths() == (default, default, default / "uploads")


@pytest.fixture
def stopped_nas(performance_store, monkeypatch):
    source = performance_store
    uploads = source / "uploads"
    branding = source / "branding"
    uploads.mkdir()
    branding.mkdir()
    (uploads / "legacy.txt").write_text("Original NAS upload", encoding="utf-8")
    (branding / "logo.txt").write_text("Original branding asset", encoding="utf-8")
    (source / "master.key").write_bytes(Fernet.generate_key())
    monkeypatch.delenv("EARTHAI_MASTER_KEY", raising=False)
    store._cipher.cache_clear()
    _insert_user("migration-owner")
    sealed = store.seal("original-provider-secret")
    provider = store.save_entity("migration-owner", "providers", {"name": "Offline provider", "api_key": sealed})
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (
            "migration-run", "migration-owner", "offline-conversation", "completed", "{}", store.now(), store.now(),
        ))
    store.close_connections()
    return source, sealed, provider["id"]


def _file_hashes(directory):
    return {
        path.relative_to(directory): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*") if path.is_file()
    }


def _assert_original_files_unchanged(directory, hashes):
    assert {path: hashlib.sha256((directory / path).read_bytes()).hexdigest() for path in hashes} == hashes


def _subprocess_env(data, state, uploads, backup=None):
    env = os.environ.copy()
    for name in ("EARTHAI_DATA_DIR", "EARTHAI_STATE_DIR", "EARTHAI_UPLOADS_DIR", "EARTHAI_MASTER_KEY", "EARTHAI_BACKUP_DIR"):
        env.pop(name, None)
    env.update({
        "EARTHAI_DATA_DIR": str(data), "EARTHAI_STATE_DIR": str(state), "EARTHAI_UPLOADS_DIR": str(uploads),
        "PYTHONPATH": str(ROOT),
    })
    if backup is not None:
        env["EARTHAI_BACKUP_DIR"] = str(backup)
    return env


@pytest.mark.parametrize("missing", ["database", "key"])
def test_fresh_process_refuses_unmigrated_database_or_missing_original_key(stopped_nas, tmp_path, missing):
    source, _, _ = stopped_nas
    destination = tmp_path / "unmigrated"
    destination.mkdir()
    if missing == "key":
        (destination / "earthai.db").write_bytes((source / "earthai.db").read_bytes())
    hashes = _file_hashes(source)
    result = subprocess.run(
        [sys.executable, "-c", "from backend import store; store.init_db(); store.cipher()"],
        cwd=ROOT, env=_subprocess_env(source, destination, source / "uploads"), capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert ("尚未迁移" if missing == "database" else "缺少原 master.key") in result.stderr
    assert not (destination / "master.key").exists()
    if missing == "database":
        assert not (destination / "earthai.db").exists()
    _assert_original_files_unchanged(source, hashes)


def test_stopped_migration_uses_backup_preserves_source_and_original_cipher(stopped_nas, tmp_path, monkeypatch):
    source, sealed, provider_id = stopped_nas
    destination = tmp_path / "migrated-state"
    hashes = _file_hashes(source)
    backup_calls = []
    original_connect = sqlite3.connect

    class BackupConnection(sqlite3.Connection):
        def backup(self, target, *args, **kwargs):
            backup_calls.append(True)
            return super().backup(target, *args, **kwargs)

    def tracked_connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=BackupConnection)

    with monkeypatch.context() as patch:
        patch.setattr(migrate_nas_state.sqlite3, "connect", tracked_connect)
        result = migrate_nas_state.migrate(source, destination)
    assert backup_calls == [True]
    assert result == {
        "ok": True, "database": str(destination / "earthai.db"), "key_file_preserved": True,
        "branding_preserved": True, "uploads_left_at": str(source / "uploads"), "source_untouched": True,
    }
    _assert_original_files_unchanged(source, hashes)
    assert not (destination / "uploads").exists()
    assert (destination / "master.key").read_bytes() == (source / "master.key").read_bytes()
    assert (destination / "branding" / "logo.txt").read_bytes() == (source / "branding" / "logo.txt").read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o700
    assert (destination / "earthai.db").stat().st_mode & 0o777 == 0o600
    assert (destination / "master.key").stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(destination / "earthai.db")) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        data = store.loads(db.execute("SELECT data FROM entities WHERE id=?", (provider_id,)).fetchone()[0])
    assert data["api_key"] == sealed
    assert Fernet((destination / "master.key").read_bytes()).decrypt(sealed.encode()).decode() == "original-provider-secret"


@pytest.mark.parametrize("rejection", ["nonempty", "queued", "running", "waiting_approval", "same", "child", "parent", "missing-key"])
def test_migration_rejects_unsafe_sources_and_destinations(stopped_nas, tmp_path, rejection):
    source, _, _ = stopped_nas
    destination = tmp_path / "rejected-state"
    expected = ""
    if rejection == "nonempty":
        destination.mkdir()
        (destination / "keep.txt").write_text("do not overwrite", encoding="utf-8")
        expected = "必须为空"
    elif rejection in {"queued", "running", "waiting_approval"}:
        with closing(sqlite3.connect(source / "earthai.db")) as db, db:
            db.execute("UPDATE runs SET status=? WHERE id='migration-run'", (rejection,))
        expected = "仍有活动任务"
    elif rejection in {"same", "child", "parent"}:
        destination = {"same": source, "child": source / "child", "parent": source.parent}[rejection]
        expected = "不能互相包含"
    elif rejection == "missing-key":
        (source / "master.key").unlink()
        expected = "未找到原 master.key"
    hashes = _file_hashes(source)
    with pytest.raises(ValueError, match=expected):
        migrate_nas_state.migrate(source, destination)
    _assert_original_files_unchanged(source, hashes)
    if rejection == "nonempty":
        assert (destination / "keep.txt").read_text(encoding="utf-8") == "do not overwrite"
        assert set(path.name for path in destination.iterdir()) == {"keep.txt"}
    elif rejection not in {"same", "parent"}:
        assert not destination.exists()


def test_backup_subprocess_includes_local_state_key_branding_and_nas_uploads(stopped_nas, tmp_path):
    source, sealed, _ = stopped_nas
    destination = tmp_path / "backup-state"
    backups = tmp_path / "archives"
    uploads = tmp_path / "uploads-on-nas"
    uploads.mkdir()
    (uploads / "nas-upload.txt").write_text("Upload remains on NAS", encoding="utf-8")
    hashes = _file_hashes(source)
    migrate_nas_state.migrate(source, destination)
    (destination / "branding" / "logo.txt").write_text("Local-state branding", encoding="utf-8")
    with closing(sqlite3.connect(destination / "earthai.db")) as db, db:
        db.execute("CREATE TABLE backup_state_marker (value TEXT NOT NULL)")
        db.execute("INSERT INTO backup_state_marker VALUES ('local-state-database')")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backup.py")], cwd=ROOT,
        env=_subprocess_env(source, destination, uploads, backups), capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    archives = list(backups.glob("*.zip"))
    assert len(archives) == 1
    assert not list(backups.glob("snapshot-*.db"))
    with zipfile.ZipFile(archives[0]) as archive:
        assert set(archive.namelist()) == {
            "data/earthai.db", "data/master.key", "data/branding/logo.txt", "data/uploads/nas-upload.txt",
        }
        assert archive.read("data/master.key") == (source / "master.key").read_bytes()
        assert archive.read("data/branding/logo.txt") == b"Local-state branding"
        assert archive.read("data/uploads/nas-upload.txt") == b"Upload remains on NAS"
        assert Fernet(archive.read("data/master.key")).decrypt(sealed.encode()).decode() == "original-provider-secret"
        extracted = tmp_path / "backup-check.db"
        extracted.write_bytes(archive.read("data/earthai.db"))
    with closing(sqlite3.connect(extracted)) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert db.execute("SELECT value FROM backup_state_marker").fetchone()[0] == "local-state-database"
    _assert_original_files_unchanged(source, hashes)
    assert (uploads / "nas-upload.txt").read_text(encoding="utf-8") == "Upload remains on NAS"


@pytest.mark.asyncio
async def test_live_notification_from_thread_wakes_every_listener_for_only_that_run():
    run_id, other_id = store.uid(), store.uid()
    listeners = [live_events.listen(run_id), live_events.listen(run_id)]
    unrelated = live_events.listen(other_id)
    try:
        await asyncio.to_thread(live_events.notify, run_id)
        await asyncio.wait_for(asyncio.gather(*(event.wait() for _, event in listeners)), timeout=1)
        assert not unrelated[1].is_set()
    finally:
        for listener in listeners:
            live_events.unlisten(run_id, listener)
        live_events.unlisten(other_id, unrelated)
    assert run_id not in live_events._WAITERS
    assert other_id not in live_events._WAITERS


@pytest.mark.asyncio
async def test_unlisten_removes_listener_without_spurious_wakes():
    run_id = store.uid()
    listener = live_events.listen(run_id)
    live_events.unlisten(run_id, listener)
    live_events.unlisten(run_id, listener)
    await asyncio.to_thread(live_events.notify, run_id)
    assert not listener[1].is_set()
    assert run_id not in live_events._WAITERS


def test_notify_without_listeners_never_accesses_database(monkeypatch):
    checkout = Mock(side_effect=AssertionError("notifications must not access database"))
    monkeypatch.setattr(store, "connect", checkout)
    monkeypatch.setattr(sqlite3, "connect", checkout)
    live_events.notify(store.uid())
    checkout.assert_not_called()


def test_in_process_event_notifications_are_deployed_with_one_worker():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    command = json.loads(next(line.removeprefix("CMD ") for line in dockerfile.splitlines() if line.startswith("CMD ")))
    assert command[command.index("--workers") + 1] == "1"
    startup = shlex.split(next(line for line in (ROOT / "start.sh").read_text(encoding="utf-8").splitlines() if line.startswith("exec ")))
    assert startup[startup.index("--workers") + 1] == "1"


@pytest.mark.asyncio
async def test_sse_route_streams_three_thread_notified_events_without_polling(monkeypatch):
    run_id = store.uid()
    owner = "stream-owner"
    persisted = []
    run = {"status": "running"}
    lock = Lock()
    loop_thread = get_ident()
    signal_waits = asyncio.Queue()
    received = asyncio.Queue()
    original_listen = live_events.listen

    def listen(id_):
        listener = original_listen(id_)
        original_wait = listener[1].wait

        async def wait():
            signal_waits.put_nowait(None)
            return await original_wait()

        monkeypatch.setattr(listener[1], "wait", wait)
        return listener

    def snapshot(snapshot_owner, snapshot_run, cursor):
        assert get_ident() != loop_thread
        assert (snapshot_owner, snapshot_run) == (owner, run_id)
        with lock:
            return deepcopy([event for event in persisted if event["id"] > cursor]), dict(run)

    snapshot_reader = Mock(side_effect=snapshot)
    monkeypatch.setattr(main, "required_run", Mock(return_value={"id": run_id, **run}))
    monkeypatch.setattr(main, "event_snapshot", snapshot_reader)
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(live_events, "listen", listen)
    request = Mock(headers={}, is_disconnected=AsyncMock(return_value=False))
    endpoint = next(route.endpoint for route in main.app.routes if route.path == "/api/runs/{id_}/events")
    response = await endpoint(run_id, request, after=0, user={"id": owner})
    assert response.media_type == "text/event-stream"

    async def consume():
        async for message in response.body_iterator:
            await received.put(message)

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(signal_waits.get(), timeout=5)
        assert snapshot_reader.call_count == 1
        for index in range(1, 4):
            event = {"id": index, "run_id": run_id, "type": "output", "data": {"text": f"event {index}"}}
            with lock:
                persisted.append(event)
                if index == 3:
                    run["status"] = "completed"
            await asyncio.to_thread(live_events.notify, run_id)
            message = await asyncio.wait_for(received.get(), timeout=5)
            assert message == f"id: {index}\ndata: {store.dumps(event)}\n\n"
            if index < 3:
                await asyncio.wait_for(signal_waits.get(), timeout=5)
                assert snapshot_reader.call_count == index + 1
        await asyncio.wait_for(consumer, timeout=5)
        assert snapshot_reader.call_count == 5
        assert [call.args for call in snapshot_reader.call_args_list] == [
            (owner, run_id, cursor) for cursor in (0, 0, 1, 2, 3)
        ]
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        await response.body_iterator.aclose()
    assert run_id not in live_events._WAITERS


def _insert_run(owner, status="running"):
    run_id = store.uid()
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (
            run_id, owner, store.uid(), status, "{}", store.now(), store.now(),
        ))
    return run_id


@pytest.mark.asyncio
async def test_sse_drains_done_written_between_event_read_and_terminal_status(performance_store, monkeypatch):
    owner = "snapshot-race-owner"
    _insert_user(owner)
    run_id = _insert_run(owner)
    loop = asyncio.get_running_loop()
    empty_batch_read = asyncio.Event()
    continue_status_read = ThreadEvent()
    snapshot_finished = ThreadEvent()
    original_connect = store.connect
    original_snapshot = main.event_snapshot
    snapshots = []
    intercept_first_read = True
    read_lock = Lock()

    @contextmanager
    def controlled_connect():
        nonlocal intercept_first_read
        with original_connect() as db:
            connection = Mock(wraps=db)

            def execute(sql, *args, **kwargs):
                nonlocal intercept_first_read
                cursor = db.execute(sql, *args, **kwargs)
                with read_lock:
                    intercept = sql.startswith("SELECT * FROM events WHERE run_id=?") and intercept_first_read
                    if intercept:
                        intercept_first_read = False
                if not intercept:
                    return cursor
                result = Mock(wraps=cursor)

                def fetchall():
                    rows = cursor.fetchall()
                    assert rows == []
                    loop.call_soon_threadsafe(empty_batch_read.set)
                    assert continue_status_read.wait(timeout=5), "terminal writer did not release snapshot"
                    return rows

                result.fetchall.side_effect = fetchall
                return result

            connection.execute.side_effect = execute
            yield connection

    def snapshot(*args):
        try:
            result = original_snapshot(*args)
            snapshots.append(deepcopy(result))
            return result
        finally:
            snapshot_finished.set()

    snapshot_reader = Mock(side_effect=snapshot)
    monkeypatch.setattr(store, "connect", controlled_connect)
    monkeypatch.setattr(main, "event_snapshot", snapshot_reader)
    request = Mock(headers={}, is_disconnected=AsyncMock(return_value=False))
    response = await main.run_events(run_id, request, user={"id": owner})

    async def consume():
        return [message async for message in response.body_iterator]

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(empty_batch_read.wait(), timeout=5)
        assert not consumer.done()
        store.update_run(owner, run_id, status="completed")
        done = store.emit(run_id, "done", {"status": "completed", "summary": "written between both SELECTs"})
        continue_status_read.set()
        messages = await asyncio.wait_for(consumer, timeout=5)
        assert messages == [f"id: {done['id']}\ndata: {store.dumps(done)}\n\n"]
        assert snapshots == [([], {"status": "completed"}), ([done], {"status": "completed"})]
        assert [call.args for call in snapshot_reader.call_args_list] == [(owner, run_id, 0), (owner, run_id, 0)]
    finally:
        continue_status_read.set()
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        await response.body_iterator.aclose()
        if empty_batch_read.is_set():
            assert await asyncio.to_thread(snapshot_finished.wait, 5)
    assert run_id not in live_events._WAITERS


@pytest.mark.asyncio
async def test_sse_keeps_terminal_stream_open_until_registered_producer_finishes(performance_store, monkeypatch):
    owner = "terminal-producer-owner"
    _insert_user(owner)
    run_id = _insert_run(owner, "completed")
    release_producer = asyncio.Event()
    waiting_for_producer = asyncio.Event()
    persisted = []

    async def produce():
        await release_producer.wait()
        persisted.append(store.emit(run_id, "done", {"status": "completed", "summary": "late terminal event"}))

    producer = asyncio.create_task(produce())
    engine.TASKS[run_id] = producer
    original_wait = asyncio.wait

    async def wait_for_producer(tasks):
        assert tasks == {producer}
        waiting_for_producer.set()
        return await original_wait(tasks)

    producer_wait = AsyncMock(side_effect=wait_for_producer)
    snapshot_reader = Mock(wraps=main.event_snapshot)
    monkeypatch.setattr(main.asyncio, "wait", producer_wait)
    monkeypatch.setattr(main, "event_snapshot", snapshot_reader)
    request = Mock(headers={}, is_disconnected=AsyncMock(return_value=False))
    response = await main.run_events(run_id, request, user={"id": owner})

    async def consume():
        return [message async for message in response.body_iterator]

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(waiting_for_producer.wait(), timeout=5)
        assert not consumer.done()
        assert not producer.done()
        assert persisted == []
        assert snapshot_reader.call_count == 1
        assert run_id in live_events._WAITERS
        release_producer.set()
        messages = await asyncio.wait_for(consumer, timeout=5)
        await asyncio.wait_for(producer, timeout=5)
        assert not producer.cancelled()
        assert len(persisted) == 1
        done = persisted[0]
        assert messages == [f"id: {done['id']}\ndata: {store.dumps(done)}\n\n"]
        producer_wait.assert_awaited_once_with({producer})
        assert [call.args for call in snapshot_reader.call_args_list] == [(owner, run_id, 0), (owner, run_id, 0)]
    finally:
        release_producer.set()
        consumer.cancel()
        await asyncio.gather(consumer, producer, return_exceptions=True)
        await response.body_iterator.aclose()
    assert run_id not in live_events._WAITERS


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["cancel", "disconnect"])
async def test_stopping_sse_consumer_does_not_cancel_registered_producer(performance_store, monkeypatch, stop):
    owner = "disconnected-producer-owner"
    _insert_user(owner)
    run_id = _insert_run(owner, "completed")
    release_producer = asyncio.Event()
    waiting_for_producer = asyncio.Event()
    disconnected = asyncio.Event()
    sent = []

    async def produce():
        await release_producer.wait()
        return store.emit(run_id, "done", {"status": "completed", "summary": "producer survived disconnect"})

    producer = asyncio.create_task(produce())
    engine.TASKS[run_id] = producer
    original_wait = asyncio.wait

    async def wait_for_producer(tasks):
        assert tasks == {producer}
        waiting_for_producer.set()
        return await original_wait(tasks)

    monkeypatch.setattr(main.asyncio, "wait", wait_for_producer)
    snapshot_reader = Mock(wraps=main.event_snapshot)
    monkeypatch.setattr(main, "event_snapshot", snapshot_reader)
    request = Mock(headers={}, is_disconnected=AsyncMock(return_value=False))
    response = await main.run_events(run_id, request, user={"id": owner})

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    consumer = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send))
    try:
        await asyncio.wait_for(waiting_for_producer.wait(), timeout=5)
        assert not producer.done()
        assert not consumer.done()
        if stop == "cancel":
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(consumer, timeout=5)
        else:
            disconnected.set()
            await asyncio.wait_for(consumer, timeout=5)
        assert snapshot_reader.call_count == 1
        assert not producer.done()
        assert producer.cancelling() == 0
        assert engine.TASKS[run_id] is producer
        assert run_id not in live_events._WAITERS
        assert sent[0]["type"] == "http.response.start"
        assert not any(message.get("body") for message in sent)
        release_producer.set()
        done = await asyncio.wait_for(producer, timeout=5)
        assert not producer.cancelled()
        assert store.events(run_id) == [done]
    finally:
        disconnected.set()
        release_producer.set()
        consumer.cancel()
        await asyncio.gather(consumer, producer, return_exceptions=True)
        await response.body_iterator.aclose()


def test_event_snapshot_reads_real_sql_decodes_payload_and_checks_run_owner(performance_store, monkeypatch):
    owner = "real-snapshot-owner"
    _insert_user(owner)
    _insert_user("other-snapshot-owner")
    run_id = _insert_run(owner)
    other_run = _insert_run("other-snapshot-owner", "failed")
    first = store.emit(run_id, "output", {"text": "first event"})
    store.emit(other_run, "output", {"text": "unrelated event"})
    second = store.emit(run_id, "output", {"text": "中文\nsecond event", "nested": {"ok": True, "items": [1, None]}})
    with _measure_storage(monkeypatch) as (statements, checkout, sqlite_connect):
        batch, run = main.event_snapshot(owner, run_id, first["id"])
    assert batch == [second]
    assert run == {"status": "running"}
    assert checkout.call_count == sqlite_connect.call_count == 1
    selects = _selects(statements)
    assert len(selects) == 2
    assert "from events" in selects[0] and "order by id limit 1000" in selects[0]
    assert "from runs where owner=" in selects[1]
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    _, other_owner_run = main.event_snapshot("other-snapshot-owner", run_id, first["id"])
    assert other_owner_run is None
    assert main.event_snapshot(owner, "missing-run", 0) == ([], None)
    store.update_run(owner, run_id, status="completed")
    done = store.emit(run_id, "done", {"status": "completed"})
    assert main.event_snapshot(owner, run_id, second["id"]) == ([done], {"status": "completed"})


def _sse_events(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    for frame in response.text.split("\n\n"):
        if not frame:
            continue
        fields = dict(line.split(": ", 1) for line in frame.splitlines())
        assert set(fields) == {"id", "data"}
        event = json.loads(fields["data"])
        assert int(fields["id"]) == event["id"]
        events.append(event)
    return events


def test_http_sse_reconnect_drains_over_one_thousand_persisted_events_without_loss(performance_client, monkeypatch):
    client = performance_client
    owner = _register(client)["id"]
    run_id = _insert_run(owner, "completed")
    _insert_user("other-http-sse-owner")
    other_run = _insert_run("other-http-sse-owner", "completed")
    stamp = store.now()
    rows = []
    for index in range(2105):
        rows.append((run_id, "output", store.dumps({"sequence": index, "text": f"事件 {index}\nnext line"}), stamp))
        if index % 250 == 0:
            rows.append((other_run, "output", store.dumps({"text": "another owner's event"}), stamp))
    rows.append((run_id, "done", store.dumps({"status": "completed", "summary": "all events persisted"}), stamp))
    with store.connect() as db:
        db.executemany("INSERT INTO events(run_id,type,data,created_at) VALUES (?,?,?,?)", rows)
        expected = [{**dict(row), "data": store.loads(row["data"])} for row in db.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,),
        )]
    assert len(expected) == 2106
    assert expected[-1]["type"] == "done"
    snapshot_reader = Mock(wraps=main.event_snapshot)
    monkeypatch.setattr(main, "event_snapshot", snapshot_reader)
    path = f"/api/runs/{run_id}/events"
    complete = _sse_events(client.get(path))
    assert complete == expected
    assert [call.args for call in snapshot_reader.call_args_list] == [
        (owner, run_id, cursor) for cursor in (0, expected[999]["id"], expected[1999]["id"], expected[-1]["id"])
    ]

    for header_index, after_index in ((499, 249), (249, 999)):
        snapshot_reader.reset_mock()
        cursor_index = max(header_index, after_index)
        resumed = _sse_events(client.get(path, params={"after": expected[after_index]["id"]}, headers={
            "Last-Event-ID": str(expected[header_index]["id"]),
        }))
        assert resumed == expected[cursor_index + 1:]
        assert complete[:cursor_index + 1] + resumed == expected
        assert len({event["id"] for event in resumed}) == len(resumed)
        assert resumed[-1]["type"] == "done"
        assert [call.args for call in snapshot_reader.call_args_list] == [
            (owner, run_id, cursor) for cursor in (
                expected[cursor_index]["id"], expected[cursor_index + 1000]["id"], expected[-1]["id"],
            )
        ]

    snapshot_reader.reset_mock()
    assert _sse_events(client.get(path, headers={"Last-Event-ID": str(expected[-1]["id"])})) == []
    assert [call.args for call in snapshot_reader.call_args_list] == [(owner, run_id, expected[-1]["id"])] * 2
    snapshot_reader.reset_mock()
    client.cookies.clear()
    client.cookies.set("earthai_session", store.new_session("other-http-sse-owner"))
    assert client.get(path).status_code == 404
    snapshot_reader.assert_not_called()
    assert run_id not in live_events._WAITERS


def test_repeated_unseal_reads_master_key_only_once(performance_store, monkeypatch):
    key = Fernet.generate_key()
    key_file = performance_store / "master.key"
    key_file.write_bytes(key)
    monkeypatch.delenv("EARTHAI_MASTER_KEY", raising=False)
    store._cipher.cache_clear()
    token = Fernet(key).encrypt(b"sealed before startup").decode()
    read_text = Mock(wraps=Path.read_text)

    def tracked_read(path, *args, **kwargs):
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read)
    for _ in range(20):
        assert store.unseal(token) == "sealed before startup"
        assert store.unseal(store.seal("round trip")) == "round trip"
    assert read_text.call_count <= 1
    read_text.assert_called_once_with(key_file)
    assert key_file.read_bytes() == key


def test_environment_master_key_never_reads_or_creates_key_file(performance_store, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv("EARTHAI_MASTER_KEY", key.decode())
    store._cipher.cache_clear()
    key_reader = Mock(side_effect=AssertionError("environment master key must not access key file"))
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", key_reader)
        patch.setattr(os, "open", key_reader)
        for _ in range(20):
            token = store.seal("environment secret")
            assert Fernet(key).decrypt(token.encode()) == b"environment secret"
            assert store.unseal(token) == "environment secret"
    key_reader.assert_not_called()
    assert not (performance_store / "master.key").exists()
