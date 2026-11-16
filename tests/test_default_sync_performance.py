import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from uuid import NAMESPACE_URL, uuid5

import pytest

from backend import admin_catalog, defaults, main, store, usage


OWNERS = ("a-owner", "b-owner", "c-owner")
STAMP = "2030-01-01T00:00:00+00:00"
TABLES = (
    "default_templates", "template_documents", "entities", "documents", "chunks", "default_sync_revisions", "platform_settings",
    "default_owner_states", "remote_agent_clicks",
)


def _insert_user(db, owner, role="user"):
    db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (owner, owner + "@example.test", "unused", store.dumps({"role": role}), STAMP))


def _insert_template(db, id_, kind, data, revision=STAMP):
    db.execute("INSERT INTO default_templates VALUES (?,?,?,?,?,?)", (id_, kind, store.dumps(data), None, STAMP, revision))


def _copy_id(owner, source):
    return str(uuid5(NAMESPACE_URL, f"earthai.default:{owner}:{source}"))


def _snapshot():
    with store.connect() as db:
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in TABLES}


@contextmanager
def _trace(monkeypatch, authorizer=None):
    statements = []
    original = store.connect

    @contextmanager
    def connect():
        with original() as db:
            db.set_trace_callback(lambda sql: statements.append(" ".join(sql.lower().split())))
            if authorizer:
                db.set_authorizer(authorizer)
            yield db

    with monkeypatch.context() as patch:
        patch.setattr(store, "connect", connect)
        yield statements


def _selects(statements, table):
    return [sql for sql in statements if sql.startswith("select ") and f"from {table}" in sql]


def _writes(statements):
    return [sql for sql in statements if sql.startswith(("insert ", "update ", "delete ", "replace ", "create "))]


def _deny_password(action, table, column, database, source):
    if action == sqlite3.SQLITE_READ and table == "users" and column == "password":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "sync.db")
    monkeypatch.setattr(store, "DATA", tmp_path)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(store, "UPLOADS", uploads)
    store.init_db()
    defaults.init_tables()
    usage.initialize()
    values = {
        "knowledge": {"name": "Knowledge"},
        "skills": {"name": "Skill", "content": "Read evidence", "enabled": True},
        "servers": {"name": "Server", "host": "192.0.2.1", "port": 22, "fingerprint": "", "status": "unknown"},
        "providers": {"name": "Provider", "models": ["local-test"]},
        "agents": {"name": "Agent", "provider_id": "providers", "skill_ids": ["skills"], "knowledge_ids": ["knowledge"]},
        "projects": {"name": "Project", "server_ids": ["servers"], "knowledge_ids": ["knowledge"]},
        "schedules": {
            "name": "Schedule", "provider_id": "providers", "server_id": "servers", "agent_id": "agents", "project_id": "projects",
            "cron": "0 9 * * *", "timezone": "UTC", "enabled": True, "next_run_at": "2030-01-02T09:00:00+00:00",
        },
    }
    with store.connect() as db:
        for owner in OWNERS:
            _insert_user(db, owner)
            for kind in (*defaults.KINDS, "conversations", "files", "alerts"):
                data = {"name": "PRIVATE-DO-NOT-DECODE", "body": "PRIVATE-DO-NOT-DECODE " * 600}
                if kind in {"conversations", "files"}:
                    data["default_template_id"] = "PRIVATE-NOT-A-TEMPLATE"
                db.execute("INSERT INTO entities VALUES (?,?,?,?,?,?)", (
                    f"private-{owner}-{kind}", owner, kind, store.dumps(data), STAMP, STAMP,
                ))
        _insert_user(db, "administrator", "admin")
        for kind, data in values.items():
            _insert_template(db, kind, kind, data)
        _insert_template(db, "other-knowledge", "knowledge", {"name": "Other knowledge"})
        _insert_template(db, "spare", "skills", {"name": "Spare skill"}, "2000-01-01T00:00:00+00:00")
        for id_ in ("knowledge", "other-knowledge"):
            db.execute("INSERT INTO template_documents VALUES (?,?,?,?,?)", (
                "document-" + id_, id_, id_ + ".md", (id_ + " searchabletoken evidence\n") * 100, STAMP,
            ))
    return values


