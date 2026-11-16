import asyncio
import base64
from collections import defaultdict, deque
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import access, admin_catalog, defaults, engine, main, presets, progress, store, tools


PASSWORD = "S3cure-test-password!"
ADMIN_PASSWORD = "Changed-admin-password!"
TABLES = (
    "users", "sessions", "entities", "messages", "runs", "events", "approvals",
    "documents", "chunks", "audit", "agent_orders", "default_templates", "template_documents", "platform_settings", "help_guides",
    "default_owner_states", "remote_agent_clicks",
)


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    data = tmp_path / "data"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "admin-platform.db")
    monkeypatch.setenv("EARTHAI_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EARTHAI_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("EARTHAI_COOKIE_SECURE", "false")
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})
    blocked = [
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected model request"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure execution"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected server connection"))),
    ]
    for module, name, replacement in blocked:
        monkeypatch.setattr(module, name, replacement)
    yield data
    for _, name, replacement in blocked:
        assert replacement.call_count == 0, name


@pytest.fixture
def client(isolated_store):
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def administrator(client):
    _login(client, "admin", "admin")
    _ok(client.post("/api/auth/password", json={"current_password": "admin", "new_password": ADMIN_PASSWORD}))
    return client


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _register(client, email="owner@example.com", **extra):
    return _ok(client.post("/api/auth/register", json={"email": email, "password": PASSWORD, "name": "测试用户", **extra}))


def _login(client, email, password=PASSWORD):
    client.cookies.clear()
    return _ok(client.post("/api/auth/login", json={"email": email, "password": password}))


def _session(client, token):
    client.cookies.clear()
    client.cookies.set("earthai_session", token)


def _body(kind, name, **changes):
    bodies = {
        "knowledge": {"name": name, "description": "测试知识库"},
        "skills": {"name": name, "content": "先收集只读证据，经过审批后才能变更。"},
        "servers": {"name": name, "host": "192.0.2.10", "password": "test-only-ssh-password"},
        "providers": {
            "name": name, "base_url": "https://models.example.invalid/v1", "api_key": "test-only-api-key",
            "models": ["test-model"], "default_model": "test-model",
        },
        "agents": {"name": name, "system_prompt": "只读检查并报告证据", "control_level": "observe"},
        "projects": {"name": name, "description": "测试项目"},
        "schedules": {"name": name, "prompt": "只读巡检", "enabled": False, "cron": "0 9 * * *", "timezone": "UTC"},
    }
    return {**bodies[kind], **changes}


def _default(client, kind, name, **changes):
    return _ok(client.post(f"/api/admin/defaults/{kind}", json=_body(kind, name, **changes)))


def _copies(client, kind):
    return {
        value["default_template_id"]: value
        for value in _ok(client.get(f"/api/{kind}"))
        if value.get("default_template_id")
    }


def _snapshot():
    with store.connect() as db:
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in TABLES}


def _owner_snapshot(owner):
    with store.connect() as db:
        result = {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} WHERE owner=? ORDER BY rowid", (owner,))]
            for table in (
                "entities", "messages", "runs", "approvals", "documents", "chunks", "audit", "agent_orders",
                "default_owner_states", "remote_agent_clicks",
            )
        }
        result["users"] = [tuple(row) for row in db.execute("SELECT * FROM users WHERE id=?", (owner,))]
        result["sessions"] = [tuple(row) for row in db.execute("SELECT * FROM sessions WHERE user_id=? ORDER BY rowid", (owner,))]
        result["events"] = [tuple(row) for row in db.execute(
            "SELECT * FROM events WHERE run_id IN (SELECT id FROM runs WHERE owner=?) ORDER BY id", (owner,),
        )]
    return result


def _run(owner, conversation, status="running", **data):
    id_, stamp = store.uid(), store.now()
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (
            id_, owner, conversation["id"], status, store.dumps({"goal": "不执行真实任务", **data}), stamp, stamp,
        ))
    return id_


def _linked_catalog(client):
    values = {kind: _default(client, kind, "关联测试-" + kind) for kind in defaults.KINDS}
    references = {
        "agents": {
            "provider_id": values["providers"]["id"], "skill_ids": [values["skills"]["id"]],
            "knowledge_ids": [values["knowledge"]["id"]],
        },
        "projects": {"server_ids": [values["servers"]["id"]], "knowledge_ids": [values["knowledge"]["id"]]},
        "schedules": {
            "server_id": values["servers"]["id"], "provider_id": values["providers"]["id"], "agent_id": values["agents"]["id"],
        },
    }
    for kind, fields in references.items():
        value = defaults.get_template(kind, values[kind]["id"])
        data = {key: value for key, value in value.items() if key not in {"id", "created_at", "updated_at"}}
        values[kind] = defaults.save(kind, {**data, **fields}, value["id"])
    return values


def test_bootstrap_admin_hash_forced_password_change_and_restart(isolated_store):
    with TestClient(main.app) as client:
        assert client.get("/api/admin/overview").status_code == 401
        with store.connect() as db:
            original = dict(db.execute("SELECT * FROM users WHERE email='admin'").fetchone())
        assert original["password"] != "admin"
        assert store.password_matches("admin", original["password"])
        assert store.loads(original["data"])["must_change_password"] is True
        user = _login(client, "admin", "admin")
        stale_token = client.cookies.get("earthai_session")
        assert user["role"] == "admin" and user["must_change_password"] is True
        assert "password" not in user
        assert _ok(client.get("/api/auth/me"))["must_change_password"] is True
        for path in ("/api/admin/overview", "/api/admin/users", "/api/admin/defaults/agents", "/api/conversations"):
            assert client.get(path).status_code == 403
        assert client.get("/api/admin/overview?must_change_password=false").status_code == 403
        unchanged = _ok(client.patch("/api/auth/me", json={"must_change_password": False, "role": "user"}))
        assert unchanged["must_change_password"] is True and unchanged["role"] == "admin"
        assert client.get("/api/admin/overview").status_code == 403
        for body, status in (
            ({"current_password": "wrong", "new_password": ADMIN_PASSWORD}, 403),
            ({"current_password": "admin", "new_password": "short"}, 422),
            ({"current_password": "admin", "new_password": ADMIN_PASSWORD, "must_change_password": False}, 422),
        ):
            assert client.post("/api/auth/password", json=body).status_code == status
        assert _ok(client.post("/api/auth/logout")) == {"ok": True}
        assert store.user_for_token(stale_token) is None
        _login(client, "admin", "admin")
        stale_token = client.cookies.get("earthai_session")
        changed = _ok(client.post("/api/auth/password", json={"current_password": "admin", "new_password": ADMIN_PASSWORD}))
        fresh_token = client.cookies.get("earthai_session")
        assert fresh_token != stale_token and changed["must_change_password"] is False
        assert store.user_for_token(stale_token) is None
        assert _ok(client.get("/api/admin/overview"))["health"]["database"] == "ok"
        assert client.post("/api/auth/password", json={
            "current_password": ADMIN_PASSWORD, "new_password": ADMIN_PASSWORD,
        }).status_code == 422
        with store.connect() as db:
            changed_row = dict(db.execute("SELECT * FROM users WHERE email='admin'").fetchone())
            inventory = [tuple(row) for row in db.execute("SELECT id,kind,data FROM default_templates ORDER BY id")]
        assert changed_row["password"] != original["password"]
        assert store.password_matches(ADMIN_PASSWORD, changed_row["password"])
        assert not store.password_matches("admin", changed_row["password"])
    with TestClient(main.app) as restarted:
        with store.connect() as db:
            rows = db.execute("SELECT * FROM users WHERE email='admin'").fetchall()
            assert len(rows) == 1 and dict(rows[0]) == changed_row
            assert [tuple(row) for row in db.execute("SELECT id,kind,data FROM default_templates ORDER BY id")] == inventory
        assert restarted.post("/api/auth/login", json={"email": "admin", "password": "admin"}).status_code == 401
        user = _login(restarted, "admin", ADMIN_PASSWORD)
        assert user["id"] == original["id"] and user["must_change_password"] is False
        assert restarted.get("/api/admin/users").status_code == 200
        _session(restarted, stale_token)
        assert restarted.get("/api/auth/me").status_code == 401


