from __future__ import annotations

import asyncio
import importlib
import re
import sqlite3
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import admin_catalog, defaults, engine, main, presets, store, tools

MARKER = "catalog_expansion_20261029_v1"
CATALOG_TABLES = (
    "users", "default_templates", "template_documents", "platform_settings", "entities", "documents", "chunks",
    "default_owner_states", "default_sync_revisions",
)
READ_ONLY_COMMAND = re.compile(
    r"kubectl(?:\s+(?:--context|--namespace|-n)(?:=|\s+)\S+)*\s+"
    r"(?:get|describe|logs|top|auth\s+can-i|version|explain|api-resources|cluster-info)\b"
    r"|\b(?:journalctl|vmstat|iostat|free|df|du|ss|lsblk|lscpu|uptime|ps|findmnt|dig|nslookup|curl|openssl|ip|stat)\b"
    r"|systemctl\s+(?:status|show|is-active|list-units)\b"
    r"|(?m:^(?:"
    r'etcdctl --endpoints="\$ENDPOINT" --dial-timeout=3s --command-timeout=5s '
    r"(?:endpoint status --write-out=table|alarm list)"
    r'|mysql --login-path="\$READONLY_PROFILE" --connect-timeout=5 --ssl-mode=VERIFY_IDENTITY -e "'
    r"(?:SELECT @@version,@@server_uuid,@@read_only;"
    r"|SELECT REQUESTING_ENGINE_TRANSACTION_ID,BLOCKING_ENGINE_TRANSACTION_ID "
    r'FROM performance_schema\.data_lock_waits LIMIT 20;)"'
    r'|psql "service=\$PGSERVICE" -X -v ON_ERROR_STOP=1 -c "'
    r"(?:SELECT pg_is_in_recovery\(\),current_setting\('server_version'\);"
    r"|SELECT pid,state,wait_event_type,wait_event,pg_blocking_pids\(pid\) "
    r'FROM pg_stat_activity WHERE datname=current_database\(\) LIMIT 20;)"'
    r'|redis-cli --tls -h "\$HOST" -p "\$PORT" INFO (?:memory|replication)'
    r'|mongosh --host "\$MONGO_HOST" --tls --quiet --eval '
    r"(?:'JSON\.stringify\(db\.adminCommand\(\{hello:1\}\)\)'"
    r"|'JSON\.stringify\(rs\.status\(\)\.members\.map\(m=>\(\{name:m\.name,stateStr:m\.stateStr,"
    r"health:m\.health,optimeDate:m\.optimeDate\}\)\)\)')"
    r'|kafka-consumer-groups\.sh --bootstrap-server "\$BROKERS" --command-config "\$READONLY_CONFIG" '
    r'--describe --group "\$GROUP" --timeout 10000'
    r'|kafka-topics\.sh --bootstrap-server "\$BROKERS" --command-config "\$READONLY_CONFIG" --describe --topic "\$TOPIC"'
    r'|rabbitmqctl -p "\$VHOST" list_queues name type messages_ready messages_unacknowledged consumers --timeout 10'
    r"|rabbitmq-diagnostics -q alarms"
    r'|grep -E "Max open files\|Max processes" "/proc/\$PID/limits"'
    r'|grep -E "\^\(Name\|Pid\|Threads\):" "/proc/\$PID/status"'
    r"|sysctl fs\.file-nr fs\.file-max"
    r"|chronyc -n (?:tracking|sources)"
    r"|timedatectl show -p NTPSynchronized -p Timezone"
    r")$)"
)


@pytest.fixture
def expansion_store(monkeypatch, tmp_path):
    data = tmp_path / "catalog-expansion"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    store.close_connections()
    store._cipher.cache_clear()
    monkeypatch.setattr(store, "DATA_ROOT", data)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "earthai.db")
    monkeypatch.setattr(store, "_CONNECTIONS", {})
    monkeypatch.setattr(store, "_CONNECTION_LOCAL", threading.local())
    monkeypatch.setenv("EARTHAI_DATA_DIR", str(data))
    monkeypatch.setenv("EARTHAI_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("EARTHAI_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", "DELETE")
    monkeypatch.setenv("EARTHAI_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("EARTHAI_COOKIE_SECURE", "false")
    monkeypatch.delenv("EARTHAI_STATE_DIR", raising=False)
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})

    async def idle_scheduler():
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "scheduler_loop", idle_scheduler)
    blocked = (
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected paid model request"))),
        (engine, "provider_models", AsyncMock(side_effect=AssertionError("unexpected provider request"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure execution"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected server connection"))),
        (tools, "ssh_connect", Mock(side_effect=AssertionError("unexpected SSH connection"))),
        (httpx.HTTPTransport, "handle_request", Mock(side_effect=AssertionError("unexpected network request"))),
        (httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(side_effect=AssertionError("unexpected network request"))),
    )
    for target, name, replacement in blocked:
        monkeypatch.setattr(target, name, replacement)
    yield data
    store.close_connections()
    store._cipher.cache_clear()
    for _, name, replacement in blocked:
        assert replacement.call_count == 0, name


