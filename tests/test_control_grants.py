import asyncio
import threading
from collections import defaultdict, deque
from itertools import combinations
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import access, admin, defaults, engine, main, progress, store, text_tools, tools, usage


PASSWORD = "Control-grants-test-password!"
ADMIN_PASSWORD = "Control-grants-admin-password!"
LEVELS = ("observe", "approve", "autonomous")
FINAL = {"role": "assistant", "content": "本地测试已结束。"}
TOOL_CALL = {"role": "assistant", "content": None, "tool_calls": [
    {"id": "local-files", "type": "function", "function": {"name": "list_files", "arguments": "{}"}},
]}
INVALID_GRANTS = [
    None, [], "observe", ("observe",), {"observe": True}, True, 1,
    ["Observe"], [" observe"], ["root"], ["observe", "observe"], ["observe", None], [False], [["observe"]],
]


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    data, state, uploads = tmp_path / "data", tmp_path / "state", tmp_path / "uploads"
    for path in (data, state, uploads):
        path.mkdir()
    for name, value in (("DATA_ROOT", data), ("DATA", state), ("UPLOADS", uploads), ("DB_PATH", state / "grants.db")):
        monkeypatch.setattr(store, name, value)
    monkeypatch.setattr(store, "_CONNECTIONS", {})
    monkeypatch.setattr(store, "_CONNECTION_LOCK", threading.Lock())
    monkeypatch.setattr(store, "_CONNECTION_LOCAL", threading.local())
    for name, value in {
        "EARTHAI_DATA_DIR": str(data), "EARTHAI_STATE_DIR": str(state), "EARTHAI_UPLOADS_DIR": str(uploads),
        "EARTHAI_MASTER_KEY": Fernet.generate_key().decode(), "EARTHAI_SQLITE_JOURNAL_MODE": "WAL",
        "EARTHAI_ALLOW_REGISTRATION": "true", "EARTHAI_COOKIE_SECURE": "false",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})
    blocked = [
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected paid model request"))),
        (text_tools, "complete", AsyncMock(side_effect=AssertionError("unexpected fallback model request"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure tool"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected infrastructure connection"))),
    ]
    for module, name, replacement in blocked:
        monkeypatch.setattr(module, name, replacement)
    store.init_db()
    defaults.init_tables()
    usage.initialize()
    try:
        yield
    finally:
        store.close_connections()
    for _, name, replacement in blocked:
        assert replacement.call_count == 0, name


@pytest.fixture
def client(isolated_store):
    # Deliberately omit lifespan: tests initialize their own schema and dispatch scheduler ticks explicitly.
    client = TestClient(main.app)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def administrator(client):
    admin.bootstrap_admin()
    _ok(client.post("/api/auth/login", json={"email": "admin", "password": "admin"}))
    user = _ok(client.post("/api/auth/password", json={
        "current_password": "admin", "new_password": ADMIN_PASSWORD,
    }))
    return {"user": user, "token": client.cookies.get("earthai_session")}


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _as(client, token):
    client.cookies.clear()
    client.cookies.set("earthai_session", token)


def _register(client, email="grants@example.test", **changes):
    return _ok(client.post("/api/auth/register", json={"email": email, "password": PASSWORD, **changes}))


def _managed(client, email="managed-grants", **changes):
    return _ok(client.post("/api/admin/users", json={
        "email": email, "password": PASSWORD, "name": email, **changes,
    }))


def _data(owner):
    with store.connect() as db:
        return store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()[0])


def _set_user(owner, **changes):
    with store.connect() as db:
        data = store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()[0])
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps({**data, **changes}), owner))


def _owner(grants=("observe",), *, legacy=False):
    owner = store.uid()
    data = {"name": "engine owner", "role": "user", "control_level": grants[0]}
    if not legacy:
        data["allowed_control_levels"] = list(grants)
    with store.connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (owner, owner + "@example.test", "unused", store.dumps(data), store.now()))
    return owner


def _snapshot():
    with store.connect() as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
        )]
        return {table: sorted((tuple(row) for row in db.execute(f'SELECT * FROM "{table}"')), key=repr) for table in tables}


def _owned_snapshot(owner):
    with store.connect() as db:
        result = {}
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
        )]
        for table in tables:
            columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
            field = "owner" if "owner" in columns else "user_id" if table == "sessions" else "id" if table == "users" else None
            if field:
                result[table] = [tuple(row) for row in db.execute(
                    f'SELECT * FROM "{table}" WHERE "{field}"=? ORDER BY rowid', (owner,),
                )]
        result["events"] = [tuple(row) for row in db.execute(
            "SELECT * FROM events WHERE run_id IN (SELECT id FROM runs WHERE owner=?) ORDER BY id", (owner,),
        )]
    return result


def _body(kind, **changes):
    bodies = {
        "agents": {"name": "local agent", "kind": "local", "system_prompt": "报告只读证据"},
        "schedules": {"name": "local schedule", "prompt": "概述已有资料", "cron": "0 9 * * *", "timezone": "UTC", "enabled": False},
        "conversations": {"title": "local conversation"},
        "servers": {"name": "server", "host": "192.0.2.44", "password": "local-test-only"},
        "providers": {"name": "provider", "base_url": "https://model.example.invalid/v1", "api_key": "local-test-only",
                      "models": ["local-model"], "default_model": "local-model"},
        "skills": {"name": "skill", "content": "先收集证据"},
        "knowledge": {"name": "knowledge", "description": "私人资料"},
        "projects": {"name": "project"},
        "alerts": {"title": "alert", "description": "本地测试"},
    }
    return {**bodies[kind], **changes}


def _conversation(owner, level="observe", **changes):
    return store.save_entity(owner, "conversations", _body("conversations", control_level=level, **changes))