def test_regular_user_cannot_escalate_or_access_admin(client):
    user = _register(client, role="admin", disabled=True, must_change_password=True)
    assert user["role"] == "user" and not user["disabled"] and not user["must_change_password"]
    changed = _ok(client.patch("/api/auth/me", json={
        "role": "admin", "disabled": True, "must_change_password": True, "email": "admin", "password": "changed", "name": "合法改名",
    }))
    assert changed["role"] == "user" and changed["email"] == user["email"]
    assert changed["name"] == "合法改名" and not changed["disabled"] and not changed["must_change_password"]
    endpoints = (
        ("GET", "/api/admin/overview", None), ("GET", "/api/admin/users", None),
        ("POST", "/api/admin/users", {}), ("PATCH", f"/api/admin/users/{user['id']}", {"role": "admin"}),
        ("DELETE", f"/api/admin/users/{user['id']}", None), ("POST", "/api/admin/users/batch", {}),
        ("GET", "/api/admin/defaults/skills", None), ("POST", "/api/admin/defaults/skills", {"name": "越权"}),
        ("GET", "/api/admin/alerts", None), ("POST", "/api/admin/alerts/batch", {}),
        ("GET", "/api/admin/audit", None), ("PATCH", "/api/admin/branding", {"name": "越权"}),
    )
    for method, path, body in endpoints:
        assert client.request(method, path, json=body).status_code == 403, (method, path)
    assert client.post("/api/admin/branding/assets", files={"file": ("logo.png", b"invalid", "image/png")}).status_code == 403
    with store.connect() as db:
        row = db.execute("SELECT password,data FROM users WHERE id=?", (user["id"],)).fetchone()
        assert store.password_matches(PASSWORD, row["password"])
        legacy = store.loads(row["data"])
        legacy.pop("role")
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(legacy), user["id"]))
    assert client.get("/api/admin/overview").status_code == 403
    assert client.get("/api/skills").status_code == 200


def test_admin_cannot_enter_user_chat_or_execution_apis(administrator):
    client = administrator
    assert _ok(client.get("/api/auth/me"))["role"] == "admin"
    assert client.get("/api/branding").status_code == 200
    denied = (
        ("GET", "/api/overview", None), ("GET", "/api/conversations", None),
        ("POST", "/api/conversations", {}), ("GET", "/api/conversations/missing", None),
        ("POST", "/api/conversations/missing/messages", {"content": "不得执行"}),
        ("POST", "/api/chat", {"content": "不得执行"}), ("GET", "/api/runs", None),
        ("GET", "/api/runs/missing/events", None), ("POST", "/api/runs/missing/cancel", {}),
        ("POST", "/api/approvals/missing", {"approved": True}), ("GET", "/api/preferences/chat", None),
        ("GET", "/api/agents", None), ("POST", "/api/agents/reorder", {"agent_ids": []}),
        ("POST", "/api/providers/missing/test", {}), ("POST", "/api/servers/missing/test", {}),
        ("POST", "/api/servers/missing/diagnose", {}), ("POST", "/api/alerts/missing/diagnose", {}),
        ("POST", "/api/schedules/missing/run", {}), ("POST", "/api/knowledge/search", {"query": "证据"}),
    )
    for method, path, body in denied:
        assert client.request(method, path, json=body).status_code == 403, (method, path)
    assert client.post("/api/files", files={"file": ("blocked.txt", b"blocked", "text/plain")}).status_code == 403
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM entities").fetchone()[0] == 0


@pytest.mark.parametrize(("kind", "agent_kind"), [
    *((kind, "local") for kind in defaults.KINDS), ("agents", "remote"),
])
def test_default_sync_stable_owner_ids_permissions_and_private_crud(administrator, kind, agent_kind):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    changes = {"kind": "remote", "url": "https://agents.example.invalid/remote"} if agent_kind == "remote" else {}
    source = _ok(client.post(f"/api/admin/defaults/{kind}", json={**_body(kind, "默认-" + kind), **changes}))
    template_before = defaults.get_template(kind, source["id"])
    editable = kind in {"skills", "knowledge"} or (kind == "agents" and agent_kind == "local")
    assert source["read_only"] is False
    first = _register(client)
    first_token = client.cookies.get("earthai_session")
    original = _copies(client, kind)[source["id"]]
    assert original["read_only"] is (not editable) and original["id"] != source["id"]
    private = _ok(client.post(f"/api/{kind}", json=_body(
        kind, "我的私有资源", default_template_id=source["id"], read_only=True,
    )))
    assert private["read_only"] is False and not private.get("default_template_id")
    assert _ok(client.patch(f"/api/{kind}/{private['id']}", json={"name": "我的修订"}))["name"] == "我的修订"
    content_field = {"skills": "content", "knowledge": "description", "agents": "system_prompt"}.get(kind, "name")
    personal_changes = {"name": "我的默认修订"}
    admin_changes = {"name": "管理员修订"}
    if editable:
        personal_changes[content_field] = "个人保留的内容与检查步骤"
        admin_changes[content_field] = "管理端新发布的内容与检查步骤"
        changed = _ok(client.patch(f"/api/{kind}/{original['id']}", json=personal_changes))
        assert all(changed[field] == value for field, value in personal_changes.items())
        assert changed["id"] == original["id"] and changed["default_template_id"] == source["id"]
        assert changed["read_only"] is False
    else:
        assert client.patch(f"/api/{kind}/{original['id']}", json={"name": "越权修改"}).status_code == 403
        assert client.delete(f"/api/{kind}/{original['id']}").status_code == 403
    assert defaults.get_template(kind, source["id"]) == template_before
    second = _register(client, "other@example.com")
    second_token = client.cookies.get("earthai_session")
    other = _copies(client, kind)[source["id"]]
    assert other["id"] not in {original["id"], source["id"]}
    assert other["name"] == source["name"] and other["read_only"] is (not editable)
    if editable:
        assert other[content_field] == source[content_field]
    assert all(item["id"] != private["id"] for item in _ok(client.get(f"/api/{kind}")))
    for id_ in (private["id"], original["id"]):
        assert client.patch(f"/api/{kind}/{id_}", json={"name": "跨用户"}).status_code == 404
        assert client.delete(f"/api/{kind}/{id_}").status_code == 404
    _session(client, admin_token)
    updated = _ok(client.patch(f"/api/admin/defaults/{kind}/{source['id']}", json=admin_changes))
    assert updated["id"] == source["id"] and updated["created_at"] == source["created_at"]
    for owner, token, before in ((first, first_token, original), (second, second_token, other)):
        _session(client, token)
        copy = _copies(client, kind)[source["id"]]
        overridden = editable and owner["id"] == first["id"]
        expected = personal_changes if overridden else admin_changes
        assert copy["id"] == before["id"] and copy["created_at"] == before["created_at"]
        assert all(copy[field] == value for field, value in expected.items())
        assert copy["read_only"] is (not editable)
        assert copy["default_revision"] == (original["default_revision"] if overridden else updated["updated_at"])
        assert store.get_entity(owner["id"], kind, copy["id"]) is not None
    _session(client, first_token)
    assert next(item for item in _ok(client.get(f"/api/{kind}")) if item["id"] == private["id"])["name"] == "我的修订"
    assert _ok(client.delete(f"/api/{kind}/{private['id']}")) == {"ok": True}
    assert store.get_entity(first["id"], kind, private["id"]) is None
    if editable:
        assert _ok(client.delete(f"/api/{kind}/{original['id']}")) == {"ok": True}
        defaults.sync_user(first["id"])
        assert source["id"] not in _copies(client, kind)
        assert store.get_entity(first["id"], kind, original["id"]) is None
        _session(client, second_token)
        assert _copies(client, kind)[source["id"]]["name"] == "管理员修订"
        _session(client, admin_token)
        assert _ok(client.get(f"/api/admin/defaults/{kind}/{source['id']}"))["name"] == "管理员修订"


@pytest.mark.parametrize(("target", "field"), [("providers", "provider_id"), ("skills", "skill_ids")])
def test_default_http_create_accepts_scalar_and_list_template_references(administrator, target, field):
    client = administrator
    reference = _default(client, target, "关联目标")
    value = [reference["id"]] if field.endswith("_ids") else reference["id"]
    created = _default(client, "agents", "带默认引用的智能体", **{field: value})
    assert created[field] == value