@pytest.fixture
def original_catalog(expansion_store):
    store.init_db()
    defaults.initialize()
    admin_catalog.install()
    assert len(presets.PRESETS) == 50
    assert len(defaults.list_templates("knowledge")) == len(defaults.list_templates("skills")) == 50
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM template_documents").fetchone()[0] == 100
    return _snapshot()


def _expansion():
    return importlib.import_module("backend.catalog_expansion")


def _snapshot(tables=CATALOG_TABLES):
    with store.connect() as db:
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in tables}


def _rows(table, clause="", parameters=()):
    with store.connect() as db:
        return [dict(row) for row in db.execute(f"SELECT * FROM {table} {clause} ORDER BY rowid", parameters)]


def _marker():
    return _rows("platform_settings", "WHERE key=?", (MARKER,))


def _sources(kind):
    return {item["id"]: item for item in defaults.list_templates(kind)}


def _data(value):
    return {key: item for key, item in value.items() if key not in {"id", "created_at", "updated_at"}}


def _user(name):
    owner = store.uid()
    with store.connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (
            owner, f"{name}@catalog.example.test", "unused-offline-test-hash",
            store.dumps({"name": name, "role": "user", "control_level": "observe"}), store.now(),
        ))
    defaults.sync_user(owner)
    return owner


def _copies(owner, kind):
    return {item["default_template_id"]: item for item in store.list_entities(owner, kind) if item.get("default_template_id")}


def _documents(owner, knowledge_id):
    result = {}
    with store.connect() as db:
        for row in db.execute("SELECT * FROM documents WHERE owner=? AND knowledge_id=? ORDER BY id", (owner, knowledge_id)):
            chunks = [chunk["content"] for chunk in db.execute(
                "SELECT content FROM chunks WHERE owner=? AND document_id=? ORDER BY rowid", (owner, row["id"]),
            )]
            text = "".join([chunks[0], *(chunk[250:] for chunk in chunks[1:])]) if chunks else ""
            result[row["id"]] = {key: row[key] for key in ("id", "name", "size", "chunk_count")}
            result[row["id"]]["text"] = text
    return result


def _assert_original_rows(before):
    old_templates = {row[0]: row for row in before["default_templates"]}
    current_templates = {row["id"]: row for row in _rows("default_templates")}
    for id_, previous in old_templates.items():
        current = current_templates[id_]
        if previous[1] == "knowledge":
            assert tuple(current.values())[:-1] == previous[:-1]
        else:
            assert tuple(current.values()) == previous
    current_documents = {row["id"]: tuple(row.values()) for row in _rows("template_documents")}
    for previous in before["template_documents"]:
        assert current_documents[previous[0]] == previous


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def test_append_inventory_preserves_all_original_templates_and_documents(original_catalog):
    before = original_catalog
    _expansion().install()
    _assert_original_rows(before)
    assert len(_marker()) == 1
    assert len(defaults.list_templates("knowledge")) == len(defaults.list_templates("agents")) == 50
    skills = defaults.list_templates("skills")
    assert len(skills) == 100
    old_ids = {row[0] for row in before["default_templates"]}
    new_skills = [item for item in skills if item["id"] not in old_ids]
    domains = {preset["key"] for preset in presets.PRESETS}
    assert len(new_skills) == len({item["builtin_key"] for item in new_skills}) == 50
    assert {item["builtin_domain"] for item in new_skills} == domains
    assert not ({item["builtin_key"] for item in new_skills} & {row[3] for row in before["default_templates"]})
    assert len({item["name"] for item in new_skills}) == len({item["content"] for item in new_skills}) == 50
    for item in new_skills:
        content = item["content"]
        assert len(content) >= 350, item["builtin_domain"]
        assert item.get("enabled", True) is True
        assert "只读" in content and "验证" in content
        assert READ_ONLY_COMMAND.search(content), item["builtin_domain"]
        assert re.search(r"(?:^|\n)\s*(?:1[.、)]|#{1,3}\s)", content), item["builtin_domain"]
    old_documents = {row[0] for row in before["template_documents"]}
    new_documents = [row for row in _rows("template_documents") if row["id"] not in old_documents]
    assert len({row["content"] for row in new_documents}) == len(new_documents)
    by_source = defaultdict(list)
    for row in new_documents:
        by_source[row["template_id"]].append(row)
        assert len(row["content"]) >= 700
        assert "验证" in row["content"] and "只读" in row["content"]
        assert READ_ONLY_COMMAND.search(row["content"]), row["name"]
    assert set(by_source) == set(_sources("knowledge"))
    assert all(1 <= len(values) <= 10 for values in by_source.values())
    assert list(store.UPLOADS.iterdir()) == []