def _run(owner, level="observe", status="running", conversation=None, **changes):
    conversation = conversation or _conversation(owner, level)
    id_, stamp = store.uid(), store.now()
    data = {"goal": "概述已有资料", "control_level": level, "model": "local-model", "step_count": 0, **changes}
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (
            id_, owner, conversation["id"], status, store.dumps(data), stamp, stamp,
        ))
    return store.get_run(owner, id_)


def _approval(owner, run):
    id_ = store.uid()
    with store.connect() as db:
        db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?)", (
            id_, owner, run["id"], "ssh_exec", store.dumps({"command": "systemctl restart app"}), "write", "pending", store.now(),
        ))
    return id_


@pytest.mark.parametrize("levels", [list(values) for size in range(1, 4) for values in combinations(LEVELS, size)])
def test_grants_are_exact_subsets_not_a_hierarchy(levels):
    raw = list(reversed(levels))
    user = {"role": "user", "allowed_control_levels": raw}
    assert access.validate_grants(raw) == levels
    assert access.allowed_levels(user) == levels
    assert user["allowed_control_levels"] == raw
    for level in LEVELS:
        if level in levels:
            assert access.require_control(user, level) is user
        else:
            with pytest.raises(HTTPException) as rejected:
                access.require_control(user, level)
            assert rejected.value.status_code == 403
    assert access.preferred_control(user, "autonomous") == (
        "autonomous" if "autonomous" in levels else "observe" if "observe" in levels else levels[0]
    )


@pytest.mark.parametrize("value", INVALID_GRANTS)
def test_invalid_explicit_grants_fail_closed_instead_of_becoming_legacy(value):
    with pytest.raises(ValueError):
        access.validate_grants(value)
    user = {"allowed_control_levels": value}
    assert access.allowed_levels(user) == []
    with pytest.raises(HTTPException) as rejected:
        access.preferred_control(user)
    assert rejected.value.status_code == 403
    with pytest.raises(HTTPException) as rejected:
        access.require_control(user, "observe")
    assert rejected.value.status_code == 403


def test_new_registration_ignores_injected_grants_and_starts_observe(client):
    user = _register(client, allowed_control_levels=list(LEVELS), control_level="autonomous")
    assert user["allowed_control_levels"] == ["observe"]
    assert user["control_level"] == user["chat_preferences"]["control_level"] == "observe"
    assert _data(user["id"])["allowed_control_levels"] == ["observe"]
    assert _ok(client.get("/api/auth/me"))["allowed_control_levels"] == ["observe"]
    _ok(client.post("/api/auth/logout"))
    logged_in = _ok(client.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}))
    assert logged_in["allowed_control_levels"] == ["observe"]
    assert _ok(client.get("/api/preferences/chat"))["control_level"] == "observe"


@pytest.mark.parametrize(("changes", "expected", "level"), [
    ({}, ["observe"], "observe"),
    ({"allowed_control_levels": ["autonomous"]}, ["autonomous"], "autonomous"),
    ({"allowed_control_levels": ["autonomous", "observe"]}, ["observe", "autonomous"], "observe"),
])
def test_admin_created_accounts_default_safely_or_use_explicit_exact_grants(client, administrator, changes, expected, level):
    user = _managed(client, **changes)
    assert user["allowed_control_levels"] == expected
    assert user["control_level"] == level
    assert _data(user["id"])["allowed_control_levels"] == expected
    logged_in = _ok(client.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}))
    assert logged_in["allowed_control_levels"] == expected
    assert _ok(client.get("/api/preferences/chat"))["control_level"] == level
    assert administrator["user"]["allowed_control_levels"] == ["observe"]


def test_legacy_missing_grant_field_remains_compatible_without_backfilling_all_modes(client):
    user = _register(client)
    with store.connect() as db:
        data = _data(user["id"])
        data.pop("allowed_control_levels")
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(data), user["id"]))
    assert access.allowed_levels(data) == list(LEVELS)
    assert _ok(client.get("/api/auth/me"))["allowed_control_levels"] == list(LEVELS)
    assert _ok(client.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}))["allowed_control_levels"] == list(LEVELS)
    for level in LEVELS:
        assert access.execution_allowed(user["id"], level) is None
    assert _ok(client.patch("/api/auth/me", json={"control_level": "autonomous"}))["control_level"] == "autonomous"
    assert _ok(client.patch("/api/preferences/chat", json={"control_level": "approve"}))["control_level"] == "approve"
    assert "allowed_control_levels" not in _data(user["id"])


def test_user_profile_cannot_self_grant_even_when_combined_with_level_change(client):
    user = _register(client)
    response = _ok(client.patch("/api/auth/me", json={"name": "合法改名", "allowed_control_levels": list(LEVELS)}))
    assert response["name"] == "合法改名" and response["allowed_control_levels"] == ["observe"]
    before = _snapshot()
    _ok(client.patch("/api/auth/me", json={
        "allowed_control_levels": list(LEVELS), "control_level": "autonomous", "theme": "light",
    }), 403)
    assert _snapshot() == before
    assert _data(user["id"])["allowed_control_levels"] == ["observe"]