def test_default_references_are_remapped_to_each_owner(administrator):
    client = administrator
    sources = _linked_catalog(client)
    per_owner = []
    for email in ("first@example.com", "second@example.com"):
        user = _register(client, email)
        copies = {kind: _copies(client, kind)[value["id"]] for kind, value in sources.items()}
        assert copies["agents"]["provider_id"] == copies["providers"]["id"]
        assert copies["agents"]["skill_ids"] == [copies["skills"]["id"]]
        assert copies["agents"]["knowledge_ids"] == [copies["knowledge"]["id"]]
        assert copies["projects"]["server_ids"] == [copies["servers"]["id"]]
        assert copies["projects"]["knowledge_ids"] == [copies["knowledge"]["id"]]
        for field, kind in (("server_id", "servers"), ("provider_id", "providers"), ("agent_id", "agents")):
            assert copies["schedules"][field] == copies[kind]["id"]
        references = {field: copies[kind]["id"] for field, kind in defaults.SINGLE_REFS.items()}
        conversation = _ok(client.post("/api/conversations", json=references))
        assert all(conversation[field] == value for field, value in references.items())
        assert copies["providers"]["has_api_key"] and "api_key" not in copies["providers"]
        assert copies["servers"]["has_credentials"] and "password" not in copies["servers"]
        per_owner.append((user, copies))
    assert not ({item["id"] for item in per_owner[0][1].values()} & {item["id"] for item in per_owner[1][1].values()})
    assert client.post("/api/conversations", json={"provider_id": per_owner[0][1]["providers"]["id"]}).status_code == 404
    assert client.post("/api/conversations", json={"provider_id": sources["providers"]["id"]}).status_code == 404


def test_registration_installs_full_catalog_and_one_hundred_indexed_documents(client):
    count = len(presets.PRESETS)
    assert count == 50
    with store.connect() as db:
        template_stats = {row["template_id"]: (row["n"], row["chunks"]) for row in db.execute(
            "SELECT template_id,count(*) n,sum((length(content)+1149)/1150) chunks "
            "FROM template_documents GROUP BY template_id",
        )}
    assert len(template_stats) == 50 and all(3 <= value[0] <= 12 for value in template_stats.values())
    document_count = sum(value[0] for value in template_stats.values())
    chunk_count = sum(value[1] for value in template_stats.values())
    assert 150 <= document_count <= 600
    owner_ids, resource_ids = [], []
    for email in ("catalog-one@example.com", "catalog-two@example.com"):
        user = _register(client, email)
        owner_ids.append(user["id"])
        catalogs = {kind: _ok(client.get(f"/api/{kind}")) for kind in ("agents", "skills", "knowledge")}
        assert {kind: len(items) for kind, items in catalogs.items()} == {"agents": 50, "skills": 100, "knowledge": 50}
        assert all(not item["read_only"] and item["default_template_id"] for items in catalogs.values() for item in items)
        resource_ids.append({item["id"] for items in catalogs.values() for item in items})
        by_id = {item["id"]: item for items in catalogs.values() for item in items}
        for agent in catalogs["agents"]:
            assert by_id[agent["skill_ids"][0]]["builtin_domain"] == agent["builtin_domain"]
            assert by_id[agent["knowledge_ids"][0]]["builtin_domain"] == agent["builtin_domain"]
        preset = presets.PRESETS[0]
        knowledge = next(item for item in catalogs["knowledge"] if item["builtin_domain"] == preset["key"])
        documents = _ok(client.get(f"/api/knowledge/{knowledge['id']}/documents"))
        source = preset["documents"][0]
        document = next(item for item in documents if item["name"] == source["name"])
        expected = f"# {source['name'].removesuffix('.md')}\n\n{presets.REFERENCE_NOTICE}{source['content']}"
        assert _ok(client.get(f"/api/knowledge/{knowledge['id']}/documents/{document['id']}")) == {
            "id": document["id"], "name": source["name"], "text": expected,
        }
        assert all(3 <= item["document_count"] <= 12 for item in catalogs["knowledge"])
        assert {
            item["default_template_id"]: (item["document_count"], item["chunk_count"]) for item in catalogs["knowledge"]
        } == template_stats
        assert sum(item["document_count"] for item in catalogs["knowledge"]) == document_count
        assert sum(item["chunk_count"] for item in catalogs["knowledge"]) == chunk_count
    assert not (resource_ids[0] & resource_ids[1])
    assert list(store.UPLOADS.iterdir()) == []
    with store.connect() as db:
        for owner in owner_ids:
            for table in ("messages", "runs", "approvals", "resource_usage", "remote_agent_clicks"):
                assert db.execute(f"SELECT count(*) FROM {table} WHERE owner=?", (owner,)).fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM documents WHERE owner=?", (owner,)).fetchone()[0] == document_count
            assert db.execute("SELECT count(*) FROM documents WHERE owner=? AND (size<=0 OR chunk_count<=0)", (owner,)).fetchone()[0] == 0
            assert db.execute("SELECT count(DISTINCT document_id) FROM chunks WHERE owner=?", (owner,)).fetchone()[0] == document_count
            assert db.execute("SELECT count(*) FROM chunks WHERE owner=?", (owner,)).fetchone()[0] == chunk_count
            assert db.execute("SELECT sum(chunk_count) FROM documents WHERE owner=?", (owner,)).fetchone()[0] == chunk_count
        assert db.execute("SELECT count(*) FROM template_documents").fetchone()[0] == document_count
        assert db.execute("SELECT count(*) FROM chunks c LEFT JOIN documents d ON d.id=c.document_id "
                          "WHERE d.id IS NULL OR c.owner<>d.owner OR c.knowledge_id<>d.knowledge_id").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM entities WHERE owner=(SELECT id FROM users WHERE email='admin')").fetchone()[0] == 0