def test_repeated_install_is_exact_noop_and_admin_deletions_are_not_recreated(original_catalog):
    expansion = _expansion()
    original_ids = {row[0] for row in original_catalog["default_templates"]}
    original_doc_ids = {row[0] for row in original_catalog["template_documents"]}
    expansion.install()
    after_install = _snapshot()
    installed_marker = _marker()
    expansion.install()
    expansion.install()
    assert _snapshot() == after_install
    new_skill = next(item for item in defaults.list_templates("skills") if item["id"] not in original_ids)
    new_document = next(row for row in _rows("template_documents") if row["id"] not in original_doc_ids)
    admin_catalog.delete_documents(new_document["template_id"], [new_document["id"]])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        defaults.delete_many("skills", [new_skill["id"]], db)
        defaults.sync_all(db)
    deleted = _snapshot()
    store.close_connections()
    expansion.install()
    assert _snapshot() == deleted
    with TestClient(main.app):
        assert not _rows("template_documents", "WHERE id=?", (new_document["id"],))
        assert defaults.get_template("skills", new_skill["id"]) is None
        assert _marker() == installed_marker
        assert len(defaults.list_templates("skills")) == 99
        assert _snapshot(("default_templates", "template_documents")) == {
            table: deleted[table] for table in ("default_templates", "template_documents")
        }


def test_preexisting_admin_edits_and_deleted_preset_library_are_respected(original_catalog):
    knowledge = list(_sources("knowledge").values())
    deleted, edited = knowledge[:2]
    skill = next(iter(_sources("skills").values()))
    defaults.save("skills", {**_data(skill), "name": "管理员保留的技能", "content": "人工编写的技能正文", "enabled": False}, skill["id"])
    defaults.save("knowledge", {**_data(edited), "description": "管理员维护的知识说明"}, edited["id"])
    document = _rows("template_documents", "WHERE template_id=?", (edited["id"],))[0]
    admin_catalog.save_document(edited["id"], "admin-edited.md", "管理员自有正文，不应被扩充重写。", document["id"])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        defaults.delete_many("knowledge", [deleted["id"]], db)
        defaults.sync_all(db)
    custom = defaults.save("skills", {"name": "自定义管理技能", "content": "人工内容", "enabled": False})
    before = _snapshot()
    _expansion().install()
    _assert_original_rows(before)
    assert defaults.get_template("knowledge", deleted["id"]) is None
    assert len(defaults.list_templates("knowledge")) == 49
    assert len(defaults.list_templates("skills")) == 101
    assert defaults.get_template("skills", custom["id"]) == custom
    assert not _rows("template_documents", "WHERE template_id=?", (deleted["id"],))
    edited_after = defaults.get_template("knowledge", edited["id"])
    assert edited_after is not None and edited_after["description"] == "管理员维护的知识说明"
    assert next(row for row in _rows("template_documents") if row["id"] == document["id"])["content"] == "管理员自有正文，不应被扩充重写。"