def test_batch_prepares_templates_and_documents_once_without_loading_private_json(catalog, monkeypatch):
    original_loads, original_remap = store.loads, defaults.remap
    decoded, prepared_ids = Counter(), defaultdict(set)
    with store.connect() as db:
        sources = [row[0] for row in db.execute("SELECT data FROM default_templates")]

    def loads(value, default=None):
        assert "PRIVATE-DO-NOT-DECODE" not in (value or "")
        decoded[value] += 1
        return original_loads(value, default)

    def remap(data, mapping):
        prepared_ids[data["name"]].add(id(data))
        return original_remap(data, mapping)

    with monkeypatch.context() as patch:
        patch.setattr(store, "loads", loads)
        patch.setattr(defaults, "remap", remap)
        with _trace(patch, _deny_password) as sql:
            defaults.sync_all()
    assert len(_selects(sql, "default_templates")) == 1
    assert len(_selects(sql, "template_documents")) == 1
    assert len(_selects(sql, "users")) == 1
    assert len(_selects(sql, "entities")) == len(OWNERS)
    assert all("kind in (" in query and "json_extract(data,'$.default_template_id') is not null" in query
               for query in _selects(sql, "entities"))
    assert all(decoded[source] == 1 for source in sources)
    assert len(prepared_ids) == len(sources) and all(len(ids) == 1 for ids in prepared_ids.values())
    for owner in OWNERS:
        agent = store.get_entity(owner, "agents", _copy_id(owner, "agents"))
        assert agent is not None
        assert agent["provider_id"] == _copy_id(owner, "providers")
        assert agent["skill_ids"] == [_copy_id(owner, "skills")]
        assert agent["knowledge_ids"] == [_copy_id(owner, "knowledge")]
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM entities WHERE owner='administrator'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM default_sync_revisions").fetchone()[0] == len(OWNERS)


def test_unchanged_explicit_sync_skips_remap_deepcopy_reindex_and_all_writes(catalog, monkeypatch):
    defaults.sync_all()
    legacy_copy_id = _copy_id(OWNERS[0], "skills")
    with store.connect() as db:
        db.execute("UPDATE entities SET data=json_set(data,'$.read_only',json('true')) WHERE id=?", (legacy_copy_id,))
    before = _snapshot()

    def unexpected(*args, **kwargs):
        raise AssertionError("unchanged template must be skipped before remap/deepcopy")

    with monkeypatch.context() as patch:
        patch.setattr(defaults, "remap", unexpected)
        patch.setattr(defaults.copy, "deepcopy", unexpected)
        with _trace(patch, _deny_password) as sql:
            defaults.sync_all()
            defaults.sync_user(OWNERS[0])
    assert not _writes(sql)
    assert not _selects(sql, "template_documents")
    assert _snapshot() == before
    legacy_copy = store.get_entity(OWNERS[0], "skills", legacy_copy_id)
    assert legacy_copy is not None and legacy_copy["read_only"] is True
    assert main.public_entity("skills", legacy_copy)["read_only"] is False


def test_unchanged_startup_is_three_small_reads_without_write_lock(catalog, monkeypatch):
    defaults.sync_all()
    before = _snapshot()

    def authorizer(action, table, column, database, source):
        if action == sqlite3.SQLITE_READ and (table in {"entities", "documents", "chunks", "template_documents"}
                                             or (table, column) == ("default_templates", "data")):
            return sqlite3.SQLITE_DENY
        return _deny_password(action, table, column, database, source)

    with store.connect() as writer:
        writer.execute("BEGIN IMMEDIATE")
        with _trace(monkeypatch, authorizer) as sql:
            assert defaults.sync_all_if_needed() is False
            assert defaults.sync_all_if_needed() is False
    assert len([query for query in sql if query.startswith("select ")]) == 6
    assert len(_selects(sql, "default_templates")) == 2
    assert not any(query.startswith("begin") for query in sql)
    assert not _writes(sql)
    assert _snapshot() == before