def test_default_document_body_and_search_updates_keep_user_document_ids(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    knowledge = _default(client, "knowledge", "正文同步")
    users = []
    for email in ("document-one@example.com", "document-two@example.com"):
        user = _register(client, email)
        copy = _copies(client, "knowledge")[knowledge["id"]]
        private = _ok(client.post("/api/knowledge", json={"name": "私有知识"}))
        private_doc = _ok(client.post(f"/api/knowledge/{private['id']}/documents", files={
            "file": ("private.md", b"privateadmintoken evidence", "text/markdown"),
        }))
        users.append((user, client.cookies.get("earthai_session"), copy, private, private_doc))
    _session(client, admin_token)
    old_text = "obsoleteadmintoken\n" + "只读证据与风险审批。\n" * 320
    document = _ok(client.post(f"/api/admin/defaults/knowledge/{knowledge['id']}/documents", json={
        "name": "original.md", "content": old_text,
    }))
    user_document_ids = []
    for _, token, copy, _, _ in users:
        _session(client, token)
        docs = _ok(client.get(f"/api/knowledge/{copy['id']}/documents"))
        assert len(docs) == 1
        user_document_ids.append(docs[0]["id"])
        assert _ok(client.get(f"/api/knowledge/{copy['id']}/documents/{docs[0]['id']}"))["text"] == old_text
        assert _ok(client.post("/api/knowledge/search", json={"query": "obsoleteadmintoken", "knowledge_ids": [copy["id"]]}))["results"]
        assert _copies(client, "knowledge")[knowledge["id"]]["read_only"] is False
    assert len(set(user_document_ids + [document["id"]])) == 3
    _session(client, admin_token)
    before = _snapshot()
    assert client.patch(f"/api/admin/defaults/knowledge/{knowledge['id']}/documents/{document['id']}", json={
        "name": "", "content": "invalid",
    }).status_code == 422
    assert _snapshot() == before
    new_text = "replacementadmintoken\n" + "新的正文与验证步骤。\n" * 370
    updated = _ok(client.patch(f"/api/admin/defaults/knowledge/{knowledge['id']}/documents/{document['id']}", json={
        "name": "updated.md", "content": new_text,
    }))
    assert updated["id"] == document["id"]
    assert _ok(client.get(f"/api/admin/defaults/knowledge/{knowledge['id']}/documents"))[0]["content"] == new_text
    for index, (_, token, copy, private, private_doc) in enumerate(users):
        _session(client, token)
        docs = _ok(client.get(f"/api/knowledge/{copy['id']}/documents"))
        assert docs[0]["id"] == user_document_ids[index]
        assert docs[0]["size"] == len(new_text.encode()) and docs[0]["chunk_count"] == len(range(0, len(new_text), 1150))
        assert _ok(client.get(f"/api/knowledge/{copy['id']}/documents/{docs[0]['id']}")) == {
            "id": docs[0]["id"], "name": "updated.md", "text": new_text,
        }
        for query, expected in (("obsoleteadmintoken", False), ("replacementadmintoken", True)):
            results = _ok(client.post("/api/knowledge/search", json={"query": query, "knowledge_ids": [copy["id"]]}))["results"]
            assert bool(results) is expected
        assert _ok(client.get(f"/api/knowledge/{private['id']}/documents/{private_doc['id']}"))["text"] == "privateadmintoken evidence"
        assert client.get(f"/api/knowledge/{copy['id']}/documents/{user_document_ids[1 - index]}").status_code == 404
        assert _ok(client.delete(f"/api/knowledge/{private['id']}/documents/{private_doc['id']}")) == {"ok": True}
    _session(client, admin_token)
    assert _ok(client.delete(f"/api/admin/defaults/knowledge/{knowledge['id']}/documents/{document['id']}"))["count"] == 1
    for _, token, copy, _, _ in users:
        _session(client, token)
        assert _ok(client.get(f"/api/knowledge/{copy['id']}/documents")) == []
        assert _ok(client.post("/api/knowledge/search", json={"query": "replacementadmintoken", "knowledge_ids": [copy["id"]]}))["results"] == []
    _session(client, admin_token)
    editable_document = _ok(client.post(f"/api/admin/defaults/knowledge/{knowledge['id']}/documents", json={
        "name": "editable.md", "content": "newdefaultdocumenttoken evidence",
    }))
    _, first_token, first_copy, _, _ = users[0]
    _, second_token, second_copy, _, _ = users[1]
    _session(client, first_token)
    inherited_document = _ok(client.get(f"/api/knowledge/{first_copy['id']}/documents"))[0]
    assert _ok(client.delete(f"/api/knowledge/{first_copy['id']}/documents/{inherited_document['id']}")) == {"ok": True}
    personal_document = _ok(client.post(f"/api/knowledge/{first_copy['id']}/documents", files={
        "file": ("personal.md", b"personaldocumenttoken evidence", "text/markdown"),
    }))
    assert _ok(client.get(f"/api/knowledge/{first_copy['id']}/documents/{personal_document['id']}"))["text"] == "personaldocumenttoken evidence"
    _session(client, second_token)
    untouched_document = _ok(client.get(f"/api/knowledge/{second_copy['id']}/documents"))[0]
    assert _ok(client.get(f"/api/knowledge/{second_copy['id']}/documents/{untouched_document['id']}"))["text"] == "newdefaultdocumenttoken evidence"
    _session(client, admin_token)
    template_documents = _ok(client.get(f"/api/admin/defaults/knowledge/{knowledge['id']}/documents"))
    assert len(template_documents) == 1 and template_documents[0]["id"] == editable_document["id"]
    assert template_documents[0]["content"] == "newdefaultdocumenttoken evidence"
    _ok(client.patch(f"/api/admin/defaults/knowledge/{knowledge['id']}/documents/{editable_document['id']}", json={
        "name": "editable.md", "content": "latestdefaultdocumenttoken evidence",
    }))
    _session(client, first_token)
    assert _ok(client.get(f"/api/knowledge/{first_copy['id']}/documents")) == [personal_document]
    assert _ok(client.get(f"/api/knowledge/{first_copy['id']}/documents/{personal_document['id']}"))["text"] == "personaldocumenttoken evidence"
    assert _ok(client.post("/api/knowledge/search", json={"query": "personaldocumenttoken", "knowledge_ids": [first_copy["id"]]}))["results"]
    assert _ok(client.post("/api/knowledge/search", json={"query": "latestdefaultdocumenttoken", "knowledge_ids": [first_copy["id"]]}))["results"] == []
    _session(client, second_token)
    assert _ok(client.get(f"/api/knowledge/{second_copy['id']}/documents"))[0]["id"] == untouched_document["id"]
    assert _ok(client.get(f"/api/knowledge/{second_copy['id']}/documents/{untouched_document['id']}"))["text"] == "latestdefaultdocumenttoken evidence"
    assert _ok(client.post("/api/knowledge/search", json={"query": "latestdefaultdocumenttoken", "knowledge_ids": [second_copy["id"]]}))["results"]


@pytest.mark.parametrize("kind", defaults.KINDS)
def test_default_batches_and_imports_validate_before_writing(administrator, kind):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    sources = [_default(client, kind, name) for name in ("批量一", "批量二")]
    if kind == "knowledge":
        _ok(client.post(f"/api/admin/defaults/knowledge/{sources[0]['id']}/documents", json={"name": "batch.md", "content": "batchcleanup"}))
    owner = _register(client)
    owner_token = client.cookies.get("earthai_session")
    copies = {source["id"]: _copies(client, kind)[source["id"]] for source in sources}
    _session(client, admin_token)
    path = f"/api/admin/defaults/{kind}"
    before = _snapshot()
    for body in (
        {"ids": [sources[0]["id"], "missing"], "action": "update", "changes": {"name": "不应写入"}},
        {"ids": [sources[0]["id"], "missing"], "action": "delete"},
        {"ids": [sources[0]["id"], sources[0]["id"]], "action": "delete"},
        {"ids": [source["id"] for source in sources], "action": "update", "changes": {"name": ""}},
    ):
        assert client.post(path + "/batch", json=body).status_code == 422
        assert _snapshot() == before
    assert client.post(path + "/import", json={"items": [_body(kind, "不应导入"), _body(kind, "")]}).status_code == 422
    assert _snapshot() == before
    assert _ok(client.post(path + "/batch", json={
        "ids": [source["id"] for source in sources], "action": "update", "changes": {"name": "批量修订"},
    })) == {"ok": True, "count": 2}
    _session(client, owner_token)
    for source in sources:
        copy = _copies(client, kind)[source["id"]]
        assert copy["name"] == "批量修订" and copy["id"] == copies[source["id"]]["id"]
    _session(client, admin_token)
    original_ids = {item["id"] for item in _ok(client.get(path))}
    assert _ok(client.post(path + "/import", json={"items": [_body(kind, "导入一"), _body(kind, "导入二")]})) == {"ok": True, "count": 2}
    imported = {item["id"] for item in _ok(client.get(path))} - original_ids
    assert len(imported) == 2
    assert _ok(client.post(path + "/batch", json={"ids": [source["id"] for source in sources], "action": "delete"}))["count"] == 2
    assert all(source["id"] not in {item["id"] for item in _ok(client.get(path))} for source in sources)
    _session(client, owner_token)
    remaining = _copies(client, kind)
    assert imported <= remaining.keys() and not (copies.keys() & remaining.keys())
    if kind == "knowledge":
        with store.connect() as db:
            for copy in copies.values():
                assert db.execute("SELECT count(*) FROM documents WHERE owner=? AND knowledge_id=?", (owner["id"], copy["id"])).fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM chunks WHERE owner=? AND knowledge_id=?", (owner["id"], copy["id"])).fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM template_documents WHERE template_id=?", (sources[0]["id"],)).fetchone()[0] == 0