def test_expansion_sync_preserves_overrides_tombstones_managed_document_ids_and_new_users(original_catalog):
    owner = _user("existing")
    knowledge = list(_copies(owner, "knowledge").values())
    _, overridden, removed = knowledge[:3]
    skills = list(_copies(owner, "skills").values())
    custom_skill, removed_skill = skills[:2]
    defaults.save_personal(owner, "skills", custom_skill["id"], {
        **_data(custom_skill), "content": "我的个人技能正文，扩充不得覆盖。", "enabled": False,
    })
    defaults.save_personal(owner, "knowledge", overridden["id"], {**_data(overridden), "description": "我的个人文档库"})
    private_document = store.uid()
    with store.connect() as db:
        text = "personalexpansiontoken 仅当前用户保留的补充知识。"
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", (
            private_document, owner, overridden["id"], "personal.md", len(text.encode()), 1, store.now(),
        ))
        db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", (
            store.uid(), owner, overridden["id"], private_document, "personal.md", text,
        ))
    defaults.delete_personal(owner, "knowledge", removed["id"])
    defaults.delete_personal(owner, "skills", removed_skill["id"])
    managed_before = {
        item["id"]: _documents(owner, item["id"])
        for item in _copies(owner, "knowledge").values() if item["id"] != overridden["id"]
    }
    override_rows = {
        "entities": _rows("entities", "WHERE id IN (?,?)", (overridden["id"], custom_skill["id"])),
        "documents": _rows("documents", "WHERE knowledge_id=?", (overridden["id"],)),
        "chunks": _rows("chunks", "WHERE knowledge_id=?", (overridden["id"],)),
    }
    states_before = _rows("default_owner_states", "WHERE owner=?", (owner,))
    expansion = _expansion()
    expansion.install()
    defaults.sync_all()
    _assert_original_rows(original_catalog)
    for knowledge_id, previous_documents in managed_before.items():
        after = _documents(owner, knowledge_id)
        assert previous_documents.keys() < after.keys()
        assert all(after[id_] == value for id_, value in previous_documents.items())
    for table, previous in override_rows.items():
        clause, parameters = ("WHERE id IN (?,?)", (overridden["id"], custom_skill["id"])) if table == "entities" else (
            "WHERE knowledge_id=?", (overridden["id"],),
        )
        assert _rows(table, clause, parameters) == previous
    assert _rows("default_owner_states", "WHERE owner=?", (owner,)) == states_before
    assert store.get_entity(owner, "knowledge", removed["id"]) is None
    assert store.get_entity(owner, "skills", removed_skill["id"]) is None
    assert len(_copies(owner, "knowledge")) == 49
    assert len(_copies(owner, "skills")) == 99
    assert store.search_knowledge(owner, "personalexpansiontoken", [overridden["id"]])
    fresh = _user("new-after-expansion")
    assert len(_copies(fresh, "skills")) == 100
    assert len(_copies(fresh, "knowledge")) == len(_copies(fresh, "agents")) == 50
    old_doc_ids = {row[0] for row in original_catalog["template_documents"]}
    documents = _rows("template_documents")
    fresh_knowledge = _copies(fresh, "knowledge")
    for source_id, copy in fresh_knowledge.items():
        expected = [row for row in documents if row["template_id"] == source_id]
        inherited = _documents(fresh, copy["id"])
        assert len(inherited) == len(expected)
        assert {(row["name"], row["content"]) for row in expected} == {(row["name"], row["text"]) for row in inherited.values()}
        added = next(row for row in expected if row["id"] not in old_doc_ids)
        found = store.search_knowledge(fresh, added["name"].removesuffix(".md"), [copy["id"]], limit=100)
        assert any(row["document_name"] == added["name"] for row in found)
    frozen = _snapshot()
    installed_marker = _marker()
    with TestClient(main.app):
        expansion.install()
        defaults.sync_user(owner)
        defaults.sync_all()
        assert _snapshot(("entities", "documents", "chunks", "default_owner_states")) == {
            table: frozen[table] for table in ("entities", "documents", "chunks", "default_owner_states")
        }
        assert _marker() == installed_marker


@pytest.mark.parametrize("failure", ("document", "skill", "marker"))
def test_install_failure_rolls_back_all_changes_and_marker_can_retry(original_catalog, failure):
    table, condition = {
        "document": ("template_documents", "1"),
        "skill": ("default_templates", "NEW.kind='skills'"),
        "marker": ("platform_settings", f"NEW.key='{MARKER}'"),
    }[failure]
    with store.connect() as db:
        db.execute(f"CREATE TRIGGER reject_expansion BEFORE INSERT ON {table} WHEN {condition} "
                   "BEGIN SELECT RAISE(ABORT,'injected expansion failure'); END")
    before = _snapshot()
    with pytest.raises(sqlite3.IntegrityError, match="injected expansion failure"):
        _expansion().install()
    assert _snapshot() == before
    assert not _marker()
    with store.connect() as db:
        db.execute("DROP TRIGGER reject_expansion")
    _expansion().install()
    assert len(_marker()) == 1
    assert len(defaults.list_templates("skills")) == 100
    _assert_original_rows(original_catalog)