def test_admin_single_and_batch_updates_normalize_grants_and_current_preferences(client, administrator):
    one = _managed(client, allowed_control_levels=list(LEVELS))
    two = _managed(client, "second-managed")
    _set_user(one["id"], control_level="autonomous", chat_preferences={**main.default_chat_preferences(one), "control_level": "autonomous"})
    changed = _ok(client.patch(f"/api/admin/users/{one['id']}", json={"allowed_control_levels": ["approve"]}))
    assert changed["allowed_control_levels"] == ["approve"]
    assert changed["control_level"] == changed["chat_preferences"]["control_level"] == "approve"
    assert _ok(client.post("/api/admin/users/batch", json={
        "ids": [one["id"], two["id"]], "action": "update", "changes": {"allowed_control_levels": ["autonomous", "observe"]},
    }))["count"] == 2
    users = {user["id"]: user for user in _ok(client.get("/api/admin/users"))}
    for user in (one, two):
        assert users[user["id"]]["allowed_control_levels"] == ["observe", "autonomous"]
        assert _data(user["id"])["control_level"] == "observe"
    assert _data(one["id"])["chat_preferences"]["control_level"] == "observe"


@pytest.mark.parametrize("grants", [[], None, "observe", ["observe", "observe"], ["Observe"], ["observe", "root"], [True]])
def test_admin_invalid_grants_reject_create_patch_and_whole_batch_without_writes(client, administrator, grants):
    one, two = _managed(client), _managed(client, "second-managed")
    waiting = _run(one["id"], status="waiting_approval")
    _approval(one["id"], waiting)
    before = _snapshot()
    for method, path, body in (
        ("POST", "/api/admin/users", {"email": "invalid-grants", "name": "invalid", "password": PASSWORD, "allowed_control_levels": grants}),
        ("PATCH", f"/api/admin/users/{one['id']}", {"name": "不应改名", "allowed_control_levels": grants}),
        ("POST", "/api/admin/users/batch", {"ids": [one["id"], two["id"]], "action": "update",
                                            "changes": {"name": "不应改名", "allowed_control_levels": grants}}),
    ):
        _ok(client.request(method, path, json=body), 422)
        assert _snapshot() == before


def test_invalid_batch_target_or_protected_account_never_partially_changes_grants(client, administrator):
    one, two = _managed(client), _managed(client, "second-managed")
    before = _snapshot()
    for ids, changes in (
        ([one["id"], "missing"], {"allowed_control_levels": ["approve"]}),
        ([one["id"], one["id"]], {"allowed_control_levels": ["approve"]}),
        ([one["id"], two["id"], administrator["user"]["id"]], {"allowed_control_levels": ["approve"], "role": "user"}),
    ):
        _ok(client.post("/api/admin/users/batch", json={"ids": ids, "action": "update", "changes": changes}), 422)
        assert _snapshot() == before


@pytest.mark.parametrize("level", ["approve", "autonomous"])
@pytest.mark.parametrize("surface", ["profile", "preferences", "agent-create", "agent-patch", "schedule-create", "schedule-patch",
                                     "conversation-create", "conversation-patch", "send-message"])
def test_ungranted_level_is_http_403_and_cannot_write(client, level, surface):
    _register(client)
    changes = {"control_level": level}
    if surface == "profile":
        method, path, body = "PATCH", "/api/auth/me", {**changes, "name": "不应改名"}
    elif surface == "preferences":
        method, path, body = "PATCH", "/api/preferences/chat", {**changes, "model": "must-not-save"}
    elif surface == "send-message":
        conversation = _ok(client.post("/api/conversations", json={}))
        method, path, body = "POST", f"/api/conversations/{conversation['id']}/messages", {**changes, "content": "不得执行"}
    else:
        kind, operation = surface.rsplit("-", 1)
        kind = {"agent": "agents", "schedule": "schedules", "conversation": "conversations"}[kind]
        if operation == "create":
            method, path, body = "POST", f"/api/{kind}", _body(kind, **changes)
        else:
            existing = _ok(client.post(f"/api/{kind}", json=_body(kind)))
            method, path, body = "PATCH", f"/api/{kind}/{existing['id']}", changes
    before = _snapshot()
    _ok(client.request(method, path, json=body), 403)
    assert _snapshot() == before
    assert engine.TASKS == {}


@pytest.mark.parametrize("kind", ["agents", "schedules", "conversations"])
def test_new_local_configuration_without_explicit_level_defaults_observe(client, kind):
    user = _register(client)
    created = _ok(client.post(f"/api/{kind}", json=_body(kind)))
    assert created["control_level"] == "observe"
    assert _data(user["id"])["allowed_control_levels"] == ["observe"]


@pytest.mark.parametrize("surface", ["preferences", "conversation-create", "conversation-patch", "send-message", "schedule-create", "schedule-patch"])
@pytest.mark.parametrize("level", ["approve", "autonomous"])
def test_linked_agent_own_mode_cannot_hide_inside_outer_observe(client, surface, level):
    user = _register(client)
    agent = store.save_entity(user["id"], "agents", _body("agents", control_level=level))
    body = {"agent_id": agent["id"], "control_level": "observe"}
    if surface == "preferences":
        method, path = "PATCH", "/api/preferences/chat"
    elif surface == "send-message":
        conversation = _ok(client.post("/api/conversations", json={}))
        method, path = "POST", f"/api/conversations/{conversation['id']}/messages"
        body["content"] = "不得执行"
    else:
        resource, operation = surface.rsplit("-", 1)
        kind = "conversations" if resource == "conversation" else "schedules"
        if operation == "create":
            method, path, body = "POST", f"/api/{kind}", _body(kind, **body)
        else:
            existing = _ok(client.post(f"/api/{kind}", json=_body(kind)))
            method, path = "PATCH", f"/api/{kind}/{existing['id']}"
    before = _snapshot()
    _ok(client.request(method, path, json=body), 403)
    assert _snapshot() == before


def test_higher_mode_default_cards_are_visible_but_backend_cannot_use_them(client):
    defaults.initialize()
    user = _register(client)
    cards = _ok(client.get("/api/agents"))
    restricted = next(card for card in cards if card["control_level"] == "approve" and card.get("default_template_id"))
    assert user["allowed_control_levels"] == ["observe"]
    history = _conversation(user["id"], agent_id=restricted["id"])
    before = _snapshot()
    for path, body in (
        ("/api/conversations", {"agent_id": restricted["id"], "control_level": "observe"}),
        (f"/api/conversations/{history['id']}/messages", {"content": "不得执行"}),
    ):
        _ok(client.post(path, json=body), 403)
        assert _snapshot() == before