def test_default_document_batch_is_atomic_and_cleans_copies(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    source = _default(client, "knowledge", "文档批量删除")
    path = f"/api/admin/defaults/knowledge/{source['id']}/documents"
    documents = [_ok(client.post(path, json={"name": name, "content": "documentbatchtoken " + name})) for name in ("one.md", "two.md")]
    owners = []
    for email in ("batch-one@example.com", "batch-two@example.com"):
        owner = _register(client, email)
        owners.append((owner, client.cookies.get("earthai_session"), _copies(client, "knowledge")[source["id"]]))
    _session(client, admin_token)
    before = _snapshot()
    for body in (
        {"ids": [documents[0]["id"], "missing"], "action": "delete"},
        {"ids": [documents[0]["id"], documents[0]["id"]], "action": "delete"},
        {"ids": [document["id"] for document in documents], "action": "update", "changes": {"content": "不应写入"}},
    ):
        assert client.post(path + "/batch", json=body).status_code == 422
        assert _snapshot() == before
    assert _ok(client.post(path + "/batch", json={"ids": [document["id"] for document in documents], "action": "delete"}))["count"] == 2
    assert _ok(client.get(path)) == []
    for owner, token, copy in owners:
        _session(client, token)
        assert _ok(client.get(f"/api/knowledge/{copy['id']}/documents")) == []
        with store.connect() as db:
            assert db.execute("SELECT count(*) FROM chunks WHERE owner=? AND knowledge_id=?", (owner["id"], copy["id"])).fetchone()[0] == 0
        assert _copies(client, "knowledge")[source["id"]]["document_count"] == 0


def test_deleting_defaults_clears_all_template_and_user_copy_references(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    sources = _linked_catalog(client)
    _ok(client.post(f"/api/admin/defaults/knowledge/{sources['knowledge']['id']}/documents", json={"name": "cleanup.md", "content": "cleanupindex"}))
    owners = []
    for email in ("cleanup-one@example.com", "cleanup-two@example.com"):
        owner = _register(client, email)
        copies = {kind: _copies(client, kind)[source["id"]] for kind, source in sources.items()}
        owners.append((owner, client.cookies.get("earthai_session"), copies))
    _session(client, admin_token)
    removed = set()
    for kind in ("providers", "servers", "knowledge", "skills", "agents", "projects", "schedules"):
        source_id = sources[kind]["id"]
        assert _ok(client.delete(f"/api/admin/defaults/{kind}/{source_id}"))["count"] == 1
        removed.add(kind)
        for other_kind, source in sources.items():
            if other_kind in removed:
                continue
            value = _ok(client.get(f"/api/admin/defaults/{other_kind}/{source['id']}"))
            for field, target in defaults.SINGLE_REFS.items():
                if target == kind:
                    assert not value.get(field)
            for field, target in defaults.MULTI_REFS.items():
                if target == kind:
                    assert source_id not in value.get(field, [])
        for owner, token, copies in owners:
            _session(client, token)
            assert source_id not in _copies(client, kind)
            for other_kind, source in sources.items():
                if other_kind in removed:
                    continue
                value = _copies(client, other_kind)[source["id"]]
                for field, target in defaults.SINGLE_REFS.items():
                    if target == kind:
                        assert not value.get(field)
                for field, target in defaults.MULTI_REFS.items():
                    if target == kind:
                        assert copies[kind]["id"] not in value.get(field, [])
            if kind == "knowledge":
                with store.connect() as db:
                    assert db.execute("SELECT count(*) FROM documents WHERE owner=? AND knowledge_id=?", (owner["id"], copies[kind]["id"])).fetchone()[0] == 0
                    assert db.execute("SELECT count(*) FROM chunks WHERE owner=? AND knowledge_id=?", (owner["id"], copies[kind]["id"])).fetchone()[0] == 0
        _session(client, admin_token)


def test_running_default_resources_cannot_be_changed_or_deleted(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    source = _default(client, "agents", "执行锁定")
    owner = _register(client)
    copy = _copies(client, "agents")[source["id"]]
    conversation = _ok(client.post("/api/conversations", json={"agent_id": copy["id"]}))
    run_id = _run(owner["id"], conversation, agent_id=copy["id"])
    _session(client, admin_token)
    before = _snapshot()
    assert client.patch(f"/api/admin/defaults/agents/{source['id']}", json={"name": "不应更新"}).status_code == 422
    assert client.delete(f"/api/admin/defaults/agents/{source['id']}").status_code == 422
    assert client.post("/api/admin/defaults/agents/batch", json={"ids": [source["id"]], "action": "delete"}).status_code == 422
    assert _snapshot() == before
    store.update_run(owner["id"], run_id, status="completed")
    assert _ok(client.patch(f"/api/admin/defaults/agents/{source['id']}", json={"name": "执行后更新"}))["name"] == "执行后更新"


def test_admin_user_crud_and_protected_accounts_validate_whole_batch(administrator):
    client = administrator
    initial = _ok(client.get("/api/auth/me"))
    primary_token = client.cookies.get("earthai_session")
    second = _ok(client.post("/api/admin/users", json={"email": "second-admin", "name": "第二管理员", "password": PASSWORD, "role": "admin"}))
    regular = _ok(client.post("/api/admin/users", json={"email": "managed-user", "name": "普通账号", "password": PASSWORD}))
    assert regular["role"] == "user" and not regular["disabled"]
    assert len(store.list_entities(regular["id"], "agents")) == len(presets.PRESETS)
    assert store.list_entities(second["id"], "agents") == []
    listed = _ok(client.get("/api/admin/users"))
    assert {initial["id"], second["id"], regular["id"]} <= {user["id"] for user in listed}
    assert all("password" not in user for user in listed)
    assert _ok(client.patch(f"/api/admin/users/{regular['id']}", json={"name": "后台改名"}))["name"] == "后台改名"
    assert client.post("/api/admin/users", json={"email": "managed-user", "name": "重复", "password": PASSWORD}).status_code == 422
    for changes in ({"role": "root"}, {"disabled": "false"}, {"password": "short"}, {"email": "bad account"}, {"unknown": True}):
        before = _snapshot()
        assert client.patch(f"/api/admin/users/{regular['id']}", json=changes).status_code == 422
        assert _snapshot() == before
    _login(client, "second-admin")
    before = _snapshot()
    for id_ in (initial["id"], second["id"]):
        assert client.delete(f"/api/admin/users/{id_}").status_code == 422
        for changes in ({"disabled": True}, {"role": "user"}):
            assert client.patch(f"/api/admin/users/{id_}", json=changes).status_code == 422
    assert client.patch(f"/api/admin/users/{initial['id']}", json={"email": "renamed-admin"}).status_code == 422
    for body in (
        {"ids": [regular["id"], initial["id"]], "action": "delete"},
        {"ids": [regular["id"], initial["id"]], "action": "update", "changes": {"role": "user"}},
        {"ids": [regular["id"], "missing"], "action": "update", "changes": {"name": "不应写入"}},
        {"ids": [regular["id"], regular["id"]], "action": "delete"},
    ):
        assert client.post("/api/admin/users/batch", json=body).status_code == 422
        assert _snapshot() == before
    _session(client, primary_token)
    assert _ok(client.post("/api/admin/users/batch", json={
        "ids": [regular["id"]], "action": "update", "changes": {"name": "批量改名"},
    }))["count"] == 1
    assert _ok(client.delete(f"/api/admin/users/{regular['id']}"))["count"] == 1
    assert all(user["id"] != regular["id"] for user in _ok(client.get("/api/admin/users")))


def test_role_changes_cancel_runs_disable_schedules_and_revoke_sessions(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    user = _register(client)
    original_token = client.cookies.get("earthai_session")
    schedule = _ok(client.post("/api/schedules", json=_body("schedules", "晋升前任务", enabled=True)))
    conversation = _ok(client.post("/api/conversations", json={}))
    run_id = _run(user["id"], conversation)
    _session(client, admin_token)
    promoted = _ok(client.patch(f"/api/admin/users/{user['id']}", json={"role": "admin"}))
    assert promoted["role"] == "admin" and store.user_for_token(original_token) is None
    assert store.get_run(user["id"], run_id)["status"] == "cancelled"
    assert store.get_entity(user["id"], "schedules", schedule["id"])["enabled"] is False
    _session(client, original_token)
    assert client.get("/api/auth/me").status_code == 401
    _login(client, user["email"])
    promoted_token = client.cookies.get("earthai_session")
    assert client.get("/api/admin/overview").status_code == 200
    assert client.get("/api/conversations").status_code == 403
    _session(client, admin_token)
    assert _ok(client.patch(f"/api/admin/users/{user['id']}", json={"role": "user"}))["role"] == "user"
    _session(client, promoted_token)
    assert client.get("/api/auth/me").status_code == 401
    _login(client, user["email"])
    assert client.get("/api/admin/overview").status_code == 403
    assert len(_copies(client, "agents")) == len(presets.PRESETS)


def test_password_reset_disable_and_reenable_invalidate_existing_sessions(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    user = _register(client)
    original_token = client.cookies.get("earthai_session")
    _session(client, admin_token)
    reset_password = "Reset-user-password!"
    reset = _ok(client.patch(f"/api/admin/users/{user['id']}", json={"password": reset_password}))
    assert reset["must_change_password"] is True and store.user_for_token(original_token) is None
    assert client.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}).status_code == 401
    _login(client, user["email"], reset_password)
    reset_token = client.cookies.get("earthai_session")
    assert client.get("/api/skills").status_code == 403
    assert _ok(client.patch("/api/auth/me", json={"must_change_password": False}))["must_change_password"] is True
    assert client.get("/api/skills").status_code == 403
    _ok(client.post("/api/auth/password", json={"current_password": reset_password, "new_password": PASSWORD}))
    active_token = client.cookies.get("earthai_session")
    assert store.user_for_token(reset_token) is None and client.get("/api/skills").status_code == 200
    conversation = _ok(client.post("/api/conversations", json={}))
    run_id = _run(user["id"], conversation, status="waiting_approval")
    _session(client, admin_token)
    assert _ok(client.patch(f"/api/admin/users/{user['id']}", json={"disabled": True}))["disabled"] is True
    assert store.get_run(user["id"], run_id)["status"] == "cancelled"
    _session(client, active_token)
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}).status_code == 403
    _session(client, admin_token)
    assert _ok(client.patch(f"/api/admin/users/{user['id']}", json={"disabled": False}))["disabled"] is False
    assert store.user_for_token(active_token) is None
    assert _login(client, user["email"])["disabled"] is False


def test_user_deletion_cleans_owned_rows_uploads_and_sessions_only(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    owner = _register(client, "delete@example.com")
    owner_token = client.cookies.get("earthai_session")
    uploaded = _ok(client.post("/api/files", files={"file": ("private.txt", b"private evidence", "text/plain")}))
    storage = store.UPLOADS / store.get_entity(owner["id"], "files", uploaded["id"])["storage_name"]
    knowledge = _ok(client.post("/api/knowledge", json={"name": "待删除知识"}))
    _ok(client.post(f"/api/knowledge/{knowledge['id']}/documents", files={"file": ("private.md", b"deleteindextoken", "text/markdown")}))
    _ok(client.get("/api/agents"))
    inherited_skill = next(iter(_copies(client, "skills").values()))
    _ok(client.patch(f"/api/skills/{inherited_skill['id']}", json={"content": "待删除的个人默认技能"}))
    conversation = _ok(client.post("/api/conversations", json={}))
    run_id = _run(owner["id"], conversation, status="waiting_approval")
    store.add_message(owner["id"], conversation["id"], "user", "待删除消息", run_id)
    store.emit(run_id, "status", {"status": "waiting_approval"})
    with store.connect() as db:
        db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?)", (
            store.uid(), owner["id"], run_id, "ssh_exec", "{}", "write", "pending", store.now(),
        ))
    survivor = _register(client, "survivor@example.com")
    survivor_token = client.cookies.get("earthai_session")
    survivor_file = _ok(client.post("/api/files", files={"file": ("keep.txt", b"keep evidence", "text/plain")}))
    survivor_storage = store.UPLOADS / store.get_entity(survivor["id"], "files", survivor_file["id"])["storage_name"]
    survivor_skill = next(iter(_copies(client, "skills").values()))
    _ok(client.patch(f"/api/skills/{survivor_skill['id']}", json={"content": "应保留的个人默认技能"}))
    with store.connect() as db:
        for user in (owner, survivor):
            assert db.execute("SELECT count(*) FROM default_owner_states WHERE owner=?", (user["id"],)).fetchone()[0] == 1
    survivor_before = _owner_snapshot(survivor["id"])
    _session(client, admin_token)
    before = _snapshot()
    assert client.post("/api/admin/users/batch", json={"ids": [owner["id"], "missing"], "action": "delete"}).status_code == 422
    assert _snapshot() == before and storage.is_file()
    assert _ok(client.post("/api/admin/users/batch", json={"ids": [owner["id"]], "action": "delete"}))["count"] == 1
    assert not storage.exists() and survivor_storage.read_bytes() == b"keep evidence"
    assert all(not rows for rows in _owner_snapshot(owner["id"]).values())
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM events WHERE run_id=?", (run_id,)).fetchone()[0] == 0
    assert _owner_snapshot(survivor["id"]) == survivor_before
    _session(client, owner_token)
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": owner["email"], "password": PASSWORD}).status_code == 401
    _session(client, survivor_token)
    assert _ok(client.get("/api/auth/me"))["id"] == survivor["id"]
    assert client.get(f"/api/files/{survivor_file['id']}/download").content == b"keep evidence"