@pytest.mark.parametrize("change", ["insert", "update_non_max", "delete", "replace_same_count_and_max"])
def test_startup_detects_direct_sql_template_changes_not_just_count_or_max(catalog, change):
    defaults.sync_all()
    with store.connect() as db:
        if change == "insert":
            _insert_template(db, "manual", "skills", {"name": "Manual template"}, "1999-01-01T00:00:00+00:00")
        elif change == "update_non_max":
            db.execute("UPDATE default_templates SET data=?,updated_at=? WHERE id='spare'", (
                store.dumps({"name": "Changed spare"}), "2001-01-01T00:00:00+00:00",
            ))
        else:
            db.execute("DELETE FROM default_templates WHERE id='spare'")
            if change == "replace_same_count_and_max":
                _insert_template(db, "replacement", "skills", {"name": "Replacement"}, "2000-01-01T00:00:00+00:00")
    assert defaults.sync_all_if_needed() is True
    assert defaults.sync_all_if_needed() is False
    for owner in OWNERS:
        if change == "update_non_max":
            value = store.get_entity(owner, "skills", _copy_id(owner, "spare"))
            assert value is not None and value["name"] == "Changed spare"
        elif change in {"delete", "replace_same_count_and_max"}:
            assert store.get_entity(owner, "skills", _copy_id(owner, "spare")) is None
        else:
            value = store.get_entity(owner, "skills", _copy_id(owner, "manual"))
            assert value is not None
            assert main.public_entity("skills", value)["read_only"] is False
        if change == "replace_same_count_and_max":
            value = store.get_entity(owner, "skills", _copy_id(owner, "replacement"))
            assert value is not None and value["name"] == "Replacement"


@pytest.mark.parametrize("change", ["new_user", "replace_user", "admin_to_user", "user_to_admin", "missing_stamp", "stale_stamp"])
def test_startup_detects_user_ids_roles_and_missing_or_stale_stamps(catalog, change):
    defaults.sync_all()
    owner = OWNERS[0]
    with store.connect() as db:
        if change in {"new_user", "replace_user"}:
            if change == "replace_user":
                db.execute("DELETE FROM users WHERE id=?", (owner,))
            owner = "new-user"
            _insert_user(db, owner)
        elif change == "admin_to_user":
            owner = "administrator"
            db.execute("UPDATE users SET data='{}' WHERE id=?", (owner,))
        elif change == "user_to_admin":
            db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps({"role": "admin"}), owner))
        elif change == "missing_stamp":
            db.execute("DELETE FROM default_sync_revisions WHERE owner=?", (owner,))
        else:
            db.execute("UPDATE default_sync_revisions SET sync_revision='stale' WHERE owner=?", (owner,))
    assert defaults.sync_all_if_needed() is True
    assert defaults.sync_all_if_needed() is False
    if change != "user_to_admin":
        value = store.get_entity(owner, "agents", _copy_id(owner, "agents"))
        assert value is not None
        assert main.public_entity("agents", value)["read_only"] is False


def test_startup_ignores_profile_and_password_changes_without_caching_auth(catalog, monkeypatch):
    defaults.sync_all()
    with store.connect() as db:
        db.execute("UPDATE users SET password='changed',data=? WHERE id=?", (
            store.dumps({"name": "Changed name", "role": "user", "disabled": True}), OWNERS[0],
        ))
    with _trace(monkeypatch, _deny_password) as sql:
        assert defaults.sync_all_if_needed() is False
    assert not _writes(sql)


def test_registration_always_installs_and_explicit_sync_repairs_missing_copies(catalog, monkeypatch):
    defaults.sync_all()
    with store.connect() as db:
        _insert_user(db, "registered")
    defaults.sync_user("registered")
    original = store.get_entity("registered", "skills", _copy_id("registered", "skills"))
    assert original is not None
    assert main.public_entity("skills", original)["read_only"] is False
    assert defaults.sync_all_if_needed() is True
    with store.connect() as db:
        db.execute("DELETE FROM entities WHERE id=?", (original["id"],))
    with _trace(monkeypatch) as sql:
        assert defaults.sync_all_if_needed() is False
    assert not _selects(sql, "entities")
    defaults.sync_user("registered")
    repaired = store.get_entity("registered", "skills", original["id"])
    assert repaired is not None and repaired["default_revision"] == original["default_revision"]