@pytest.mark.parametrize("surface", ["conversation", "schedule"])
def test_historical_higher_mode_resources_remain_readable_but_cannot_run(client, surface):
    user = _register(client)
    conversation = _conversation(user["id"], "autonomous")
    run = _run(user["id"], "autonomous", status="completed", conversation=conversation)
    store.emit(run["id"], "done", {"status": "completed"})
    schedule = store.save_entity(user["id"], "schedules", _body("schedules", control_level="autonomous"))
    before = _snapshot()
    for path in ("/api/conversations", f"/api/conversations/{conversation['id']}", "/api/schedules", "/api/runs",
                 f"/api/runs/{run['id']}", f"/api/runs/{run['id']}/events"):
        assert client.get(path).status_code == 200
    assert _snapshot() == before
    path = f"/api/conversations/{conversation['id']}/messages" if surface == "conversation" else f"/api/schedules/{schedule['id']}/run"
    _ok(client.post(path, json={"content": "不得重放"} if surface == "conversation" else {}), 403)
    assert _snapshot() == before


def test_preferences_clear_revoked_mode_and_linked_agent_without_rewriting_history(client):
    user = _register(client)
    agent = store.save_entity(user["id"], "agents", _body("agents", control_level="approve"))
    historical = _conversation(user["id"], "approve", agent_id=agent["id"])
    saved = {**main.default_chat_preferences(user), "control_level": "approve", "agent_id": agent["id"]}
    _set_user(user["id"], control_level="approve", chat_preferences=saved)
    response = client.get("/api/preferences/chat")
    preferences = _ok(response)
    assert preferences["control_level"] == "observe" and preferences["agent_id"] is None
    assert {"control_level", "agent_id"} <= set(response.headers["X-EarthAI-Preferences-Cleared"].split(","))
    assert _data(user["id"])["chat_preferences"] == preferences
    assert store.get_entity(user["id"], "conversations", historical["id"]) == historical
    assert store.get_entity(user["id"], "agents", agent["id"]) == agent


@pytest.mark.parametrize("kind", ["servers", "providers", "skills", "knowledge", "projects", "alerts"])
def test_observe_grant_does_not_block_non_run_resource_crud(client, kind):
    user = _register(client)
    resource = _ok(client.post(f"/api/{kind}", json=_body(kind)))
    field = "title" if kind == "alerts" else "name"
    assert _ok(client.patch(f"/api/{kind}/{resource['id']}", json={field: "合法资源修订"}))[field] == "合法资源修订"
    assert any(item["id"] == resource["id"] for item in _ok(client.get(f"/api/{kind}")))
    _ok(client.delete(f"/api/{kind}/{resource['id']}"))
    assert store.get_entity(user["id"], kind, resource["id"]) is None
    assert _data(user["id"])["allowed_control_levels"] == ["observe"]


@pytest.mark.parametrize("grants", [["observe"], ["approve"]])
def test_remote_link_clicks_ignore_local_run_mode_and_only_record_a_click(client, grants):
    user = _register(client)
    _set_user(user["id"], allowed_control_levels=grants, control_level=grants[0])
    remote = store.save_entity(user["id"], "agents", {
        "name": "remote", "kind": "remote", "url": "https://agent.example.invalid/workspace", "control_level": "autonomous",
    })
    before = _snapshot()
    _ok(client.post(f"/api/agents/{remote['id']}/open"))
    after = _snapshot()
    assert len(after["remote_agent_clicks"]) == len(before["remote_agent_clicks"]) + 1
    assert {key: value for key, value in after.items() if key != "remote_agent_clicks"} == {
        key: value for key, value in before.items() if key != "remote_agent_clicks"
    }
    assert store.list_runs(user["id"]) == []


@pytest.mark.parametrize("kind", ["agents", "schedules"])
def test_json_import_checks_every_item_before_writing_and_allows_observe(client, kind):
    user = _register(client)
    before = _snapshot()
    _ok(client.post(f"/api/{kind}/import", json={"items": [
        _body(kind, name="first allowed", control_level="observe"), _body(kind, name="second forbidden", control_level="autonomous"),
    ]}), 403)
    assert _snapshot() == before
    imported = _ok(client.post(f"/api/{kind}/import", json={"items": [_body(kind, name="allowed one"), _body(kind, name="allowed two")]}))
    assert imported["count"] == 2
    resources = store.list_entities(user["id"], kind)
    assert len(resources) == 2 and all(item["control_level"] == "observe" for item in resources)
    if kind == "schedules":
        assert all(item["enabled"] is False for item in resources)


def test_schedule_json_import_also_checks_linked_agent_mode_atomically(client):
    user = _register(client)
    agent = store.save_entity(user["id"], "agents", _body("agents", control_level="approve"))
    before = _snapshot()
    _ok(client.post("/api/schedules/import", json={"items": [
        _body("schedules", name="allowed", control_level="observe"),
        _body("schedules", name="forbidden linked agent", control_level="observe", agent_id=agent["id"]),
    ]}), 403)
    assert _snapshot() == before