def test_admin_alerts_span_owners_and_bulk_failures_do_not_partially_write(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    first = _register(client, "alerts-one@example.com")
    first_token = client.cookies.get("earthai_session")
    one = _ok(client.post("/api/alerts", json={"title": "一号告警", "severity": "critical"}))
    two = _ok(client.post("/api/alerts", json={"title": "二号告警"}))
    second = _register(client, "alerts-two@example.com")
    second_token = client.cookies.get("earthai_session")
    three = _ok(client.post("/api/alerts", json={"title": "三号告警"}))
    assert {item["id"] for item in _ok(client.get("/api/alerts"))} == {three["id"]}
    assert client.patch(f"/api/alerts/{one['id']}", json={"status": "resolved"}).status_code == 404
    assert client.delete(f"/api/alerts/{one['id']}").status_code == 404
    assert client.get("/api/admin/alerts").status_code == 403
    assert client.patch(f"/api/admin/alerts/{one['id']}", json={"status": "resolved"}).status_code == 403
    assert client.delete(f"/api/admin/alerts/{one['id']}").status_code == 403
    _session(client, admin_token)
    alerts = {item["id"]: item for item in _ok(client.get("/api/admin/alerts"))}
    assert set(alerts) == {one["id"], two["id"], three["id"]}
    assert alerts[one["id"]]["owner_id"] == first["id"] and alerts[three["id"]]["owner_email"] == second["email"]
    before = _snapshot()
    for body in (
        {"ids": [one["id"], "missing"], "action": "update", "changes": {"status": "resolved"}},
        {"ids": [one["id"], "missing"], "action": "delete"},
        {"ids": [one["id"], one["id"]], "action": "delete"},
        {"ids": [one["id"], three["id"]], "action": "update", "changes": {"severity": "fatal"}},
    ):
        assert client.post("/api/admin/alerts/batch", json=body).status_code == 422
        assert _snapshot() == before
    assert client.patch(f"/api/admin/alerts/{one['id']}", json={"owner_id": second["id"]}).status_code == 422
    assert _snapshot() == before
    assert _ok(client.post("/api/admin/alerts/batch", json={
        "ids": [one["id"], three["id"]], "action": "update", "changes": {"status": "resolved"},
    }))["count"] == 2
    assert _ok(client.patch(f"/api/admin/alerts/{two['id']}", json={"description": "后台复核", "severity": "info"}))["description"] == "后台复核"
    _session(client, first_token)
    assert next(item for item in _ok(client.get("/api/alerts")) if item["id"] == one["id"])["status"] == "resolved"
    _session(client, second_token)
    assert _ok(client.get("/api/alerts"))[0]["status"] == "resolved"
    _session(client, admin_token)
    assert _ok(client.delete(f"/api/admin/alerts/{one['id']}"))["count"] == 1
    assert _ok(client.post("/api/admin/alerts/batch", json={"ids": [two["id"], three["id"]], "action": "delete"}))["count"] == 2
    assert _ok(client.get("/api/admin/alerts")) == []
    audit = _ok(client.get("/api/admin/audit"))
    assert any(item["action"] == "admin.alerts.update" and item["owner_email"] == "admin" for item in audit)


def test_branding_is_public_validated_and_serves_only_local_image_assets(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    client.cookies.clear()
    original = _ok(client.get("/api/branding"))
    assert original["name"] == "EarthAI" and original["favicon_url"] == "/favicon.ico"
    assert client.patch("/api/admin/branding", json={"name": "未登录"}).status_code == 401
    _session(client, admin_token)
    valid = {
        "name": "  Operations  ", "subtitle": "LOCAL", "tagline": "只读证据优先",
        "title_font_family": "Noto Sans SC", "subtitle_font_family": "system-ui",
        "title_font_size": 40, "subtitle_font_size": 6, "title_color": "#Ab12EF", "subtitle_color": "#012345",
    }
    configured = _ok(client.patch("/api/admin/branding", json=valid))
    assert configured["name"] == "Operations" and configured["title_font_size"] == 40 and configured["subtitle_font_size"] == 6
    before = _snapshot()
    for invalid in (
        {"name": ""}, {"title_color": "red"}, {"title_color": "#123"}, {"subtitle_color": "#000000;display:none"},
        {"title_font_size": 13}, {"title_font_size": 41}, {"title_font_size": True}, {"subtitle_font_size": 25},
        {"subtitle_font_size": 5}, {"title_font_family": "https://fonts.example/font.css"},
        {"icon_url": "https://attacker.example/logo.png"}, {"icon_url": "//attacker.example/logo.png"},
        {"favicon_url": "javascript:alert(1)"}, {"icon_url": "data:image/svg+xml,<svg/>"},
        {"icon_url": "/api/branding/assets/../payload.svg"}, {"unknown_css": "body{}"},
    ):
        assert client.patch("/api/admin/branding", json=invalid).status_code == 422
        assert _snapshot() == before
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz4AAAAASUVORK5CYII=")
    uploaded = _ok(client.post("/api/admin/branding/assets", files={"file": ("../../logo.svg", png, "image/svg+xml")}))
    assert uploaded["url"].startswith("/api/branding/assets/") and uploaded["url"].endswith(".png")
    directory = store.DATA / "branding"
    assert [path.name for path in directory.iterdir()] == [uploaded["url"].rsplit("/", 1)[1]]
    _ok(client.patch("/api/admin/branding", json={"icon_url": uploaded["url"], "favicon_url": uploaded["url"]}))
    existing = set(directory.iterdir())
    for content in (b"", b"<svg><script>alert(1)</script></svg>", b"<html>script</html>", b"not an image", b"x" * (2 * 1024 * 1024 + 1)):
        assert client.post("/api/admin/branding/assets", files={"file": ("fake.png", content, "image/png")}).status_code == 422
        assert set(directory.iterdir()) == existing
    client.cookies.clear()
    public = _ok(client.get("/api/branding"))
    assert public["name"] == "Operations" and public["icon_url"] == uploaded["url"]
    manifest = _ok(client.get("/site.webmanifest"))
    assert manifest["short_name"] == "Operations" and manifest["icons"][0]["src"] == uploaded["url"]
    assert client.get("/favicon.ico").content == png
    asset = client.get(uploaded["url"])
    assert asset.status_code == 200 and asset.content == png
    assert asset.headers["content-type"] == "image/png" and asset.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/branding/assets/00000000-0000-0000-0000-000000000000.png").status_code == 404
    assert client.get("/api/branding/assets/payload.svg").status_code == 422


@pytest.mark.parametrize("flags", [{"role": "admin"}, {"disabled": True}, {"must_change_password": True}])
def test_execution_engine_rejects_restricted_accounts_before_any_side_effect(client, flags):
    owner = _register(client)
    assert access.execution_allowed(owner["id"]) is None
    with store.connect() as db:
        data = store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner["id"],)).fetchone()[0])
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps({**data, **flags}), owner["id"]))
    before = _snapshot()
    with pytest.raises(ValueError, match="不能执行运维任务"):
        engine.create_run(owner["id"], {"id": "not-created", "agent_id": "not-looked-up"}, "不得执行")
    with pytest.raises(ValueError, match="不能执行运维任务"):
        engine.trigger_schedule(owner["id"], {"agent_id": "not-looked-up"})
    assert _snapshot() == before and engine.TASKS == {}
    with pytest.raises(ValueError, match="执行账号不存在"):
        engine.create_run("missing-owner", {"id": "missing"}, "不得执行")


