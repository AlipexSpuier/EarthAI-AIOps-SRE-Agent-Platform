import asyncio
import copy
import sqlite3
from collections import defaultdict, deque
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import defaults, engine, main, store, tools


KINDS = ("agents", "skills", "knowledge", "projects", "servers", "providers", "schedules", "alerts")
PASSWORD = "Import-user-password-2026!"
ADMIN_PASSWORD = "Import-admin-password-2026!"
REAL_PROVIDER_MODELS = engine.provider_models
ASYNC_CLIENT = httpx.AsyncClient
REFERENCE_FIELDS = (
    ("agents", "provider_id", "providers"),
    ("agents", "skill_ids", "skills"),
    ("agents", "knowledge_ids", "knowledge"),
    ("projects", "server_ids", "servers"),
    ("projects", "skill_ids", "skills"),
    ("projects", "knowledge_ids", "knowledge"),
    ("schedules", "server_id", "servers"),
    ("schedules", "provider_id", "providers"),
    ("schedules", "agent_id", "agents"),
    ("alerts", "server_id", "servers"),
)


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    data = tmp_path / "data"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(store, "DATA_ROOT", data)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "user-import.db")
    monkeypatch.setenv("EARTHAI_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EARTHAI_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("EARTHAI_COOKIE_SECURE", "false")
    monkeypatch.setenv("EARTHAI_SQLITE_JOURNAL_MODE", "DELETE")
    monkeypatch.delenv("EARTHAI_STATE_DIR", raising=False)
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})

    async def idle_scheduler():
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "scheduler_loop", idle_scheduler)
    catalog = AsyncMock(return_value=["remote-first", "remote-second"])
    monkeypatch.setattr(engine, "provider_models", catalog)
    blocked_http = Mock(side_effect=AssertionError("unexpected outbound HTTP request"))

    def local_http_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(blocked_http)
        return ASYNC_CLIENT(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", local_http_client)
    blocked = (
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected model request"))),
        (engine, "trigger_schedule", Mock(side_effect=AssertionError("unexpected scheduled execution"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure execution"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected server connection"))),
    )
    for module, name, replacement in blocked:
        monkeypatch.setattr(module, name, replacement)
    yield catalog
    blocked_http.assert_not_called()
    for _, name, replacement in blocked:
        assert replacement.call_count == 0, name


@pytest.fixture
def client(isolated_store):
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def marker():
    return "user-import-" + uuid4().hex


@pytest.fixture
def owner(client):
    return _register(client)


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _register(client):
    client.cookies.clear()
    return _ok(client.post("/api/auth/register", json={
        "email": uuid4().hex + "@example.test", "password": PASSWORD, "name": "个人导入测试",
    }))


def _administrator(client):
    client.cookies.clear()
    user = _ok(client.post("/api/auth/login", json={"email": "admin", "password": "admin"}))
    _ok(client.post("/api/auth/password", json={"current_password": "admin", "new_password": ADMIN_PASSWORD}))
    return user


def _session(client, token):
    client.cookies.clear()
    client.cookies.set("earthai_session", token)


def _body(kind, name, **changes):
    bodies = {
        "agents": {"name": name, "system_prompt": "只读收集证据，不执行基础设施操作。"},
        "skills": {"name": name, "content": "先读取证据，再记录风险和需要审批的步骤。"},
        "knowledge": {"name": name, "description": "个人导入的知识库"},
        "projects": {"name": name, "description": "个人导入的项目"},
        "servers": {"name": name, "host": "192.0.2.20", "password": "import-ssh-" + uuid4().hex},
        "providers": {
            "name": name, "base_url": "https://models.example.test/v1", "api_key": "import-api-" + uuid4().hex,
            "models": ["manual-model"], "default_model": "manual-model",
        },
        "schedules": {
            "name": name, "prompt": "只读检查并报告证据", "cron": "0 9 1 1 *", "timezone": "UTC", "enabled": False,
        },
        "alerts": {"title": name, "description": "手工导入的告警", "severity": "warning"},
    }
    return {**bodies[kind], **changes}


def _create(client, kind, name, **changes):
    return _ok(client.post(f"/api/{kind}", json=_body(kind, name, **changes)))


def _import(client, kind, items):
    return client.post(f"/api/{kind}/import", json={"items": items})


def _snapshot():
    with store.connect() as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
        )]
        return {
            table: sorted((tuple(row) for row in db.execute('SELECT * FROM "' + table.replace('"', '""') + '"')), key=repr)
            for table in tables
        }