@pytest.mark.parametrize("kind", ["servers", "alerts"])
@pytest.mark.parametrize("has_observe", [True, False])
def test_diagnostics_are_fixed_observe_and_reject_missing_observe_before_writes(client, monkeypatch, kind, has_observe):
    user = _register(client)
    grants = ["observe", "autonomous"] if has_observe else ["autonomous"]
    _set_user(user["id"], allowed_control_levels=grants, control_level="autonomous")
    resource = _ok(client.post(f"/api/{kind}", json=_body(kind)))
    runner = AsyncMock(return_value=None)
    monkeypatch.setattr(engine, "run_agent", runner)
    before = _snapshot()
    response = client.post(f"/api/{kind}/{resource['id']}/diagnose")
    if not has_observe:
        _ok(response, 403)
        assert _snapshot() == before
        runner.assert_not_awaited()
    else:
        result = _ok(response)
        assert store.get_run(user["id"], result["run_id"])["control_level"] == "observe"
        assert store.get_entity(user["id"], "conversations", result["conversation_id"])["control_level"] == "observe"


@pytest.mark.parametrize("entrypoint", ["create_run", "trigger_schedule"])
@pytest.mark.parametrize("level", ["approve", "autonomous"])
def test_direct_engine_rejects_before_any_conversation_run_message_model_or_tool_write(monkeypatch, entrypoint, level):
    owner = _owner()
    values = {"id": "not-created", "name": "forbidden", "prompt": "不得执行", "control_level": level, "agent_id": "not-looked-up"}
    lookup = Mock(side_effect=AssertionError("outer mode must be checked before agent lookup"))
    monkeypatch.setattr(store, "get_entity", lookup)
    before = _snapshot()
    with pytest.raises(HTTPException) as rejected:
        if entrypoint == "create_run":
            engine.create_run(owner, values, "不得执行")
        else:
            engine.trigger_schedule(owner, values)
    assert rejected.value.status_code == 403
    lookup.assert_not_called()
    assert _snapshot() == before and engine.TASKS == {}


@pytest.mark.parametrize("entrypoint", ["create_run", "trigger_schedule"])
def test_direct_engine_also_rejects_linked_agent_own_mode_before_writes(entrypoint):
    owner = _owner()
    agent = store.save_entity(owner, "agents", _body("agents", control_level="approve"))
    values = {"id": "not-created", "name": "forbidden", "prompt": "不得执行", "control_level": "observe", "agent_id": agent["id"]}
    before = _snapshot()
    with pytest.raises(HTTPException) as rejected:
        if entrypoint == "create_run":
            engine.create_run(owner, values, "不得执行")
        else:
            engine.trigger_schedule(owner, values)
    assert rejected.value.status_code == 403
    assert _snapshot() == before and engine.TASKS == {}


@pytest.mark.parametrize("level", LEVELS)
async def test_explicit_single_mode_grant_allows_that_engine_run_without_implying_other_modes(monkeypatch, level):
    owner = _owner((level,))
    runner = AsyncMock(return_value=None)
    monkeypatch.setattr(engine, "run_agent", runner)
    conversation = _conversation(owner, level)
    assert access.execution_allowed(owner, level) is None
    run = engine.create_run(owner, conversation, "本地授权执行")
    await asyncio.gather(*list(engine.TASKS.values()))
    runner.assert_awaited_once_with(owner, run["id"])
    assert run["control_level"] == level and run["status"] == "queued"
    for denied in set(LEVELS) - {level}:
        before = _snapshot()
        with pytest.raises(HTTPException) as rejected:
            engine.create_run(owner, {**conversation, "control_level": denied}, "不得执行")
        assert rejected.value.status_code == 403 and _snapshot() == before