@pytest.mark.asyncio
async def test_scheduler_skips_admin_disabled_and_password_change_accounts(isolated_store, monkeypatch):
    store.init_db()
    owners = []
    states = ({"role": "admin"}, {"role": "user", "disabled": True}, {"must_change_password": True}, {})
    for index, data in enumerate(states):
        owner = store.uid()
        with store.connect() as db:
            db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (owner, f"scheduler-{index}", "unused", store.dumps(data), store.now()))
        schedule = store.save_entity(owner, "schedules", {
            **_body("schedules", f"任务{index}", enabled=True), "next_run_at": "2000-01-01T00:00:00+00:00",
        })
        owners.append((owner, schedule))
    dispatched = Mock(return_value={})
    monkeypatch.setattr(engine, "trigger_schedule", dispatched)

    async def stop_after_tick(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(engine.asyncio, "sleep", stop_after_tick)
    with pytest.raises(asyncio.CancelledError):
        await engine.scheduler_loop()
    dispatched.assert_called_once()
    assert dispatched.call_args.args[0] == owners[-1][0]
    for owner, schedule in owners[:-1]:
        assert store.get_entity(owner, "schedules", schedule["id"])["next_run_at"] == schedule["next_run_at"]
    owner, schedule = owners[-1]
    assert store.get_entity(owner, "schedules", schedule["id"])["next_run_at"] != schedule["next_run_at"]


def test_restricting_user_cancels_active_runs_older_than_two_hundred_terminal_runs(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    owner = _register(client, "old-active@example.com")
    active = []
    for status in ("queued", "running", "waiting_approval"):
        conversation = _ok(client.post("/api/conversations", json={}))
        active.append(_run(owner["id"], conversation, status=status))
    terminal_conversation = _ok(client.post("/api/conversations", json={}))
    stamp = store.now()
    with store.connect() as db:
        db.execute("UPDATE runs SET created_at=? WHERE owner=?", ("2000-01-01T00:00:00+00:00", owner["id"]))
        db.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", [
            (store.uid(), owner["id"], terminal_conversation["id"], "completed", "{}", stamp, stamp)
            for _ in range(205)
        ])
        db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?)", (
            store.uid(), owner["id"], active[-1], "ssh_exec", "{}", "write", "pending", stamp,
        ))
    recent = store.list_runs(owner["id"])
    assert len(recent) == 200 and all(run["status"] == "completed" for run in recent)
    assert not (set(active) & {run["id"] for run in recent})
    _session(client, admin_token)
    assert _ok(client.patch(f"/api/admin/users/{owner['id']}", json={"disabled": True}))["disabled"] is True
    assert all(store.get_run(owner["id"], id_)["status"] == "cancelled" for id_ in active)
    assert all(store.events(id_)[-1]["data"]["status"] == "cancelled" for id_ in active)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM runs WHERE owner=? AND status='completed'", (owner["id"],)).fetchone()[0] == 205
        assert db.execute("SELECT status FROM approvals WHERE run_id=?", (active[-1],)).fetchone()[0] == "expired"
        assert db.execute("SELECT count(*) FROM runs WHERE owner=? AND status IN ('queued','running','waiting_approval')", (owner["id"],)).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_password_reset_cancels_running_model_task_before_tools_execute(isolated_store, monkeypatch):
    started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def blocked_model(*args):
        progress.MODEL_EVENTS.get()("content", {"content": "已开始分析，等待后续数据。"})
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": "must-not-execute", "type": "function", "function": {"name": "list_files", "arguments": "{}"},
        }]}

    model = AsyncMock(side_effect=blocked_model)
    execute = AsyncMock(side_effect=AssertionError("password reset must prevent tool execution"))
    monkeypatch.setattr(engine, "model_completion", model)
    monkeypatch.setattr(tools, "execute", execute)
    async with main.lifespan(main.app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver",
    ) as client:
        _ok(await client.post("/api/auth/login", json={"email": "admin", "password": "admin"}))
        _ok(await client.post("/api/auth/password", json={"current_password": "admin", "new_password": ADMIN_PASSWORD}))
        admin_token = client.cookies.get("earthai_session")
        owner = _ok(await client.post("/api/auth/register", json={"email": "live-reset@example.com", "password": PASSWORD}))
        owner_token = client.cookies.get("earthai_session")
        provider = _ok(await client.post("/api/providers", json=_body("providers", "受控模型")))
        conversation = _ok(await client.post("/api/conversations", json={"provider_id": provider["id"]}))
        run = _ok(await client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "概述个人资料"}))
        task = engine.TASKS[run["id"]]
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            assert not task.done() and store.get_run(owner["id"], run["id"])["status"] == "running"
            _session(client, admin_token)
            changed = _ok(await client.patch(f"/api/admin/users/{owner['id']}", json={"password": "Reset-active-password!"}))
            assert changed["must_change_password"] is True
            assert cancelled.is_set() and task.done() and task.cancelled()
            assert run["id"] not in engine.TASKS and run["id"] not in engine.CANCEL_TOKENS
            assert store.get_run(owner["id"], run["id"])["status"] == "cancelled"
            assert store.user_for_token(owner_token) is None
            events = store.events(run["id"])
            assert any(event["type"] == "model_end" and event["data"].get("interrupted") for event in events)
            assert not any(event["type"] in {"tool_start", "tool_execution", "tool_result"} for event in events)
            model.assert_awaited_once()
            execute.assert_not_awaited()
            _session(client, owner_token)
            assert (await client.get("/api/auth/me")).status_code == 401
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_deleting_user_waits_for_stream_cancellation_before_removing_owned_rows(isolated_store, monkeypatch):
    started, release, cancelling, cleanup_release = (asyncio.Event() for _ in range(4))
    cleanup_finished = asyncio.Event()

    async def streaming_model(*args):
        callback = progress.MODEL_EVENTS.get()
        callback("content", {"content": "正在输出公开分析，等待下一段。"})
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelling.set()
            await cleanup_release.wait()
            callback("content", {"content": "正在输出公开分析，取消后保留这段未完成正文。"})
            cleanup_finished.set()
            raise
        return {"role": "assistant", "content": "不应完成的回复"}

    model = AsyncMock(side_effect=streaming_model)
    monkeypatch.setattr(engine, "model_completion", model)
    async with main.lifespan(main.app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver",
    ) as client:
        _ok(await client.post("/api/auth/login", json={"email": "admin", "password": "admin"}))
        _ok(await client.post("/api/auth/password", json={"current_password": "admin", "new_password": ADMIN_PASSWORD}))
        admin_token = client.cookies.get("earthai_session")
        owner = _ok(await client.post("/api/auth/register", json={"email": "live-delete@example.com", "password": PASSWORD}))
        owner_token = client.cookies.get("earthai_session")
        provider = _ok(await client.post("/api/providers", json=_body("providers", "删除期间的受控模型")))
        conversation = _ok(await client.post("/api/conversations", json={"provider_id": provider["id"]}))
        run = _ok(await client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "概述个人资料"}))
        task = engine.TASKS[run["id"]]
        deleting = None
        writes, late_writes = [], []
        original_emit, original_add_message = store.emit, store.add_message

        def record_write(kind):
            writes.append(kind)
            with store.connect() as db:
                if db.execute("SELECT 1 FROM users WHERE id=?", (owner["id"],)).fetchone() is None:
                    late_writes.append(kind)

        def record_emit(run_id, type_, data):
            if run_id == run["id"]:
                record_write(type_)
            return original_emit(run_id, type_, data)

        def record_message(owner_id, conversation_id, role, content, run_id=None):
            if owner_id == owner["id"]:
                record_write("message." + role)
            return original_add_message(owner_id, conversation_id, role, content, run_id)

        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            assert any(event["type"] == "assistant_delta" for event in store.events(run["id"]))
            monkeypatch.setattr(store, "emit", record_emit)
            monkeypatch.setattr(store, "add_message", record_message)
            _session(client, admin_token)
            deleting = asyncio.create_task(client.delete(f"/api/admin/users/{owner['id']}"))
            await asyncio.wait_for(cancelling.wait(), timeout=3)
            assert not deleting.done() and not task.done()
            assert store.user_for_token(owner_token) is None
            with store.connect() as db:
                row = db.execute("SELECT data FROM users WHERE id=?", (owner["id"],)).fetchone()
                assert row is not None and store.loads(row["data"])["disabled"] is True
            assert store.get_entity(owner["id"], "conversations", conversation["id"]) is not None
            assert store.get_run(owner["id"], run["id"])["status"] == "cancelled"
            cleanup_release.set()
            assert _ok(await asyncio.wait_for(deleting, timeout=3))["count"] == 1
            assert cleanup_finished.is_set() and task.done() and task.cancelled()
            assert {"assistant", "model_end", "message.assistant"} <= set(writes)
            assert late_writes == []
            assert run["id"] not in engine.TASKS and run["id"] not in engine.CANCEL_TOKENS
            assert all(not rows for rows in _owner_snapshot(owner["id"]).values())
            with store.connect() as db:
                assert db.execute("SELECT count(*) FROM events WHERE run_id=?", (run["id"],)).fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM messages WHERE run_id=?", (run["id"],)).fetchone()[0] == 0
            assert store.user_for_token(owner_token) is None
            model.assert_awaited_once()
            _session(client, owner_token)
            assert (await client.get("/api/auth/me")).status_code == 401
        finally:
            release.set()
            cleanup_release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if deleting is not None:
                await asyncio.wait_for(asyncio.gather(deleting, return_exceptions=True), timeout=3)