def test_install_uses_explicit_transaction_and_writes_marker_last(original_catalog, monkeypatch):
    statements = []
    original_connect = store.connect

    @contextmanager
    def traced_connect():
        with original_connect() as db:
            db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr(store, "connect", traced_connect)
    _expansion().install()
    assert any(re.match(r"\s*BEGIN\s+(?:IMMEDIATE|EXCLUSIVE)\b", statement, re.I) for statement in statements)
    writes = [statement for statement in statements if re.match(r"\s*(?:INSERT|UPDATE|DELETE|REPLACE)\b", statement, re.I)]
    assert writes and MARKER in writes[-1] and "platform_settings" in writes[-1]
    assert any(statement.strip().upper() == "COMMIT" for statement in statements)


def test_fresh_lifespan_expands_before_engine_recovery_and_registration_inherits_it(expansion_store, monkeypatch):
    def check_catalog_before_recovery():
        assert len(_marker()) == 1
        assert len(defaults.list_templates("skills")) == 100
        assert len(defaults.list_templates("knowledge")) == 50

    recover = Mock(side_effect=check_catalog_before_recovery)
    monkeypatch.setattr(engine, "recover_interrupted", recover)
    with TestClient(main.app) as client:
        recover.assert_called_once()
        _ok(client.get("/api/health"))
        user = _ok(client.post("/api/auth/register", json={
            "email": "registered-after-expansion@example.test", "password": "Offline-Catalog-2026!", "name": "目录继承用户",
        }))
        assert len(_ok(client.get("/api/skills"))) == 100
        assert len(_ok(client.get("/api/agents"))) == 50
        knowledge = _ok(client.get("/api/knowledge"))
        assert len(knowledge) == 50
        assert all(3 <= item["document_count"] <= 12 for item in knowledge)
        assert all(item["default_template_id"] and not item["read_only"] for item in knowledge)
        assert sum(item["document_count"] for item in knowledge) == len(_rows("documents", "WHERE owner=?", (user["id"],)))
        assert list(store.UPLOADS.iterdir()) == []


def test_personal_deletions_of_new_skill_and_document_survive_restart_without_catalog_reroll(original_catalog):
    expansion = _expansion()
    expansion.install()
    owner = _user("personal-delete-after-expansion")
    old_template_ids = {row[0] for row in original_catalog["default_templates"]}
    old_document_ids = {row[0] for row in original_catalog["template_documents"]}
    source_skill = next(item for item in defaults.list_templates("skills") if item["id"] not in old_template_ids)
    source_document = next(row for row in _rows("template_documents") if row["id"] not in old_document_ids)
    personal_skill = _copies(owner, "skills")[source_skill["id"]]
    personal_knowledge = _copies(owner, "knowledge")[source_document["template_id"]]
    personal_document = next(row for row in _documents(owner, personal_knowledge["id"]).values() if row["name"] == source_document["name"])
    installed_marker = _marker()
    catalog = _snapshot(("default_templates", "template_documents"))
    with TestClient(main.app) as client:
        client.cookies.set("earthai_session", store.new_session(owner))
        _ok(client.delete(f"/api/skills/{personal_skill['id']}"))
        _ok(client.delete(f"/api/knowledge/{personal_knowledge['id']}/documents/{personal_document['id']}"))
        assert store.get_entity(owner, "skills", personal_skill["id"]) is None
        assert personal_document["id"] not in _documents(owner, personal_knowledge["id"])
        states = {row["template_id"]: row["state"] for row in _rows("default_owner_states", "WHERE owner=?", (owner,))}
        assert states[source_skill["id"]] == "deleted"
        assert states[source_document["template_id"]] == "override"
        assert _snapshot(("default_templates", "template_documents")) == catalog
        frozen = _snapshot(("entities", "documents", "chunks", "default_owner_states"))
    with TestClient(main.app) as restarted:
        restarted.cookies.set("earthai_session", store.new_session(owner))
        expansion.install()
        defaults.sync_user(owner)
        defaults.sync_all()
        assert _snapshot(("entities", "documents", "chunks", "default_owner_states")) == frozen
        assert _snapshot(("default_templates", "template_documents")) == catalog
        assert _marker() == installed_marker
        assert restarted.get(f"/api/knowledge/{personal_knowledge['id']}/documents/{personal_document['id']}").status_code == 404
        assert source_skill["id"] not in _copies(owner, "skills")
        another_owner = _user("unaffected-by-other-user-delete")
        assert source_skill["id"] in _copies(another_owner, "skills")
        another_knowledge = _copies(another_owner, "knowledge")[source_document["template_id"]]
        assert any(row["name"] == source_document["name"] for row in _documents(another_owner, another_knowledge["id"]).values())