async def test_scheduler_rejected_due_item_does_not_skip_later_valid_due_item(monkeypatch):
    owner = _owner()
    denied = store.save_entity(owner, "schedules", _body(
        "schedules", name="first denied", enabled=True, control_level="approve", next_run_at="2000-01-01T00:00:00+00:00",
    ))
    valid = store.save_entity(owner, "schedules", _body(
        "schedules", name="second valid", enabled=True, control_level="observe", next_run_at="2000-01-01T00:00:00+00:00",
    ))
    runner = AsyncMock(return_value=None)
    monkeypatch.setattr(engine, "run_agent", runner)
    monkeypatch.setattr(engine.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
    try:
        with pytest.raises(asyncio.CancelledError):
            await engine.scheduler_loop()
        dispatched = store.get_entity(owner, "schedules", valid["id"])
        assert dispatched.get("last_run_id"), "a rejected first schedule must not abort the remaining due schedules"
        assert not store.get_entity(owner, "schedules", denied["id"]).get("last_run_id")
        assert len(store.list_runs(owner)) == len(store.list_entities(owner, "conversations")) == 1
    finally:
        await asyncio.gather(*list(engine.TASKS.values()), return_exceptions=True)


@pytest.mark.parametrize("source", ["run-grant", "linked-grant", "agent-mode-change"])
async def test_model_response_rechecks_live_grants_and_agent_mode_before_any_tool(monkeypatch, source):
    owner = _owner(("observe", "approve") if source != "agent-mode-change" else ("observe",))
    provider = store.save_entity(owner, "providers", _body("providers", api_key=store.seal("local-test-only")))
    agent = store.save_entity(owner, "agents", _body("agents", control_level="approve" if source == "linked-grant" else "observe"))
    level = "approve" if source == "run-grant" else "observe"
    conversation = _conversation(owner, level, provider_id=provider["id"], agent_id=agent["id"])
    run = _run(owner, level, status="queued", conversation=conversation, provider_id=provider["id"], agent_id=agent["id"])

    async def model_response(*args):
        if model.await_count == 1:
            if source == "agent-mode-change":
                store.save_entity(owner, "agents", {**agent, "control_level": "autonomous"}, agent["id"])
            else:
                _set_user(owner, allowed_control_levels=["observe"])
            return TOOL_CALL
        return FINAL

    model = AsyncMock(side_effect=model_response)
    execute = AsyncMock(return_value={"files": []})
    monkeypatch.setattr(engine, "model_completion", model)
    monkeypatch.setattr(tools, "execute", execute)
    await engine.run_agent(owner, run["id"])
    model.assert_awaited_once()
    execute.assert_not_awaited()
    assert store.get_run(owner, run["id"])["status"] not in engine.ACTIVE | {"completed"}
    assert not any(event["type"] == "tool_result" and event["data"].get("executed") for event in store.events(run["id"]))


@pytest.mark.parametrize("linked", [False, True])
async def test_admin_revocation_cancels_inflight_model_before_any_tool(client, administrator, monkeypatch, linked):
    started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def blocked_model(*args):
        progress.MODEL_EVENTS.get()("content", {"content": "正在等待本地测试结果。"})
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return TOOL_CALL

    model = AsyncMock(side_effect=blocked_model)
    execute = AsyncMock(return_value={"files": []})
    monkeypatch.setattr(engine, "model_completion", model)
    monkeypatch.setattr(tools, "execute", execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver") as http:
        user = _ok(await http.post("/api/auth/register", json={"email": "live-grant@example.test", "password": PASSWORD}))
        owner_token = http.cookies.get("earthai_session")
        _set_user(user["id"], allowed_control_levels=["observe", "approve"])
        provider = _ok(await http.post("/api/providers", json=_body("providers")))
        agent = _ok(await http.post("/api/agents", json=_body("agents", control_level="approve"))) if linked else None
        conversation = _ok(await http.post("/api/conversations", json={
            "provider_id": provider["id"], "control_level": "observe" if linked else "approve", "agent_id": agent["id"] if agent else None,
        }))
        run = _ok(await http.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "概述已有资料"}))
        task = engine.TASKS[run["id"]]
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            _as(http, administrator["token"])
            changed = _ok(await asyncio.wait_for(http.patch(f"/api/admin/users/{user['id']}", json={
                "allowed_control_levels": ["observe"],
            }), timeout=3))
            assert changed["allowed_control_levels"] == ["observe"]
            assert cancelled.is_set() and task.done() and task.cancelled()
            assert store.get_run(user["id"], run["id"])["status"] == "cancelled"
            assert run["id"] not in engine.TASKS and run["id"] not in engine.CANCEL_TOKENS
            assert not any(event["type"] in {"tool_start", "tool_execution", "tool_result"} for event in store.events(run["id"]))
            model.assert_awaited_once()
            execute.assert_not_awaited()
            _as(http, owner_token)
            assert _ok(await http.get("/api/auth/me"))["allowed_control_levels"] == ["observe"]
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("linked", [False, True])
def test_waiting_approval_cannot_be_approved_after_run_or_linked_mode_is_revoked(client, linked):
    user = _register(client)
    agent = store.save_entity(user["id"], "agents", _body("agents", control_level="approve")) if linked else None
    run = _run(user["id"], "observe" if linked else "approve", status="waiting_approval", agent_id=agent["id"] if agent else None)
    approval_id = _approval(user["id"], run)
    before = _snapshot()
    _ok(client.post(f"/api/approvals/{approval_id}", json={"approved": True}), 403)
    assert _snapshot() == before
    assert _ok(client.post(f"/api/approvals/{approval_id}", json={"approved": False}))["status"] == "rejected"


async def test_approval_wait_rechecks_grant_even_if_approval_became_approved(monkeypatch):
    owner = _owner(("observe", "approve"))
    run = _run(owner, "approve")

    async def revoke_and_mark_approved(_):
        _set_user(owner, allowed_control_levels=["observe"])
        with store.connect() as db:
            db.execute("UPDATE approvals SET status='approved' WHERE run_id=?", (run["id"],))

    monkeypatch.setattr(engine.asyncio, "sleep", revoke_and_mark_approved)
    with pytest.raises(HTTPException) as rejected:
        await engine.request_approval(owner, run, "ssh_exec", {"command": "systemctl restart app"}, "write")
    assert rejected.value.status_code == 403
    assert store.get_run(owner, run["id"])["status"] == "waiting_approval"
    assert not any(event["type"] == "status" and event["data"].get("status") == "running" for event in store.events(run["id"]))