@pytest.mark.parametrize("table", ["entities", "documents", "default_sync_revisions", "platform_settings"])
def test_batch_failure_rolls_back_all_owners_and_signatures(catalog, table):
    before = _snapshot()
    condition = f"NEW.key='{defaults.SYNC_SIGNATURE_KEY}'" if table == "platform_settings" else "NEW.owner='b-owner'"
    with store.connect() as db:
        db.execute(f"""CREATE TRIGGER reject_sync BEFORE INSERT ON {table}
            WHEN {condition} BEGIN SELECT RAISE(ABORT,'forced sync failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced sync failure"):
        defaults.sync_all_if_needed()
    assert _snapshot() == before
    with store.connect() as db:
        db.execute("DROP TRIGGER reject_sync")
    assert defaults.sync_all_if_needed() is True
    assert defaults.sync_all_if_needed() is False


def test_template_save_failure_is_atomic_with_existing_copies_and_stamp(catalog):
    defaults.sync_all()
    before = _snapshot()
    with store.connect() as db:
        db.execute("""CREATE TRIGGER reject_update BEFORE INSERT ON entities
            WHEN NEW.owner='b-owner' BEGIN SELECT RAISE(ABORT,'forced sync failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced sync failure"):
        defaults.save("skills", {**catalog["skills"], "content": "Changed"}, "skills")
    assert _snapshot() == before
    assert defaults.sync_all_if_needed() is False


def test_only_changed_knowledge_reindexes_and_admin_document_updates_store_signature(catalog, monkeypatch):
    defaults.sync_all()
    with store.connect() as db:
        before = {source: [tuple(row) for row in db.execute("SELECT * FROM chunks WHERE knowledge_id=? ORDER BY rowid", (
            _copy_id(OWNERS[0], source),
        ))] for source in ("knowledge", "other-knowledge")}
        document_id = db.execute("SELECT id FROM documents WHERE knowledge_id=?", (_copy_id(OWNERS[0], "knowledge"),)).fetchone()[0]
    with _trace(monkeypatch) as sql:
        defaults.save("skills", {**catalog["skills"], "content": "Changed"}, "skills")
    assert not _selects(sql, "template_documents")
    assert not any(query.startswith("delete from chunks") for query in sql)
    assert defaults.sync_all_if_needed() is False
    admin_catalog.save_document("knowledge", "changed.md", "replacementtoken evidence", "document-knowledge")
    assert defaults.sync_all_if_needed() is False
    for owner in OWNERS:
        assert store.search_knowledge(owner, "replacementtoken", [_copy_id(owner, "knowledge")])
    with store.connect() as db:
        assert db.execute("SELECT id FROM documents WHERE knowledge_id=?", (_copy_id(OWNERS[0], "knowledge"),)).fetchone()[0] == document_id
        for source in before:
            after = [tuple(row) for row in db.execute("SELECT * FROM chunks WHERE knowledge_id=? ORDER BY rowid", (
                _copy_id(OWNERS[0], source),
            ))]
            assert (after == before[source]) is (source == "other-knowledge")
    admin_catalog.delete_documents("knowledge", ["document-knowledge"])
    assert defaults.sync_all_if_needed() is False
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM documents WHERE knowledge_id=?", (_copy_id(OWNERS[0], "knowledge"),)).fetchone()[0] == 0


def test_server_tofu_and_schedule_runtime_state_survive_only_compatible_updates(catalog):
    defaults.sync_all()
    owner = OWNERS[0]
    server = store.get_entity(owner, "servers", _copy_id(owner, "servers"))
    assert server is not None
    server.update(fingerprint="SHA256:pinned", fingerprint_trusted_at="trusted", status="online", last_checked_at="checked")
    store.save_entity(owner, "servers", server, server["id"])
    schedule = store.get_entity(owner, "schedules", _copy_id(owner, "schedules"))
    assert schedule is not None
    schedule.update(last_run_at="ran", last_run_id="run-id", next_run_at="2035-01-01T09:00:00+00:00")
    store.save_entity(owner, "schedules", schedule, schedule["id"])
    defaults.save("servers", {**catalog["servers"], "description": "Changed"}, "servers")
    defaults.save("schedules", {**catalog["schedules"], "description": "Changed"}, "schedules")
    updated = store.get_entity(owner, "servers", server["id"])
    assert updated is not None
    for key in ("fingerprint", "fingerprint_trusted_at", "status", "last_checked_at"):
        assert updated[key] == server[key]
    updated = store.get_entity(owner, "schedules", schedule["id"])
    assert updated is not None
    for key in ("last_run_at", "last_run_id", "next_run_at"):
        assert updated[key] == schedule[key]
    defaults.save("servers", {**catalog["servers"], "host": "192.0.2.2"}, "servers")
    updated = store.get_entity(owner, "servers", server["id"])
    assert updated is not None
    assert updated["fingerprint"] == "" and "fingerprint_trusted_at" not in updated and updated["status"] == "unknown"
    defaults.save("schedules", {**catalog["schedules"], "cron": "0 10 * * *"}, "schedules")
    updated = store.get_entity(owner, "schedules", schedule["id"])
    assert updated is not None
    assert updated["next_run_at"] == catalog["schedules"]["next_run_at"]
    assert updated["last_run_at"] == "ran" and updated["last_run_id"] == "run-id"


def test_deletion_preserves_private_resources_and_cleans_only_real_references(catalog, monkeypatch):
    defaults.sync_all()
    owner = OWNERS[0]
    refs = {field: _copy_id(owner, kind) for field, kind in defaults.SINGLE_REFS.items()}
    linked = []
    for kind, data in (
        ("conversations", refs), ("alerts", {"server_id": refs["server_id"]}),
        ("projects", {"server_ids": [refs["server_id"]], "knowledge_ids": [_copy_id(owner, "knowledge")]}),
        ("agents", {"skill_ids": [_copy_id(owner, "skills")]}),
        ("schedules", {**refs, "cron": "0 9 * * *", "enabled": True}),
    ):
        linked.append((kind, store.save_entity(owner, kind, {"name": "Private linked", **data})["id"]))
    with store.connect() as db:
        untouched = [tuple(row) for row in db.execute("SELECT * FROM entities WHERE id LIKE 'private-%' ORDER BY id")]
        private_kb = "private-" + owner + "-knowledge"
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", ("private-document", owner, private_kb, "private.md", 7, 1, STAMP))
        db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", ("private-chunk", owner, private_kb, "private-document", "private.md", "private"))
        for kind in defaults.KINDS:
            defaults.delete_many(kind, [kind], db)
        sql = []
        db.set_trace_callback(lambda query: sql.append(" ".join(query.lower().split())))
        defaults.sync_all(db)
    assert defaults.sync_all_if_needed() is False
    entity_reads = _selects(sql, "entities")
    assert len(entity_reads) == len(OWNERS) * 2
    assert all("kind in (" in query or "json_extract(data," in query for query in entity_reads)
    for kind, id_ in linked:
        value = store.get_entity(owner, kind, id_)
        assert value is not None
        assert value["name"] == "Private linked"
        assert all(not value.get(field) for field in defaults.SINGLE_REFS)
        assert all(not value.get(field) for field in defaults.MULTI_REFS)
        if kind == "schedules":
            assert value["enabled"] is False
    with store.connect() as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM entities WHERE id LIKE 'private-%' ORDER BY id")] == untouched
        assert db.execute("SELECT content FROM chunks WHERE id='private-chunk'").fetchone()[0] == "private"
        assert db.execute("SELECT count(*) FROM documents WHERE id='private-document'").fetchone()[0] == 1
    assert not _selects(sql, "template_documents")