@pytest.mark.parametrize("endpoint", (1, 10))
def test_random_count_endpoints_persist_manifest_and_never_draw_again(original_catalog, monkeypatch, endpoint):
    expansion = _expansion()
    counts, samples = [], []

    class EndpointRandom:
        def randint(self, start, stop):
            assert (start, stop) == (1, 10)
            counts.append(endpoint)
            return endpoint

        def sample(self, population, count):
            assert count == endpoint and len(population) == 10
            samples.append(tuple(item["key"] for item in population))
            return population[-count:]

    monkeypatch.setattr(expansion.secrets, "SystemRandom", EndpointRandom)
    manifest = expansion.install()
    marker = _marker()
    assert len(counts) == len(samples) == 50
    assert manifest == store.loads(marker[0]["value"])
    assert manifest["documents_added"] == endpoint * 50
    assert manifest["skills_added"] == len(manifest["skill_keys"]) == 50
    assert manifest["existing_skill_keys"] == []
    assert set(manifest["knowledge"]) == set(_sources("knowledge"))
    old_document_ids = {row[0] for row in original_catalog["template_documents"]}
    for source_id, selection in manifest["knowledge"].items():
        assert selection["documents_added"] == len(selection["documents"]) == endpoint
        expected = expansion.document_pool(selection["domain"])[-endpoint:]
        actual = _rows("template_documents", "WHERE template_id=?", (source_id,))
        assert len(actual) == endpoint + 2
        added = {row["id"]: row for row in actual if row["id"] not in old_document_ids}
        assert set(added) == {item["id"] for item in selection["documents"]}
        assert {(row["name"], row["content"]) for row in added.values()} == {
            (row["name"], row["content"]) for row in expected
        }
        for item in selection["documents"]:
            assert added[item["id"]]["name"] == item["name"]
    _assert_original_rows(original_catalog)
    frozen = _snapshot(("default_templates", "template_documents"))
    no_random = Mock(side_effect=AssertionError("catalog migration must never reroll"))
    monkeypatch.setattr(expansion.secrets, "SystemRandom", no_random)
    assert expansion.install() == manifest
    store.close_connections()
    with TestClient(main.app):
        assert expansion.install() == manifest
        assert _snapshot(("default_templates", "template_documents")) == frozen
        assert _marker() == marker
    no_random.assert_not_called()


def test_concurrent_install_chooses_one_persistent_catalog_only(original_catalog):
    expansion = _expansion()
    ready = Barrier(4)

    def install_once(_):
        ready.wait(timeout=10)
        return expansion.install()

    with ThreadPoolExecutor(max_workers=4) as executor:
        manifests = list(executor.map(install_once, range(4)))
    marker = _marker()
    assert len(marker) == 1
    assert all(manifest == store.loads(marker[0]["value"]) for manifest in manifests)
    assert len(defaults.list_templates("skills")) == 100
    assert len(_rows("template_documents")) == 100 + manifests[0]["documents_added"]
    _assert_original_rows(original_catalog)


@pytest.mark.parametrize("domain", [preset["key"] for preset in presets.PRESETS])
def test_all_ten_candidate_topics_per_domain_have_distinct_substantive_read_only_guidance(domain):
    pool = _expansion().document_pool(domain)
    assert len(pool) == len({item["key"] for item in pool}) == 10
    assert len({item["name"] for item in pool}) == len({item["content"] for item in pool}) == 10
    assert all(item["key"].startswith(domain + ".") for item in pool)
    for document in pool:
        content = document["content"]
        assert len(content) >= 700, document["name"]
        assert "只读" in content and any(term in content for term in ("验证", "复核")), document["name"]
        assert READ_ONLY_COMMAND.search(content), document["name"]
        assert all(term in content for term in ("1.", "2.", "3.", "证据", "风险")), document["name"]