def test_revocation_cancels_only_removed_modes_including_old_linked_runs_and_keeps_private_and_other_user_data(client, administrator):
    owner = _managed(client, allowed_control_levels=list(LEVELS))
    survivor = _managed(client, "unchanged-other", allowed_control_levels=["autonomous"])
    _set_user(owner["id"], control_level="approve", chat_preferences={**main.default_chat_preferences(owner), "control_level": "autonomous"})
    agent = store.save_entity(owner["id"], "agents", _body("agents", control_level="approve"))
    knowledge = store.save_entity(owner["id"], "knowledge", _body("knowledge", personal_override=True))
    with store.connect() as db:
        db.execute("INSERT INTO default_owner_states(owner,template_id,entity_id,state) VALUES (?,?,?,?)", (
            owner["id"], "historical-template", knowledge["id"], "override",
        ))
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", ("private-doc", owner["id"], knowledge["id"], "private.md", 8, 1, store.now()))
        db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", ("private-chunk", owner["id"], knowledge["id"], "private-doc", "private.md", "private evidence"))
    store.save_entity(survivor["id"], "skills", _body("skills"))
    survivor_run = _run(survivor["id"], "autonomous")
    kept, removed, approvals = [], [], {}
    for level in LEVELS:
        for status in ("queued", "running", "waiting_approval"):
            run = _run(owner["id"], level, status)
            (removed if level == "approve" else kept).append(run)
            if status == "waiting_approval":
                approvals[run["id"]] = _approval(owner["id"], run)
    linked = _run(owner["id"], "observe", agent_id=agent["id"])
    removed.append(linked)
    tokens = {run["id"]: tools.Cancellation() for run in kept + removed}
    engine.CANCEL_TOKENS.update(tokens)
    schedules = [store.save_entity(owner["id"], "schedules", _body("schedules", control_level=level, enabled=True)) for level in LEVELS]
    with store.connect() as db:
        db.execute("UPDATE runs SET created_at='2000-01-01T00:00:00+00:00' WHERE owner=?", (owner["id"],))
        stamp = store.now()
        db.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", [
            (store.uid(), owner["id"], linked["conversation_id"], "completed", "{}", stamp, stamp) for _ in range(205)
        ])
    assert len(store.list_runs(owner["id"])) == 200
    before_owner, before_survivor = _owned_snapshot(owner["id"]), _owned_snapshot(survivor["id"])
    before_entities = {item["id"]: item for kind in ("agents", "knowledge", "conversations") for item in store.list_entities(owner["id"], kind)}
    changed = _ok(client.patch(f"/api/admin/users/{owner['id']}", json={"allowed_control_levels": ["autonomous", "observe"]}))
    assert changed["allowed_control_levels"] == ["observe", "autonomous"]
    assert changed["control_level"] == "observe" and changed["chat_preferences"]["control_level"] == "autonomous"
    for run in removed:
        assert store.get_run(owner["id"], run["id"])["status"] == "cancelled"
        assert tokens[run["id"]].event.is_set()
    for run in kept:
        assert store.get_run(owner["id"], run["id"])["status"] == run["status"]
        assert not tokens[run["id"]].event.is_set()
    for schedule in schedules:
        assert store.get_entity(owner["id"], "schedules", schedule["id"])["enabled"] is (schedule["control_level"] != "approve")
    with store.connect() as db:
        for run_id, approval_id in approvals.items():
            expected = "expired" if run_id in {run["id"] for run in removed} else "pending"
            assert db.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()[0] == expected
        assert db.execute("SELECT count(*) FROM runs WHERE owner=? AND status='completed'", (owner["id"],)).fetchone()[0] == 205
    after_owner = _owned_snapshot(owner["id"])
    for table in ("documents", "chunks", "default_owner_states", "agent_orders", "sessions"):
        assert after_owner[table] == before_owner[table]
    for id_, original in before_entities.items():
        kind = "agents" if id_ == agent["id"] else "knowledge" if id_ == knowledge["id"] else "conversations"
        assert store.get_entity(owner["id"], kind, id_) == original
    assert _owned_snapshot(survivor["id"]) == before_survivor
    assert store.get_run(survivor["id"], survivor_run["id"])["status"] == "running"
    for run_id in {run["id"] for run in removed} & approvals.keys():
        _ok(client.post("/api/auth/login", json={"email": owner["email"], "password": PASSWORD}))
        _ok(client.post(f"/api/approvals/{approvals[run_id]}", json={"approved": True}), 409)


@pytest.mark.parametrize("source", ["private", "default"])
@pytest.mark.parametrize("level", ["approve", "autonomous"])
def test_existing_restricted_agent_can_be_renamed_without_granting_execution(client, source, level):
    template = defaults.save("agents", _body("agents", control_level=level)) if source == "default" else None
    user = _register(client)
    agent = next(item for item in store.list_entities(user["id"], "agents") if item.get("default_template_id") == template["id"]) if template else store.save_entity(user["id"], "agents", _body("agents", control_level=level))
    changed = _ok(client.patch(f"/api/agents/{agent['id']}", json={"name": "个人改名不提升权限"}))
    assert changed["id"] == agent["id"] and changed["name"] == "个人改名不提升权限"
    assert changed["control_level"] == level
    assert _data(user["id"])["allowed_control_levels"] == ["observe"]
    if template:
        assert changed["default_template_id"] == template["id"] and changed["personal_override"] is True
        assert defaults.get_template("agents", template["id"])["name"] == template["name"]
    history = _conversation(user["id"], agent_id=agent["id"])
    before = _snapshot()
    for path, body in (
        ("/api/conversations", {"agent_id": agent["id"], "control_level": "observe"}),
        (f"/api/conversations/{history['id']}/messages", {"content": "只改名不代表获准执行"}),
    ):
        _ok(client.post(path, json=body), 403)
        assert _snapshot() == before
    with pytest.raises(HTTPException) as rejected:
        engine.create_run(user["id"], history, "不得执行")
    assert rejected.value.status_code == 403 and _snapshot() == before


@pytest.mark.parametrize("restriction", ["schedule-mode", "linked-agent-mode"])
@pytest.mark.parametrize("level", ["approve", "autonomous"])
def test_revoked_schedule_can_be_disabled_but_cannot_be_reenabled_or_run(client, restriction, level):
    user = _register(client)
    agent = store.save_entity(user["id"], "agents", _body("agents", control_level=level)) if restriction == "linked-agent-mode" else None
    schedule = store.save_entity(user["id"], "schedules", _body(
        "schedules", enabled=True, control_level="observe" if agent else level, agent_id=agent["id"] if agent else None,
    ))
    disabled = _ok(client.patch(f"/api/schedules/{schedule['id']}", json={"enabled": False}))
    assert disabled["enabled"] is False
    assert disabled["control_level"] == schedule["control_level"] and disabled["agent_id"] == schedule["agent_id"]
    assert _data(user["id"])["allowed_control_levels"] == ["observe"]
    before = _snapshot()
    _ok(client.patch(f"/api/schedules/{schedule['id']}", json={"enabled": True}), 403)
    assert _snapshot() == before
    _ok(client.post(f"/api/schedules/{schedule['id']}/run", json={}), 403)
    assert _snapshot() == before