def _user_data(owner):
    with store.connect() as db:
        return store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()[0])


def _change_user(owner, **changes):
    with store.connect() as db:
        data = store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()[0])
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps({**data, **changes}), owner))


def _new_entities(before, after):
    old_ids = {row[0] for row in before["entities"]}
    return [row for row in after["entities"] if row[0] not in old_ids]


def _assert_old_entities_unchanged(before, after):
    rows = {row[0]: row for row in after["entities"]}
    assert all(rows.get(row[0]) == row for row in before["entities"])


def _after_validation(monkeypatch, mutation):
    original = main.prepare_entity
    calls = 0
    expected = {}

    def prepare(*args, **kwargs):
        nonlocal calls
        value = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            mutation()
            expected.update(_snapshot())
        return value

    monkeypatch.setattr(main, "prepare_entity", prepare)
    return expected


def _install_catalog(monkeypatch, handler):
    calls = Mock(side_effect=handler)

    def local_http_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(calls)
        return ASYNC_CLIENT(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", local_http_client)
    monkeypatch.setattr(engine, "provider_models", REAL_PROVIDER_MODELS)
    return calls


def _trace_sql(monkeypatch):
    statements = []
    original = store.connect

    @contextmanager
    def connect():
        with original() as db:
            db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr(store, "connect", connect)
    return statements


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_imports_new_private_rows_without_overwriting_exported_ids(client, owner, marker, isolated_store, kind):
    existing = _create(client, kind, marker)
    before = _snapshot()
    items = [_body(kind, marker), _body(kind, marker + "-second")]
    for item in items:
        item.update(id=existing["id"], owner="foreign-owner", owner_id="foreign-owner",
                    created_at="2000-01-01T00:00:00Z", updated_at="2000-01-01T00:00:00Z")
    isolated_store.reset_mock()
    assert _ok(_import(client, kind, items)) == {"ok": True, "count": 2}
    after = _snapshot()
    added = _new_entities(before, after)
    assert len(added) == 2 and len({row[0] for row in added}) == 2
    assert all(row[1] == owner["id"] and row[2] == kind for row in added)
    assert existing["id"] not in {row[0] for row in added}
    for row in added:
        UUID(row[0])
        value = store.get_entity(owner["id"], kind, row[0])
        assert value is not None
        assert value["created_at"] != items[0]["created_at"]
        assert not value.get("default_template_id")
        assert main.public_entity(kind, value)["read_only"] is False
    _assert_old_entities_unchanged(before, after)
    assert {table: rows for table, rows in after.items() if table not in {"entities", "audit"}} == {
        table: rows for table, rows in before.items() if table not in {"entities", "audit"}
    }
    previous_audit = {row[0] for row in before["audit"]}
    imports = [row for row in after["audit"] if row[0] not in previous_audit and row[2] == kind + ".import"]
    assert len(imports) == 1 and imports[0][1] == owner["id"]
    assert isolated_store.await_count == (2 if kind == "providers" else 0)


@pytest.mark.parametrize("kind", KINDS)
def test_invalid_second_item_leaves_every_table_unchanged(client, owner, marker, isolated_store, kind):
    before = _snapshot()
    assert _import(client, kind, [_body(kind, marker), _body(kind, "")]).status_code == 422
    assert _snapshot() == before
    isolated_store.assert_not_awaited()


@pytest.mark.parametrize("kind", (
    "conversations", "files", "docs", "documents", "users", "runs", "approvals", "messages", "audit", "events", "settings", "unknown",
))
def test_unsupported_kinds_cannot_import(client, owner, marker, isolated_store, kind):
    before = _snapshot()
    response = _import(client, kind, [_body("skills", marker)])
    assert response.status_code == (422 if kind == "approvals" else 404), response.text
    assert _snapshot() == before
    isolated_store.assert_not_awaited()


@pytest.mark.parametrize("case", (
    "missing-items", "null-body", "list-body", "string-body", "number-body", "boolean-body", "extra-field",
    "null-items", "object-items", "string-items", "boolean-items", "empty-items", "too-many-items",
    "null-item", "string-item", "number-item", "boolean-item", "list-item",
))
def test_invalid_envelopes_are_atomic(client, owner, marker, isolated_store, case):
    item = _body("skills", marker)
    bodies = {
        "missing-items": {}, "null-body": None, "list-body": [item], "string-body": "skills", "number-body": 1,
        "boolean-body": False, "extra-field": {"items": [item], "owner": owner["id"]},
        "null-items": {"items": None}, "object-items": {"items": item}, "string-items": {"items": "skills"},
        "boolean-items": {"items": True}, "empty-items": {"items": []}, "too-many-items": {"items": [item] * 201},
        "null-item": {"items": [item, None]}, "string-item": {"items": [item, "text"]},
        "number-item": {"items": [item, 1]}, "boolean-item": {"items": [item, False]}, "list-item": {"items": [item, []]},
    }
    before = _snapshot()
    response = client.post("/api/skills/import", content=store.dumps(bodies[case]), headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    assert _snapshot() == before
    isolated_store.assert_not_awaited()


def test_malformed_json_is_rejected_without_writes(client, owner, isolated_store):
    before = _snapshot()
    response = client.post("/api/skills/import", content='{"items":', headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    assert _snapshot() == before
    isolated_store.assert_not_awaited()


def test_maximum_two_hundred_items_are_accepted(client, owner, marker):
    before = _snapshot()
    items = [_body("skills", f"{marker}-{index}") for index in range(200)]
    assert _ok(_import(client, "skills", items)) == {"ok": True, "count": 200}
    after = _snapshot()
    added = _new_entities(before, after)
    assert len(added) == 200 and {store.loads(row[3])["name"] for row in added} == {item["name"] for item in items}
    _assert_old_entities_unchanged(before, after)


@pytest.mark.parametrize(("account", "status"), (
    ("anonymous", 401), ("administrator", 403), ("disabled", 403), ("must-change-password", 403),
))
def test_every_import_kind_rejects_restricted_accounts(client, marker, isolated_store, account, status):
    if account == "administrator":
        _administrator(client)
    elif account != "anonymous":
        user = _register(client)
        _change_user(user["id"], **{"disabled" if account == "disabled" else "must_change_password": True})
    before = _snapshot()
    for kind in KINDS:
        response = _import(client, kind, [_body(kind, marker)])
        assert response.status_code == status, (kind, response.text)
        assert _snapshot() == before
    isolated_store.assert_not_awaited()


@pytest.mark.parametrize("kind", ("agents", "schedules"))
@pytest.mark.parametrize("level", ("approve", "autonomous"))
def test_ungranted_higher_control_rejects_whole_batch(client, owner, marker, isolated_store, kind, level):
    before = _snapshot()
    items = [_body(kind, marker, control_level="observe"), _body(kind, marker + "-denied", control_level=level)]
    response = _import(client, kind, items)
    assert response.status_code == 403, response.text
    assert _snapshot() == before
    isolated_store.assert_not_awaited()


@pytest.mark.parametrize("kind", ("agents", "schedules"))
@pytest.mark.parametrize(("levels", "preferred", "expected"), (
    (["observe"], "observe", "observe"),
    (["observe", "approve"], "observe", "observe"),
    (["approve"], "approve", "approve"),
    (["observe", "autonomous"], "autonomous", "autonomous"),
    (["observe"], "approve", "observe"),
))
def test_omitted_control_uses_an_authorized_preference_not_implicit_approve(client, owner, marker, kind, levels, preferred, expected):
    _change_user(owner["id"], allowed_control_levels=levels, control_level=preferred)
    before = _snapshot()
    assert _ok(_import(client, kind, [_body(kind, marker)])) == {"ok": True, "count": 1}
    after = _snapshot()
    added = _new_entities(before, after)
    assert len(added) == 1 and store.loads(added[0][3])["control_level"] == expected
    assert after["users"] == before["users"]


@pytest.mark.parametrize("enabled", (None, False, True), ids=("omitted", "explicit-false", "explicit-true"))
def test_imported_schedules_default_disabled_and_explicit_enable_requires_granted_control(client, owner, marker, enabled):
    item = _body("schedules", marker)
    item.pop("enabled")
    if enabled is not None:
        item["enabled"] = enabled
    before = _snapshot()
    assert _ok(_import(client, "schedules", [item])) == {"ok": True, "count": 1}
    added = _new_entities(before, _snapshot())
    assert len(added) == 1 and store.loads(added[0][3])["enabled"] is (enabled is True)
    if enabled is True:
        before = _snapshot()
        response = _import(client, "schedules", [{**item, "name": marker + "-denied", "control_level": "approve"}])
        assert response.status_code == 403, response.text
        assert _snapshot() == before


@pytest.mark.parametrize("selected", (False, True), ids=("empty-preferences", "saved-preferences"))
def test_import_does_not_select_chat_resources_or_change_saved_preferences(client, owner, marker, selected):
    if selected:
        provider = _create(client, "providers", marker + "-chosen-provider")
        agent = _create(client, "agents", marker + "-chosen-agent")
        project = _create(client, "projects", marker + "-chosen-project")
        server = _create(client, "servers", marker + "-chosen-server")
        _ok(client.patch("/api/preferences/chat", json={
            "provider_id": provider["id"], "agent_id": agent["id"], "project_id": project["id"], "server_id": server["id"],
            "model": "custom-selected-model", "control_level": "observe",
        }))
    before = _user_data(owner["id"])
    assert before["chat_preferences"]["control_level"] == "observe"
    for kind in KINDS:
        assert _ok(_import(client, kind, [_body(kind, marker + "-" + kind)])) == {"ok": True, "count": 1}
        assert _user_data(owner["id"]) == before
    preferences = _ok(client.get("/api/preferences/chat"))
    assert preferences == before["chat_preferences"]


@pytest.mark.parametrize("source", ("other-owner", "template-id"))
def test_references_accept_only_current_owner_entity_ids(client, owner, marker, isolated_store, source):
    token = client.cookies.get("earthai_session")
    targets = {target for _, _, target in REFERENCE_FIELDS}
    if source == "other-owner":
        _register(client)
        linked = {kind: _create(client, kind, marker + "-foreign-" + kind) for kind in targets}
    else:
        _administrator(client)
        linked = {
            kind: _ok(client.post(f"/api/admin/defaults/{kind}", json=_body(kind, marker + "-template-" + kind)))
            for kind in targets
        }
    _session(client, token)
    isolated_store.reset_mock()
    before = _snapshot()
    for kind, field, target in REFERENCE_FIELDS:
        id_ = linked[target]["id"]
        value = [id_] if field.endswith("_ids") else id_
        items = [_body(kind, marker + "-valid"), _body(kind, marker + "-invalid", **{field: value})]
        response = _import(client, kind, items)
        assert response.status_code == 404, (kind, field, response.text)
        assert _snapshot() == before
    isolated_store.assert_not_awaited()


def test_existing_owned_scalar_and_project_skill_references_are_preserved(client, owner, marker):
    linked = {kind: _create(client, kind, marker + "-owned-" + kind) for kind in {target for _, _, target in REFERENCE_FIELDS}}
    for kind in ("agents", "projects", "schedules", "alerts"):
        changes = {
            field: [linked[target]["id"]] if field.endswith("_ids") else linked[target]["id"]
            for source, field, target in REFERENCE_FIELDS if source == kind
        }
        before = _snapshot()
        assert _ok(_import(client, kind, [_body(kind, marker + "-linked-" + kind, **changes)])) == {"ok": True, "count": 1}
        added = _new_entities(before, _snapshot())
        assert len(added) == 1
        saved = store.loads(added[0][3])
        assert all(saved[field] == value for field, value in changes.items())


def test_default_read_only_copies_are_referenceable_but_agent_control_still_requires_grants(client, owner, marker):
    token = client.cookies.get("earthai_session")
    _administrator(client)
    templates = {
        kind: _ok(client.post(f"/api/admin/defaults/{kind}", json=_body(kind, marker + "-default-" + kind)))
        for kind in ("providers", "servers", "skills", "knowledge")
    }
    higher = _ok(client.post("/api/admin/defaults/agents", json=_body("agents", marker + "-approve", control_level="approve")))
    _session(client, token)
    copies = {
        kind: next(item for item in _ok(client.get(f"/api/{kind}")) if item.get("default_template_id") == template["id"])
        for kind, template in templates.items()
    }
    assert copies["providers"]["read_only"] and copies["servers"]["read_only"]
    agent = next(item for item in _ok(client.get("/api/agents")) if item.get("default_template_id") == higher["id"])
    items = {
        "agents": _body("agents", marker + "-uses-default", provider_id=copies["providers"]["id"],
                        skill_ids=[copies["skills"]["id"]], knowledge_ids=[copies["knowledge"]["id"]]),
        "projects": _body("projects", marker + "-uses-default", server_ids=[copies["servers"]["id"]],
                          skill_ids=[copies["skills"]["id"]], knowledge_ids=[copies["knowledge"]["id"]]),
        "schedules": _body("schedules", marker + "-uses-default", server_id=copies["servers"]["id"],
                           provider_id=copies["providers"]["id"]),
        "alerts": _body("alerts", marker + "-uses-default", server_id=copies["servers"]["id"]),
    }
    for kind, item in items.items():
        assert _ok(_import(client, kind, [item])) == {"ok": True, "count": 1}
    before = _snapshot()
    item = _body("schedules", marker + "-higher-agent", control_level="observe", agent_id=agent["id"])
    assert _import(client, "schedules", [item]).status_code == 403
    assert _snapshot() == before
    _change_user(owner["id"], allowed_control_levels=["observe", "approve"])
    assert _ok(_import(client, "schedules", [item])) == {"ok": True, "count": 1}


@pytest.mark.parametrize(("kind", "field"), (("agents", "skill_ids"), ("projects", "skill_ids"), ("schedules", "agent_id")))
def test_exported_ids_are_not_resolved_to_other_items_in_the_batch(client, owner, marker, kind, field):
    exported_id = str(uuid4())
    value = [exported_id] if field.endswith("_ids") else exported_id
    before = _snapshot()
    response = _import(client, kind, [
        _body(kind, marker + "-first", id=exported_id), _body(kind, marker + "-second", **{field: value}),
    ])
    assert response.status_code == 404, response.text
    assert _snapshot() == before


@pytest.mark.parametrize("kind", KINDS)
def test_exported_default_and_internal_metadata_cannot_turn_imports_into_defaults(client, owner, marker, kind):
    metadata = {
        "id": str(uuid4()), "owner": "foreign-owner", "owner_id": "foreign-owner", "read_only": True,
        "default_template_id": "forged-template", "default_revision": "forged-revision", "default_references_disabled": True,
        "builtin_key": "forged-builtin", "builtin_domain": "forged-domain", "builtin_version": "forged-version",
        "personal_override": True, "sort_order": -999999, "created_at": "2000-01-01T00:00:00Z",
        "updated_at": "2000-01-01T00:00:00Z", "storage_name": "private-storage", "has_api_key": False,
        "has_credentials": False, "document_count": 999, "chunk_count": 999, "usage_count": 999,
        "last_checked_at": "forged-check", "fingerprint_trusted_at": "forged-trust", "next_run_at": "forged-next",
        "last_run_at": "forged-last", "last_run_id": "forged-run", "model_sync": {"status": "forged"},
        "unknown_metadata": {"nested": "must-not-be-persisted"},
    }
    item = _body(kind, marker, **metadata)
    if kind == "servers":
        item["status"] = "online"
    before = _snapshot()
    assert _ok(_import(client, kind, [item])) == {"ok": True, "count": 1}
    added = _new_entities(before, _snapshot())
    assert len(added) == 1
    saved = store.loads(added[0][3])
    derived = {"sort_order", "next_run_at", "model_sync"}
    assert not (set(metadata) - derived) & saved.keys()
    assert not any(key.startswith("builtin_") or key.startswith("default_") and key != "default_model" for key in saved)
    if kind == "agents":
        assert type(saved["sort_order"]) is int and saved["sort_order"] >= 0
    if kind == "servers":
        assert saved["status"] == "unknown" and "last_checked_at" not in saved
    if kind == "schedules":
        assert saved["next_run_at"] != metadata["next_run_at"] and saved["enabled"] is False
    if kind == "providers":
        assert saved["model_sync"]["status"] == "ok"
    defaults.sync_user(owner["id"])
    value = store.get_entity(owner["id"], kind, added[0][0])
    assert value is not None and main.public_entity(kind, value)["read_only"] is False
    assert not value.get("default_template_id")


@pytest.mark.parametrize("kind", ("providers", "servers"))
def test_credentials_are_encrypted_at_rest_and_absent_from_import_responses_and_audit(client, owner, marker, kind):
    secrets = {field: "import-secret-" + uuid4().hex for field in main.SECRET_FIELDS[kind]}
    before = _snapshot()
    response = _import(client, kind, [_body(kind, marker, **secrets)])
    assert _ok(response) == {"ok": True, "count": 1}
    after = _snapshot()
    added = _new_entities(before, after)
    assert len(added) == 1
    saved = store.loads(added[0][3])
    public = client.get(f"/api/{kind}")
    public_value = next(item for item in _ok(public) if item["id"] == added[0][0])
    for field, secret in secrets.items():
        assert saved[field] != secret and store.unseal(saved[field]) == secret
        assert secret not in response.text and secret not in public.text
        assert secret not in repr(after)
        assert field not in public_value
    assert public_value["has_api_key" if kind == "providers" else "has_credentials"] is True


@pytest.mark.parametrize("kind", KINDS)
def test_sql_abort_on_second_insert_rolls_back_resources_order_and_audit(client, owner, marker, isolated_store, kind):
    first, second = marker + "-first", marker + "-second"
    field = "title" if kind == "alerts" else "name"
    with store.connect() as db:
        db.execute(f"""CREATE TRIGGER reject_second_import BEFORE INSERT ON entities
            WHEN NEW.owner='{owner['id']}' AND NEW.kind='{kind}' AND json_extract(NEW.data,'$.{field}')='{second}'
            BEGIN SELECT RAISE(ABORT,'forced second import insert failure'); END""")
    before = _snapshot()
    response = _import(client, kind, [_body(kind, first), _body(kind, second)])
    assert response.status_code == 500, response.text
    assert _snapshot() == before
    isolated_store.assert_not_awaited()
    with store.connect() as db:
        db.execute("DROP TRIGGER reject_second_import")
    assert _ok(_import(client, kind, [_body(kind, first), _body(kind, second)])) == {"ok": True, "count": 2}


@pytest.mark.parametrize("kind", ("agents", "providers"))
def test_audit_failure_rolls_back_the_entire_import(client, owner, marker, isolated_store, kind):
    with store.connect() as db:
        db.execute(f"""CREATE TRIGGER reject_import_audit BEFORE INSERT ON audit
            WHEN NEW.owner='{owner['id']}' AND NEW.action='{kind}.import'
            BEGIN SELECT RAISE(ABORT,'forced import audit failure'); END""")
    before = _snapshot()
    response = _import(client, kind, [_body(kind, marker + "-first"), _body(kind, marker + "-second")])
    assert response.status_code == 500, response.text
    assert _snapshot() == before
    isolated_store.assert_not_awaited()


@pytest.mark.parametrize(("change", "status"), (
    ({"disabled": True}, 403), ({"must_change_password": True}, 403), ({"role": "admin"}, 403),
    ({"allowed_control_levels": ["approve"]}, 403), (None, 401),
))
def test_user_and_grants_are_rechecked_after_validation(client, owner, marker, monkeypatch, isolated_store, change, status):
    def mutate():
        if change is None:
            with store.connect() as db:
                db.execute("DELETE FROM users WHERE id=?", (owner["id"],))
        else:
            _change_user(owner["id"], **change)

    expected = _after_validation(monkeypatch, mutate)
    response = _import(client, "agents", [_body("agents", marker + "-first"), _body("agents", marker + "-second")])
    assert expected
    assert response.status_code == status, response.text
    assert _snapshot() == expected
    isolated_store.assert_not_awaited()


@pytest.mark.parametrize(("kind", "field", "target", "change", "status"), (
    ("projects", "skill_ids", "skills", "deleted", 404),
    ("agents", "provider_id", "providers", "other-owner", 404),
    ("schedules", "agent_id", "agents", "higher-control", 403),
    ("schedules", "agent_id", "agents", "remote-agent", 422),
    ("alerts", "server_id", "servers", "deleted", 404),
))
def test_reference_ownership_and_agent_control_are_rechecked_after_validation(
    client, owner, marker, monkeypatch, isolated_store, kind, field, target, change, status,
):
    token = client.cookies.get("earthai_session")
    other = _register(client)
    _session(client, token)
    linked = _create(client, target, marker + "-reference")
    isolated_store.reset_mock()

    def mutate():
        with store.connect() as db:
            if change == "deleted":
                db.execute("DELETE FROM entities WHERE id=?", (linked["id"],))
            elif change == "other-owner":
                db.execute("UPDATE entities SET owner=? WHERE id=?", (other["id"], linked["id"]))
            else:
                data = store.loads(db.execute("SELECT data FROM entities WHERE id=?", (linked["id"],)).fetchone()[0])
                data.update({"control_level": "autonomous"} if change == "higher-control" else {
                    "kind": "remote", "url": "https://agents.example.test/remote",
                })
                db.execute("UPDATE entities SET data=? WHERE id=?", (store.dumps(data), linked["id"]))

    expected = _after_validation(monkeypatch, mutate)
    value = [linked["id"]] if field.endswith("_ids") else linked["id"]
    response = _import(client, kind, [
        _body(kind, marker + "-first", **{field: value}), _body(kind, marker + "-second", **{field: value}),
    ])
    assert expected
    assert response.status_code == status, response.text
    assert _snapshot() == expected
    isolated_store.assert_not_awaited()


@pytest.mark.parametrize("concurrent", (False, True), ids=("existing-order", "concurrent-append"))
def test_agent_import_appends_in_input_order_without_rewriting_personal_order(client, owner, marker, monkeypatch, concurrent):
    _create(client, "agents", marker + "-existing-one")
    _create(client, "agents", marker + "-existing-two")
    ids = [item["id"] for item in _ok(client.get("/api/agents"))]
    personal = list(reversed(ids))
    _ok(client.post("/api/agents/reorder", json={"agent_ids": personal}))
    before = _snapshot()
    maximum = max(item.get("sort_order", -1) for item in store.list_entities(owner["id"], "agents"))
    concurrent_id = []
    expected = {}
    if concurrent:
        maximum += 1000

        def mutate():
            value = store.save_entity(owner["id"], "agents", {
                **copy.deepcopy(main.DEFAULTS["agents"]), "name": marker + "-concurrent", "control_level": "observe", "sort_order": maximum,
            })
            concurrent_id.append(value["id"])

        expected = _after_validation(monkeypatch, mutate)
    names = [marker + "-z-first", marker + "-a-second"]
    items = [_body("agents", name, sort_order=-999999) for name in names]
    assert _ok(_import(client, "agents", items)) == {"ok": True, "count": 2}
    if concurrent:
        assert expected and len(concurrent_id) == 1
        before = expected
    after = _snapshot()
    added = {store.loads(row[3])["name"]: row for row in _new_entities(before, after)}
    assert set(added) == set(names)
    assert [store.loads(added[name][3])["sort_order"] for name in names] == [maximum + 1, maximum + 2]
    assert after["agent_orders"] == before["agent_orders"]
    _assert_old_entities_unchanged(before, after)
    assert [item["id"] for item in _ok(client.get("/api/agents"))] == [*personal, *concurrent_id, *[added[name][0] for name in names]]


def test_invalid_agent_batch_does_not_repair_or_normalize_legacy_ranks(client, owner, marker):
    legacy = store.save_entity(owner["id"], "agents", {"name": marker + "-legacy", "control_level": "observe"})
    assert "sort_order" not in legacy
    before = _snapshot()
    assert _import(client, "agents", [_body("agents", marker + "-first"), _body("agents", "")]).status_code == 422
    assert _snapshot() == before


def test_valid_provider_batch_commits_before_exactly_one_models_get_per_provider(client, owner, marker, monkeypatch):
    items = [_body("providers", marker + suffix, base_url=f"https://models-{index}.example.test/v1")
             for index, suffix in enumerate(("-one", "-two"))]
    by_host = {f"models-{index}.example.test": item for index, item in enumerate(items)}

    def handler(request):
        assert request.method == "GET" and request.url.path == "/v1/models"
        item = by_host[request.url.host]
        assert request.headers["authorization"] == "Bearer " + item["api_key"]
        with sqlite3.connect(store.DB_PATH) as db:
            rows = db.execute("SELECT data FROM entities WHERE owner=? AND kind='providers'", (owner["id"],)).fetchall()
            assert {store.loads(row[0])["name"] for row in rows} >= {item["name"] for item in items}
            assert db.execute("SELECT count(*) FROM audit WHERE owner=? AND action='providers.import'", (owner["id"],)).fetchone()[0] == 1
        return httpx.Response(200, json={"data": [{"id": "remote-first"}, {"id": "remote-second"}, {"id": "remote-first"}]})

    calls = _install_catalog(monkeypatch, handler)
    before = _snapshot()
    statements = _trace_sql(monkeypatch)
    response = _import(client, "providers", items)
    assert _ok(response) == {"ok": True, "count": 2}
    assert calls.call_count == 2
    assert {call.args[0].url.host for call in calls.call_args_list} == set(by_host)
    inserts = [sql for sql in statements if sql.lstrip().upper().startswith("INSERT INTO ENTITIES")]
    assert len(inserts) == 2
    after = _snapshot()
    added = _new_entities(before, after)
    assert len(added) == 2
    for row in added:
        saved = store.loads(row[3])
        assert saved["models"] == ["remote-first", "remote-second"] and saved["default_model"] == "remote-first"
        assert saved["model_sync"]["status"] == "ok"
        assert saved["api_key"] not in response.text
    _assert_old_entities_unchanged(before, after)
    assert all(item["api_key"] not in response.text for item in items)


@pytest.mark.parametrize("outcome", ("http-error", "timeout", "empty", "malformed"))
def test_provider_sync_failure_keeps_all_configurations_and_returns_safe_warnings(client, owner, marker, monkeypatch, outcome):
    items = [_body("providers", marker + suffix, base_url=f"https://models-{index}.example.test/v1")
             for index, suffix in enumerate(("-success", "-warning"))]
    leaked = items[1]["api_key"]

    def handler(request):
        assert request.method == "GET" and request.url.path == "/v1/models"
        if request.url.host == "models-0.example.test":
            return httpx.Response(200, json={"data": [{"id": "remote-first"}]})
        if outcome == "timeout":
            raise httpx.ReadTimeout("private failure " + leaked, request=request)
        if outcome == "http-error":
            return httpx.Response(401, json={"error": "private failure " + leaked})
        return httpx.Response(200, json={"data": []} if outcome == "empty" else {"error": leaked})

    calls = _install_catalog(monkeypatch, handler)
    before = _snapshot()
    statements = _trace_sql(monkeypatch)
    response = _import(client, "providers", items)
    result = _ok(response)
    assert set(result) == {"ok", "count", "warnings"} and result["ok"] is True and result["count"] == 2
    assert len(result["warnings"]) == 1 and isinstance(result["warnings"][0], str) and result["warnings"][0].strip()
    assert calls.call_count == 2
    assert len([sql for sql in statements if sql.lstrip().upper().startswith("INSERT INTO ENTITIES")]) == 2
    after = _snapshot()
    added = _new_entities(before, after)
    assert len(added) == 2
    saved = {store.loads(row[3])["name"]: store.loads(row[3]) for row in added}
    failed = saved[items[1]["name"]]
    assert failed["base_url"] == items[1]["base_url"]
    assert store.unseal(failed["api_key"]) == leaked
    assert failed["models"] == ["manual-model"] and failed["default_model"] == "manual-model"
    assert failed["model_sync"]["status"] == ("empty" if outcome == "empty" else "error")
    assert saved[items[0]["name"]]["default_model"] == "remote-first"
    _assert_old_entities_unchanged(before, after)
    public = client.get("/api/providers")
    _ok(public)
    for item in items:
        assert item["api_key"] not in response.text and item["api_key"] not in public.text
    assert "api_key" not in response.text and "private failure" not in response.text