def test_legacy_knowledge_with_same_name_and_size_but_changed_text_remains_private(isolated_store):
    store.init_db()
    defaults.initialize()
    owners = (store.uid(), store.uid())
    with store.connect() as db:
        for index, owner in enumerate(owners):
            db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (
                owner, f"legacy-{index}@example.com", store.password_hash(PASSWORD),
                store.dumps({"name": "旧版用户", "role": "user", "control_level": "observe"}), store.now(),
            ))
    for owner in owners:
        assert presets.install_user_presets(owner)["knowledge"] == len(presets.PRESETS)
    modified_owner, untouched_owner = owners
    with store.connect() as db:
        template_id = db.execute("SELECT template_id FROM template_documents ORDER BY length(content) DESC,id LIMIT 1").fetchone()[0]
    source = defaults.get_template("knowledge", template_id)
    legacy = {
        owner: next(item for item in store.list_entities(owner, "knowledge") if item["builtin_key"] == source["builtin_key"])
        for owner in owners
    }
    with store.connect() as db:
        source_document = dict(db.execute(
            "SELECT name,content FROM template_documents WHERE template_id=? ORDER BY length(content) DESC LIMIT 1", (source["id"],),
        ).fetchone())
        document = dict(db.execute("SELECT * FROM documents WHERE owner=? AND knowledge_id=? AND name=?", (
            modified_owner, legacy[modified_owner]["id"], source_document["name"],
        )).fetchone())
        chunks = db.execute("SELECT id,content FROM chunks WHERE owner=? AND document_id=? ORDER BY rowid", (
            modified_owner, document["id"],
        )).fetchall()
    original = source_document["content"]
    assert len(chunks) > 1
    position = next(index for index, char in enumerate(original) if index >= 1400 and "\u4e00" <= char <= "\u9fff")
    modified = original[:position] + ("甲" if original[position] != "甲" else "乙") + original[position + 1:]
    assert len(modified.encode()) == len(original.encode()) == document["size"]
    assert sum(first != second for first, second in zip(original, modified)) == 1
    updated_chunks = [modified[index:index + 1400] for index in range(0, len(modified), 1150)]
    assert len(updated_chunks) == len(chunks)
    with store.connect() as db:
        db.executemany("UPDATE chunks SET content=? WHERE id=?", [
            (content, chunk["id"]) for chunk, content in zip(chunks, updated_chunks)
        ])
        old_entity = tuple(db.execute("SELECT * FROM entities WHERE id=?", (legacy[modified_owner]["id"],)).fetchone())
        old_documents = [tuple(row) for row in db.execute("SELECT * FROM documents WHERE owner=? AND knowledge_id=? ORDER BY id", (
            modified_owner, legacy[modified_owner]["id"],
        ))]
        old_chunks = [tuple(row) for row in db.execute("SELECT * FROM chunks WHERE owner=? AND knowledge_id=? ORDER BY rowid", (
            modified_owner, legacy[modified_owner]["id"],
        ))]
    with TestClient(main.app) as client:
        _login(client, "legacy-0@example.com")
        private = next(item for item in _ok(client.get("/api/knowledge")) if item["id"] == legacy[modified_owner]["id"])
        assert private["name"] == source["name"] and private["read_only"] is False and not private.get("default_template_id")
        assert _ok(client.get(f"/api/knowledge/{private['id']}/documents/{document['id']}")) == {
            "id": document["id"], "name": source_document["name"], "text": modified,
        }
        default_copy = _copies(client, "knowledge")[source["id"]]
        assert default_copy["id"] != private["id"] and default_copy["read_only"] is False
        documents = _ok(client.get(f"/api/knowledge/{default_copy['id']}/documents"))
        default_document = next(item for item in documents if item["name"] == source_document["name"])
        assert _ok(client.get(f"/api/knowledge/{default_copy['id']}/documents/{default_document['id']}"))["text"] == original
        assert len(_ok(client.get("/api/knowledge"))) == len(presets.PRESETS) + 1
        admin_catalog.install()
        defaults.sync_all()
        with store.connect() as db:
            assert tuple(db.execute("SELECT * FROM entities WHERE id=?", (private["id"],)).fetchone()) == old_entity
            assert [tuple(row) for row in db.execute("SELECT * FROM documents WHERE owner=? AND knowledge_id=? ORDER BY id", (
                modified_owner, private["id"],
            ))] == old_documents
            assert [tuple(row) for row in db.execute("SELECT * FROM chunks WHERE owner=? AND knowledge_id=? ORDER BY rowid", (
                modified_owner, private["id"],
            ))] == old_chunks
        assert _ok(client.patch(f"/api/knowledge/{private['id']}", json={"description": "仍可编辑的私人知识"}))["read_only"] is False
        _login(client, "legacy-1@example.com")
        adopted = _copies(client, "knowledge")[source["id"]]
        assert adopted["id"] == legacy[untouched_owner]["id"] and adopted["read_only"] is False
        assert len(_ok(client.get("/api/knowledge"))) == len(presets.PRESETS)