async def test_grant_tightening_does_not_cancel_inflight_observe_run_when_its_mode_is_unchanged(client, administrator, monkeypatch):
    owner = _owner(("observe", "approve"))
    preferences = main.default_chat_preferences(_data(owner))
    _set_user(owner, chat_preferences=preferences)
    provider = store.save_entity(owner, "providers", _body("providers", api_key=store.seal("local-test-only")))
    agent = store.save_entity(owner, "agents", _body("agents", control_level="observe"))
    conversation = _conversation(owner, provider_id=provider["id"], agent_id=agent["id"])
    started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def blocked_model(*args):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return dict(FINAL)

    model = AsyncMock(side_effect=blocked_model)
    monkeypatch.setattr(engine, "model_completion", model)
    run = engine.create_run(owner, conversation, "概述已有资料")
    task = engine.TASKS[run["id"]]
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        cancel_token = engine.CANCEL_TOKENS[run["id"]]
        before = store.get_run(owner, run["id"])
        assert before["status"] == "running" and before["control_level"] == "observe"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver") as http:
            _as(http, administrator["token"])
            changed = _ok(await asyncio.wait_for(http.patch(f"/api/admin/users/{owner}", json={
                "allowed_control_levels": ["observe"],
            }), timeout=3))
        assert changed["allowed_control_levels"] == ["observe"]
        assert changed["control_level"] == "observe" and changed["chat_preferences"] == preferences
        assert engine.TASKS[run["id"]] is task and not task.done()
        assert not cancel_token.event.is_set() and not cancelled.is_set()
        assert store.get_run(owner, run["id"]) == before
        release.set()
        await asyncio.wait_for(task, timeout=3)
        assert store.get_run(owner, run["id"])["status"] == "completed"
        assert not task.cancelled() and not cancelled.is_set()
        model.assert_awaited_once()
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("with_agent", [False, True])
async def test_project_skills_merge_with_agent_deduplicate_before_twelve_limit_and_count_once(monkeypatch, with_agent):
    owner = _owner()
    provider = store.save_entity(owner, "providers", _body("providers", api_key=store.seal("local-test-only")))
    skills = [store.save_entity(owner, "skills", _body(
        "skills", name=f"skill-{index}", content=f"PROJECT_MERGED_SKILL_{index:02d}_MARKER",
    )) for index in range(14)]
    ids = [skill["id"] for skill in skills]
    agent = store.save_entity(owner, "agents", _body(
        "agents", control_level="observe", skill_ids=[ids[0], ids[0], ids[1], ids[2]],
    )) if with_agent else None
    project_ids = [ids[2], ids[2], *ids[3:], ids[0], ids[1]] if with_agent else [ids[0], *ids]
    project = store.save_entity(owner, "projects", _body("projects", skill_ids=project_ids))
    conversation = _conversation(owner, provider_id=provider["id"], project_id=project["id"], agent_id=agent["id"] if agent else None)
    run = _run(owner, status="queued", conversation=conversation, provider_id=provider["id"],
               project_id=project["id"], agent_id=agent["id"] if agent else None)
    model = AsyncMock(side_effect=[TOOL_CALL, dict(FINAL)])
    execute = AsyncMock(return_value={"files": []})
    monkeypatch.setattr(engine, "model_completion", model)
    monkeypatch.setattr(tools, "execute", execute)
    await engine.run_agent(owner, run["id"])
    assert store.get_run(owner, run["id"])["status"] == "completed"
    assert model.await_count == 2
    execute.assert_awaited_once_with(owner, None, "list_files", {}, None)
    prompt = model.await_args_list[0].args[2][0]["content"]
    for index in range(14):
        assert prompt.count(f"PROJECT_MERGED_SKILL_{index:02d}_MARKER") == (1 if index < 12 else 0)
    positions = [prompt.index(f"PROJECT_MERGED_SKILL_{index:02d}_MARKER") for index in range(12)]
    assert positions == sorted(positions)
    with store.connect() as db:
        counts = {row["resource_id"]: row["total"] for row in db.execute(
            "SELECT resource_id,count(*) total FROM resource_usage WHERE owner=? AND run_id=? AND kind='skills' GROUP BY resource_id",
            (owner, run["id"]),
        )}
    assert counts == dict.fromkeys(ids[:12], 1)
    assert usage.resource_counts(owner, "skills") == counts
    assert usage.summary()["totals"] == {"agents": int(with_agent), "knowledge": 0, "skills": 12}


@pytest.mark.parametrize("operation", ["create", "patch"])
async def test_resource_write_refreshes_grants_after_awaiting_request_body(client, operation):
    user = _register(client)
    _set_user(user["id"], allowed_control_levels=["observe", "approve"])
    stale_user = {**user, "allowed_control_levels": ["observe", "approve"]}
    agent = _ok(client.post("/api/agents", json=_body("agents"))) if operation == "patch" else None
    snapshots = []

    async def receive():
        _set_user(user["id"], allowed_control_levels=["observe"])
        snapshots.append(_snapshot())
        body = _body("agents", control_level="approve") if operation == "create" else {"control_level": "approve"}
        return {"type": "http.request", "body": store.dumps(body).encode(), "more_body": False}

    request = main.Request({"type": "http", "method": "POST" if operation == "create" else "PATCH",
                            "path": "/api/agents", "headers": []}, receive)
    with pytest.raises(HTTPException) as rejected:
        if agent:
            await main.update("agents", agent["id"], request, user=stale_user)
        else:
            await main.create("agents", request, user=stale_user)
    assert rejected.value.status_code == 403
    assert len(snapshots) == 1 and _snapshot() == snapshots[0]
    assert _data(user["id"])["allowed_control_levels"] == ["observe"] and engine.TASKS == {}
