"""Space grants regressions using isolated SQLite and local blobs, never real services."""

import asyncio
import hashlib
import io
import sqlite3
import threading
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import paramiko
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from backend import access, admin, defaults, engine, main, model_client, store, text_tools, tools, usage


PASSWORD = "Space-modules-local-test-password!"
MODULES = ("personal", "team")
INVALID_MODULES = [
    None, "personal", {"personal": True}, True, 1, 0,
    ["Personal"], [" personal"], ["root"], ["personal", "personal"],
    ["personal", "team", "team"], ["personal", None], [False], [["personal"]],
]
FINAL = {"role": "assistant", "content": "本地测试结束。"}


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    data, state, uploads = tmp_path / "data", tmp_path / "state", tmp_path / "uploads"
    for path in (data, state, uploads):
        path.mkdir()
    for name, value in (("DATA_ROOT", data), ("DATA", state), ("UPLOADS", uploads), ("DB_PATH", state / "spaces.db")):
        monkeypatch.setattr(store, name, value)
    monkeypatch.setattr(store, "_CONNECTIONS", {})
    monkeypatch.setattr(store, "_CONNECTION_LOCK", threading.Lock())
    monkeypatch.setattr(store, "_CONNECTION_LOCAL", threading.local())
    monkeypatch.setattr(store, "_cipher", lru_cache(maxsize=4)(store._cipher.__wrapped__))
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
        (model_client, "complete", AsyncMock(side_effect=AssertionError("unexpected model HTTP request"))),
        (text_tools, "complete", AsyncMock(side_effect=AssertionError("unexpected fallback model request"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected infrastructure connection"))),
        (tools, "ssh_connect", Mock(side_effect=AssertionError("unexpected SSH execution"))),
        (paramiko.SSHClient, "connect", Mock(side_effect=AssertionError("unexpected SSH connection"))),
        (httpx.HTTPTransport, "handle_request", Mock(side_effect=AssertionError("unexpected external HTTP request"))),
        (httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(side_effect=AssertionError("unexpected external HTTP request"))),
    ]
    for target, name, replacement in blocked:
        monkeypatch.setattr(target, name, replacement)
    store.init_db()
    defaults.init_tables()
    usage.initialize()
    try:
        yield
    finally:
        store.close_connections()
        store._cipher.cache_clear()
    for _, name, replacement in blocked:
        assert replacement.call_count == 0, name


@pytest.fixture
def client(isolated_store):
    # Do not start lifespan or its scheduler; all tables are initialized in the fixture.
    client = TestClient(main.app)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def administrator(client):
    admin.bootstrap_admin()
    with store.connect() as db:
        row = db.execute("SELECT id,data FROM users WHERE email='admin'").fetchone()
        data = {**store.loads(row["data"]), "must_change_password": False}
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(data), row["id"]))
    token = store.new_session(row["id"])
    _as(client, token)
    return {"user": {**data, "id": row["id"], "email": "admin"}, "token": token}


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _as(client, token):
    client.cookies.clear()
    client.cookies.set("earthai_session", token)


def _account(*, legacy=False, **changes):
    id_ = store.uid()
    data = {
        "name": "local space owner", "role": "user", "control_level": "observe",
        "allowed_control_levels": ["observe"], "disabled": False, "must_change_password": False,
        "team_invites_blocked": False,
    }
    if not legacy:
        data["space_modules"] = ["personal"]
    data.update(changes)
    email = f"{id_}@example.test"
    with store.connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (id_, email, "unused-local-password", store.dumps(data), store.now()))
    return {**data, "id": id_, "email": email}


def _data(owner):
    with store.connect() as db:
        return store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()[0])


def _set_user(owner, **changes):
    with store.connect() as db:
        data = store.loads(db.execute("SELECT data FROM users WHERE id=?", (owner,)).fetchone()[0])
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps({**data, **changes}), owner))


def _managed(client, email="managed-space", **changes):
    return _ok(client.post("/api/admin/users", json={
        "email": email, "name": email, "password": PASSWORD, **changes,
    }))


def _rows(table, clause="", parameters=()):
    with store.connect() as db:
        return [tuple(row) for row in db.execute(f'SELECT * FROM "{table}" {clause} ORDER BY rowid', parameters)]


def _snapshot():
    with store.connect() as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
        )]
        return {table: sorted((tuple(row) for row in db.execute(f'SELECT * FROM "{table}"')), key=repr) for table in tables}


def _blobs():
    return {path.name: (path.read_bytes(), hashlib.sha256(path.read_bytes()).hexdigest()) for path in store.UPLOADS.iterdir()}


def _seed_file(owner, *, storage_name=None, content=b"unchanged personal evidence\n"):
    storage_name = storage_name or store.uid()
    (store.UPLOADS / storage_name).write_bytes(content)
    return store.save_entity(owner, "files", {
        "name": "private.md", "size": len(content), "mime": "text/markdown", "storage_name": storage_name,
    })


def _deny_blob_io(patch):
    guards = []
    for name in ("read_bytes", "read_text", "write_bytes", "write_text", "open", "unlink"):
        guard = Mock(side_effect=AssertionError(f"denied space must not call Path.{name}"))
        patch.setattr(Path, name, guard)
        guards.append(guard)
    return guards


def _body(kind):
    return {
        "agents": {"name": "local agent", "kind": "local", "system_prompt": "仅概述已有证据"},
        "schedules": {"name": "local schedule", "prompt": "概述资料", "cron": "0 9 * * *", "timezone": "UTC", "enabled": False},
        "conversations": {"title": "local conversation"},
        "servers": {"name": "local server", "host": "192.0.2.44", "password": "offline-only"},
        "providers": {"name": "local provider", "base_url": "https://model.example.invalid/v1", "api_key": "offline-only",
                      "models": ["local-model"], "default_model": "local-model"},
        "skills": {"name": "local skill", "content": "收集证据"},
        "knowledge": {"name": "local knowledge", "description": "私人资料"},
        "projects": {"name": "local project"},
        "alerts": {"title": "local alert", "description": "本地测试"},
    }[kind]


def _tool_call(name, args, call_id="local-tool"):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": store.dumps(args)}},
    ]}


def _run(owner):
    provider = store.save_entity(owner, "providers", {**_body("providers"), "api_key": store.seal("offline-only")})
    conversation = store.save_entity(owner, "conversations", {**_body("conversations"), "control_level": "observe"})
    id_, stamp = store.uid(), store.now()
    data = {"goal": "保存本地资料", "control_level": "observe", "model": "local-model", "provider_id": provider["id"], "step_count": 0}
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (
            id_, owner, conversation["id"], "queued", store.dumps(data), stamp, stamp,
        ))
    return store.get_run(owner, id_)


@pytest.mark.parametrize("modules", [[], ["personal"], ["team"], ["personal", "team"]])
def test_space_modules_are_exact_subsets_including_empty(modules):
    raw = list(reversed(modules))
    user = {"role": "user", "space_modules": raw}
    assert access.validate_space_modules(raw) == modules
    assert access.enabled_spaces(user) == modules
    assert user["space_modules"] == raw
    for module in MODULES:
        if module in modules:
            assert access.require_space(user, module) is user
        else:
            with pytest.raises(HTTPException) as rejected:
                access.require_space(user, module)
            assert rejected.value.status_code == 403


@pytest.mark.parametrize("value", INVALID_MODULES)
def test_invalid_explicit_modules_fail_closed_for_user_and_fresh_owner(value):
    with pytest.raises(ValueError):
        access.validate_space_modules(value)
    user = _account(space_modules=value)
    assert access.enabled_spaces(user) == []
    for module in MODULES:
        for check in (lambda: access.require_space(user, module), lambda: access.require_space_owner(user["id"], module)):
            with pytest.raises(HTTPException) as rejected:
                check()
            assert rejected.value.status_code == 403
    assert _data(user["id"])["space_modules"] == value


def test_tuple_is_not_an_accepted_in_memory_module_list():
    with pytest.raises(ValueError):
        access.validate_space_modules(("personal",))
    assert access.enabled_spaces({"space_modules": ("personal",)}) == []


@pytest.mark.parametrize("changes", [{"disabled": True}, {"role": "admin"}, {"role": "unknown"}, {"must_change_password": True}])
def test_space_access_never_bypasses_account_restrictions(changes):
    user = _account(space_modules=list(MODULES), **changes)
    for module in MODULES:
        with pytest.raises(HTTPException) as rejected:
            access.require_space(user, module)
        assert rejected.value.status_code == 403
        with pytest.raises(HTTPException) as rejected:
            access.require_space_owner(user["id"], module)
        assert rejected.value.status_code == 403


@pytest.mark.parametrize("module", [None, [], {}, "Personal", "root"])
def test_unknown_requested_space_is_a_permission_denial(module):
    user = _account(space_modules=list(MODULES))
    with pytest.raises(HTTPException) as rejected:
        access.require_space(user, module)
    assert rejected.value.status_code == 403


@pytest.mark.parametrize("in_transaction", [False, True])
def test_require_space_owner_reads_latest_grants_not_an_earlier_user(in_transaction):
    user = _account(space_modules=list(MODULES))
    _set_user(user["id"], space_modules=["team"])
    assert access.require_space(user, "personal") is user
    if in_transaction:
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            with pytest.raises(HTTPException) as rejected:
                access.require_space_owner(user["id"], "personal")
    else:
        with pytest.raises(HTTPException) as rejected:
            access.require_space_owner(user["id"], "personal")
    assert rejected.value.status_code == 403
    assert access.require_space_owner(user["id"], "team")["space_modules"] == ["team"]


def test_require_space_owner_rejects_missing_account():
    with pytest.raises(HTTPException) as rejected:
        access.require_space_owner("missing-owner", "personal")
    assert rejected.value.status_code == 403


@pytest.mark.parametrize("injected", [[], ["team"], ["personal", "team"]])
def test_registration_cannot_self_grant_spaces_controls_or_invitation_override(client, injected):
    user = _ok(client.post("/api/auth/register", json={
        "email": "registered-space@example.test", "password": PASSWORD,
        "space_modules": injected, "allowed_control_levels": ["autonomous"], "team_invites_blocked": True,
    }))
    assert user["space_modules"] == ["personal"]
    assert user["allowed_control_levels"] == ["observe"]
    saved = _data(user["id"])
    assert saved["space_modules"] == ["personal"]
    assert saved["allowed_control_levels"] == ["observe"]
    assert saved.get("team_invites_blocked", False) is False
    assert _ok(client.get("/api/auth/me"))["space_modules"] == ["personal"]
    assert _ok(client.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}))["space_modules"] == ["personal"]


@pytest.mark.parametrize(("changes", "expected"), [
    ({}, ["personal"]), ({"space_modules": []}, []), ({"space_modules": ["personal"]}, ["personal"]),
    ({"space_modules": ["team"]}, ["team"]), ({"space_modules": ["team", "personal"]}, ["personal", "team"]),
])
def test_admin_create_defaults_to_personal_or_uses_exact_explicit_modules(client, administrator, changes, expected):
    user = _managed(client, **changes)
    assert user["space_modules"] == expected
    assert _data(user["id"])["space_modules"] == expected
    assert user["team_invites_blocked"] is False
    assert _data(user["id"])["team_invites_blocked"] is False
    assert _ok(client.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}))["space_modules"] == expected


@pytest.mark.parametrize("modules", ["missing", None, [], ["team"], ["personal", "team"]])
def test_admin_patch_omitting_modules_never_rewrites_existing_raw_grants_or_invite_block(client, administrator, modules):
    user = _account(team_invites_blocked=True)
    with store.connect() as db:
        data = _data(user["id"])
        if modules == "missing":
            data.pop("space_modules")
        else:
            data["space_modules"] = modules
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(data), user["id"]))
    changed = _ok(client.patch(f"/api/admin/users/{user['id']}", json={"name": "unrelated edit"}))
    after = _data(user["id"])
    assert ("space_modules" in after) == ("space_modules" in data)
    assert after.get("space_modules") == data.get("space_modules")
    assert after["team_invites_blocked"] is True
    assert changed["space_modules"] == access.enabled_spaces(data)


def test_admin_single_and_batch_replace_modules_only_when_explicit_and_allow_empty(client, administrator):
    one, two = _account(space_modules=list(MODULES)), _account()
    changed = _ok(client.patch(f"/api/admin/users/{one['id']}", json={"space_modules": []}))
    assert changed["space_modules"] == [] and changed["team_invites_blocked"] is True
    _ok(client.post("/api/admin/users/batch", json={
        "ids": [one["id"], two["id"]], "action": "update", "changes": {"space_modules": ["team", "personal"]},
    }))
    for user in (one, two):
        assert _data(user["id"])["space_modules"] == list(MODULES)
        assert _data(user["id"])["team_invites_blocked"] is False
    _ok(client.post("/api/admin/users/batch", json={
        "ids": [one["id"], two["id"]], "action": "update", "changes": {"space_modules": []},
    }))
    _ok(client.post("/api/admin/users/batch", json={
        "ids": [one["id"], two["id"]], "action": "update", "changes": {"name": "unrelated batch edit"},
    }))
    for user in (one, two):
        assert _data(user["id"])["space_modules"] == []
        assert _data(user["id"])["team_invites_blocked"] is True


@pytest.mark.parametrize("modules", [None, "personal", {}, True, ["root"], ["personal", "personal"], ["personal", False]])
def test_invalid_admin_space_payload_rejects_create_patch_and_entire_batch_without_writes(client, administrator, modules):
    one, two = _account(), _account(space_modules=["team"])
    before, blobs = _snapshot(), _blobs()
    for method, path, body in (
        ("POST", "/api/admin/users", {"email": "invalid-space", "name": "invalid", "password": PASSWORD, "space_modules": modules}),
        ("PATCH", f"/api/admin/users/{one['id']}", {"name": "must not save", "space_modules": modules}),
        ("POST", "/api/admin/users/batch", {"ids": [one["id"], two["id"]], "action": "update",
                                            "changes": {"name": "must not save", "space_modules": modules}}),
    ):
        _ok(client.request(method, path, json=body), 422)
        assert _snapshot() == before and _blobs() == blobs


@pytest.mark.parametrize("shape", [
    "null-body", "list-body", "unknown-field", "null-changes", "list-changes", "string-changes",
    "string-ids", "empty-ids", "nested-id", "bool-id", "list-action", "dict-action",
])
def test_admin_batch_invalid_shapes_are_422_and_atomic(client, administrator, shape):
    one, two = _account(), _account(space_modules=["team"])
    body = {"ids": [one["id"], two["id"]], "action": "update", "changes": {"space_modules": []}}
    if shape == "null-body":
        body = None
    elif shape == "list-body":
        body = []
    elif shape == "unknown-field":
        body["space_modules"] = ["team"]
    elif shape.endswith("-changes"):
        body["changes"] = {"null-changes": None, "list-changes": [], "string-changes": "personal"}[shape]
    elif shape.endswith("-ids"):
        body["ids"] = one["id"] if shape == "string-ids" else []
    elif shape == "nested-id":
        body["ids"] = [one["id"], [two["id"]]]
    elif shape == "bool-id":
        body["ids"] = [one["id"], True]
    else:
        body["action"] = [] if shape == "list-action" else {}
    before = _snapshot()
    _ok(client.post("/api/admin/users/batch", content=store.dumps(body), headers={"content-type": "application/json"}), 422)
    assert _snapshot() == before


def test_admin_batch_invalid_targets_and_protected_account_cannot_partially_change_modules(client, administrator):
    one, two = _account(), _account(space_modules=list(MODULES))
    before = _snapshot()
    for ids, changes in (
        ([one["id"], "missing"], {"space_modules": []}),
        ([one["id"], one["id"]], {"space_modules": []}),
        ([one["id"], two["id"], administrator["user"]["id"]], {"space_modules": [], "role": "user"}),
    ):
        _ok(client.post("/api/admin/users/batch", json={"ids": ids, "action": "update", "changes": changes}), 422)
        assert _snapshot() == before


def test_profile_cannot_self_grant_modules_controls_or_clear_admin_invitation_block(client):
    user = _account(space_modules=[], team_invites_blocked=True)
    _as(client, store.new_session(user["id"]))
    updated = _ok(client.patch("/api/auth/me", json={
        "name": "ordinary profile edit", "space_modules": list(MODULES),
        "allowed_control_levels": ["autonomous"], "team_invites_blocked": False,
    }))
    assert updated["name"] == "ordinary profile edit"
    assert updated["space_modules"] == [] and updated["allowed_control_levels"] == ["observe"]
    saved = _data(user["id"])
    assert saved["space_modules"] == [] and saved["allowed_control_levels"] == ["observe"]
    assert saved["team_invites_blocked"] is True
    before = _snapshot()
    _ok(client.patch(f"/api/admin/users/{user['id']}", json={"space_modules": ["team"]}), 403)
    _ok(client.post("/api/admin/users/batch", json={
        "ids": [user["id"]], "action": "update", "changes": {"space_modules": ["team"]},
    }), 403)
    _ok(client.post("/api/team-spaces", json={"name": "must not create"}), 403)
    assert _snapshot() == before


@pytest.mark.parametrize("modules", [[], ["team"], None, ["personal", "unknown"], ["personal", "personal"]])
@pytest.mark.parametrize("surface", ["list", "upload", "download", "delete"])
def test_disabled_personal_http_endpoints_deny_without_blob_io_or_database_writes(client, monkeypatch, modules, surface):
    user = _account(space_modules=modules)
    file = _seed_file(user["id"])
    _as(client, store.new_session(user["id"]))
    before, blobs = _snapshot(), _blobs()
    with monkeypatch.context() as patch:
        guards = _deny_blob_io(patch)
        if surface == "upload":
            response = client.post("/api/files", files={"file": ("denied.md", b"must not save", "text/markdown")})
        elif surface == "list":
            response = client.get("/api/files")
        elif surface == "download":
            response = client.get(f"/api/files/{file['id']}/download")
        else:
            response = client.delete(f"/api/files/{file['id']}")
        _ok(response, 403)
        for guard in guards:
            guard.assert_not_called()
    assert _snapshot() == before and _blobs() == blobs


@pytest.mark.parametrize("modules", [[], ["team"], None, ["personal", "unknown"], ["personal", "personal"]])
@pytest.mark.parametrize("name", ["list_files", "read_file", "write_report"])
async def test_direct_file_tools_refresh_permission_before_metadata_or_blob_access(monkeypatch, modules, name):
    user = _account()
    file = _seed_file(user["id"])
    _set_user(user["id"], space_modules=modules)
    before, blobs = _snapshot(), _blobs()
    args = {"file_id": file["id"]} if name == "read_file" else {"name": "denied.md", "content": "must not save"} if name == "write_report" else {}
    with monkeypatch.context() as patch:
        guards = _deny_blob_io(patch)
        for lookup in ("get_entity", "list_entities", "save_entity"):
            guard = Mock(side_effect=AssertionError(f"denied space must not call store.{lookup}"))
            patch.setattr(store, lookup, guard)
            guards.append(guard)
        with pytest.raises(HTTPException) as rejected:
            await tools.execute(user["id"], None, name, args)
        assert rejected.value.status_code == 403
        for guard in guards:
            guard.assert_not_called()
    assert _snapshot() == before and _blobs() == blobs


@pytest.mark.parametrize("kind", ["servers", "providers", "agents", "skills", "knowledge", "projects", "alerts", "schedules", "conversations"])
def test_team_only_user_can_crud_non_file_resources_without_personal_grant(client, kind):
    user = _account(space_modules=["team"])
    _as(client, store.new_session(user["id"]))
    resource = _ok(client.post(f"/api/{kind}", json=_body(kind)))
    field = "title" if kind in {"alerts", "conversations"} else "name"
    assert _ok(client.patch(f"/api/{kind}/{resource['id']}", json={field: "ordinary resource edit"}))[field] == "ordinary resource edit"
    assert any(item["id"] == resource["id"] for item in _ok(client.get(f"/api/{kind}")))
    _ok(client.delete(f"/api/{kind}/{resource['id']}"))
    assert store.get_entity(user["id"], kind, resource["id"]) is None
    assert _data(user["id"])["space_modules"] == ["team"]
    assert engine.TASKS == {} and _blobs() == {}


async def test_personal_owner_isolation_remains_enforced_with_spaces_enabled(client, monkeypatch):
    owner, other = _account(space_modules=list(MODULES)), _account(space_modules=list(MODULES))
    private, own = _seed_file(owner["id"]), _seed_file(other["id"], content=b"other owner evidence\n")
    _as(client, store.new_session(other["id"]))
    before, blobs = _snapshot(), _blobs()
    with monkeypatch.context() as patch:
        guards = _deny_blob_io(patch)
        _ok(client.get(f"/api/files/{private['id']}/download"), 404)
        _ok(client.delete(f"/api/files/{private['id']}"), 404)
        assert [file["id"] for file in _ok(client.get("/api/files"))] == [own["id"]]
        assert [file["id"] for file in await tools.execute(other["id"], None, "list_files", {})] == [own["id"]]
        with pytest.raises(tools.ToolError, match="不存在或没有权限"):
            await tools.execute(other["id"], None, "read_file", {"file_id": private["id"]})
        for guard in guards:
            guard.assert_not_called()
    assert _snapshot() == before and _blobs() == blobs


def test_disabling_and_reenabling_modules_preserves_file_ids_content_hashes_and_team_relationships(client, administrator):
    owner, member = _account(space_modules=list(MODULES)), _account()
    owner_token = store.new_session(owner["id"])
    _as(client, owner_token)
    space = _ok(client.post("/api/team-spaces", json={"name": "preserved team"}))
    _ok(client.post(f"/api/team-spaces/{space['id']}/members", json={"email": member["email"], "role": "editor"}))
    personal = _ok(client.post("/api/files", files={"file": ("personal.md", b"private unchanged evidence\n", "text/markdown")}))
    team_file = _ok(client.post(f"/api/team-spaces/{space['id']}/files", files={
        "file": ("team.md", b"shared unchanged evidence\n", "text/markdown"),
    }))
    relations = {table: _rows(table) for table in ("team_spaces", "team_members", "team_files")}
    private_rows, blobs = _rows("entities", "WHERE kind='files'"), _blobs()
    assert store.get_entity(owner["id"], "files", team_file["id"]) is None
    _as(client, administrator["token"])
    changed = _ok(client.patch(f"/api/admin/users/{owner['id']}", json={"space_modules": []}))
    assert changed["space_modules"] == [] and changed["team_invites_blocked"] is True
    _as(client, owner_token)
    for path in ("/api/files", f"/api/files/{personal['id']}/download", "/api/team-spaces", f"/api/team-spaces/{space['id']}/members"):
        _ok(client.get(path), 403)
    assert {table: _rows(table) for table in relations} == relations
    assert _rows("entities", "WHERE kind='files'") == private_rows and _blobs() == blobs
    _as(client, administrator["token"])
    changed = _ok(client.patch(f"/api/admin/users/{owner['id']}", json={"space_modules": ["team", "personal"]}))
    assert changed["space_modules"] == list(MODULES) and changed["team_invites_blocked"] is False
    _as(client, owner_token)
    assert [file["id"] for file in _ok(client.get("/api/files"))] == [personal["id"]]
    assert client.get(f"/api/files/{personal['id']}/download").content == b"private unchanged evidence\n"
    assert client.get(f"/api/team-spaces/{space['id']}/files/{team_file['id']}/download").content == b"shared unchanged evidence\n"
    assert {table: _rows(table) for table in relations} == relations
    assert _rows("entities", "WHERE kind='files'") == private_rows and _blobs() == blobs


@pytest.mark.parametrize("modules", [[], ["personal"]])
def test_invitation_can_enable_team_for_never_enabled_unblocked_account(client, administrator, modules):
    owner = _account(space_modules=["team"])
    target = _managed(client, space_modules=modules)
    assert target["team_invites_blocked"] is False
    _as(client, store.new_session(owner["id"]))
    space = _ok(client.post("/api/team-spaces", json={"name": "inviting team"}))
    added = _ok(client.post(f"/api/team-spaces/{space['id']}/members", json={"email": target["email"], "role": "viewer"}))
    assert added["user_id"] == target["id"]
    assert _data(target["id"])["space_modules"] == [*modules, "team"]
    assert _data(target["id"])["team_invites_blocked"] is False
    assert _data(target["id"])["allowed_control_levels"] == ["observe"]


def test_admin_disabled_team_blocks_reinvite_until_explicit_admin_reenable(client, administrator):
    owner, target = _account(space_modules=["team"]), _account(space_modules=list(MODULES))
    owner_token, target_token = store.new_session(owner["id"]), store.new_session(target["id"])
    _as(client, owner_token)
    space = _ok(client.post("/api/team-spaces", json={"name": "inviting team"}))
    _as(client, administrator["token"])
    changed = _ok(client.patch(f"/api/admin/users/{target['id']}", json={"space_modules": ["personal"]}))
    assert changed["team_invites_blocked"] is True
    _ok(client.patch(f"/api/admin/users/{target['id']}", json={"name": "unrelated edit"}))
    assert _data(target["id"])["team_invites_blocked"] is True
    _as(client, target_token)
    _ok(client.patch("/api/auth/me", json={"team_invites_blocked": False, "space_modules": list(MODULES)}))
    assert _data(target["id"])["space_modules"] == ["personal"]
    assert _data(target["id"])["team_invites_blocked"] is True
    _as(client, owner_token)
    before = _snapshot()
    _ok(client.post(f"/api/team-spaces/{space['id']}/members", json={"email": target["email"], "role": "viewer"}), 409)
    assert _snapshot() == before
    _as(client, administrator["token"])
    changed = _ok(client.patch(f"/api/admin/users/{target['id']}", json={"space_modules": ["team"]}))
    assert changed["space_modules"] == ["team"] and changed["team_invites_blocked"] is False
    _as(client, owner_token)
    assert _ok(client.post(f"/api/team-spaces/{space['id']}/members", json={
        "email": target["email"], "role": "viewer",
    }))["user_id"] == target["id"]


async def test_upload_rechecks_modules_after_await_and_leaves_no_new_blob_or_row(client, administrator, monkeypatch):
    user = _account(space_modules=list(MODULES))
    _seed_file(user["id"])
    token = store.new_session(user["id"])
    started, release = asyncio.Event(), asyncio.Event()
    original = main.uploaded_bytes

    async def delayed_bytes(file):
        content = await original(file)
        started.set()
        await release.wait()
        return content

    monkeypatch.setattr(main, "uploaded_bytes", delayed_bytes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver") as http:
        _as(http, token)
        pending = asyncio.create_task(http.post("/api/files", files={"file": ("revoked.md", b"must not save", "text/markdown")}))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            _as(http, administrator["token"])
            changed = _ok(await http.patch(f"/api/admin/users/{user['id']}", json={"space_modules": ["team"]}))
            assert changed["space_modules"] == ["team"]
            before, blobs = _snapshot(), _blobs()
            with monkeypatch.context() as patch:
                writes = Mock(side_effect=AssertionError("revoked upload must not create a blob"))
                patch.setattr(Path, "write_bytes", writes)
                release.set()
                _ok(await asyncio.wait_for(pending, timeout=3), 403)
                writes.assert_not_called()
            assert _snapshot() == before and _blobs() == blobs
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("failure", ["partial-blob", "metadata", "audit"])
async def test_upload_failure_cleans_only_new_blob_and_rolls_back_metadata(monkeypatch, failure):
    user = _account()
    _seed_file(user["id"])
    if failure != "partial-blob":
        table = "entities" if failure == "metadata" else "audit"
        condition = "NEW.kind='files'" if failure == "metadata" else "NEW.action='file.upload'"
        with store.connect() as db:
            db.execute(f"CREATE TRIGGER fail_upload BEFORE INSERT ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'local upload failure'); END")
    before, blobs = _snapshot(), _blobs()
    original = Path.write_bytes

    def partial_write(path, content):
        original(path, content[:4])
        raise OSError("local partial write failure")

    with monkeypatch.context() as patch:
        if failure == "partial-blob":
            patch.setattr(Path, "write_bytes", partial_write)
        with pytest.raises(OSError if failure == "partial-blob" else sqlite3.IntegrityError):
            await main.upload_file(UploadFile(
                io.BytesIO(b"new upload must be rolled back"), filename="new.md", headers=Headers({"content-type": "text/markdown"}),
            ), user=user)
    assert _snapshot() == before and _blobs() == blobs


async def test_personal_delete_commits_database_before_unlink(monkeypatch):
    user = _account()
    file = _seed_file(user["id"])
    original, unlinked = Path.unlink, []

    def after_commit(path, *args, **kwargs):
        db = sqlite3.connect(store.DB_PATH)
        try:
            assert db.execute("SELECT count(*) FROM entities WHERE id=?", (file["id"],)).fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM audit WHERE action='files.delete' AND resource=?", (file["id"],)).fetchone()[0] == 1
        finally:
            db.close()
        unlinked.append(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", after_commit)
    assert await main.remove("files", file["id"], user=user) == {"ok": True}
    assert unlinked == [file["storage_name"]]
    assert not (store.UPLOADS / file["storage_name"]).exists()


async def test_personal_delete_database_failure_does_not_unlink_existing_blob(monkeypatch):
    user = _account()
    file = _seed_file(user["id"])
    with store.connect() as db:
        db.execute("CREATE TRIGGER fail_delete BEFORE INSERT ON audit WHEN NEW.action='files.delete' BEGIN SELECT RAISE(ABORT, 'local delete failure'); END")
    before, blobs = _snapshot(), _blobs()
    with monkeypatch.context() as patch:
        unlink = Mock(side_effect=AssertionError("rolled back delete must keep its blob"))
        patch.setattr(Path, "unlink", unlink)
        with pytest.raises(sqlite3.IntegrityError):
            await main.remove("files", file["id"], user=user)
        unlink.assert_not_called()
    assert _snapshot() == before and _blobs() == blobs


@pytest.mark.parametrize("name", ["list_files", "read_file", "write_report"])
async def test_engine_rechecks_personal_after_model_response_before_file_tool(monkeypatch, name):
    user = _account()
    file = _seed_file(user["id"])
    run = _run(user["id"])
    args = {"file_id": file["id"]} if name == "read_file" else {"name": "denied.md", "content": "must not save"} if name == "write_report" else {}

    async def revoke_before_tool(*_):
        _set_user(user["id"], space_modules=["team"])
        return _tool_call(name, args)

    model = AsyncMock(side_effect=revoke_before_tool)
    execute = AsyncMock(wraps=tools.execute)
    monkeypatch.setattr(engine, "model_completion", model)
    monkeypatch.setattr(tools, "execute", execute)
    files, blobs = _rows("entities", "WHERE kind='files'"), _blobs()
    with monkeypatch.context() as patch:
        guards = _deny_blob_io(patch)
        await engine.run_agent(user["id"], run["id"])
        for guard in guards:
            guard.assert_not_called()
    model.assert_awaited_once()
    execute.assert_not_awaited()
    assert store.get_run(user["id"], run["id"])["status"] == "failed"
    assert not any(event["type"] == "tool_result" and event["data"].get("executed") for event in store.events(run["id"]))
    assert _rows("entities", "WHERE kind='files'") == files and _blobs() == blobs


@pytest.mark.parametrize("revoke", [False, True])
async def test_engine_report_cache_is_reused_only_while_personal_is_still_enabled(monkeypatch, revoke):
    user = _account()
    run = _run(user["id"])
    args = {"name": "cached-report.md", "content": "CACHE_REPORT_PRIVATE_CONTENT\n"}
    saved_files, saved_blobs = [], {}

    async def model_response(*_):
        if model.await_count == 1:
            return _tool_call("write_report", args, "first-report")
        if model.await_count == 2:
            saved_files.extend(_rows("entities", "WHERE kind='files'"))
            saved_blobs.update(_blobs())
            if revoke:
                _set_user(user["id"], space_modules=["team"])
            return _tool_call("write_report", args, "same-report-after-check")
        return dict(FINAL)

    model = AsyncMock(side_effect=model_response)
    execute = AsyncMock(wraps=tools.execute)
    monkeypatch.setattr(engine, "model_completion", model)
    monkeypatch.setattr(tools, "execute", execute)
    await engine.run_agent(user["id"], run["id"])
    execute.assert_awaited_once_with(user["id"], None, "write_report", args, None)
    assert len(saved_files) == 1 and len(saved_blobs) == 1
    assert _rows("entities", "WHERE kind='files'") == saved_files and _blobs() == saved_blobs
    events = store.events(run["id"])
    results = [event["data"] for event in events if event["type"] == "tool_result" and event["data"].get("name") == "write_report"]
    notices = [event["data"] for event in events if event["type"] == "notice" and event["data"].get("code") == "duplicate_write_reused"]
    assert results[0]["executed"] is True and results[0]["ok"] is True
    if revoke:
        assert model.await_count == 2
        assert store.get_run(user["id"], run["id"])["status"] == "failed"
        assert len(results) == 1 and notices == []
    else:
        assert model.await_count == 3
        assert store.get_run(user["id"], run["id"])["status"] == "completed"
        assert len(results) == 2 and results[1]["reused"] is True
        assert results[1]["output"] == results[0]["output"] and len(notices) == 1


async def test_missing_legacy_field_defaults_personal_without_implicit_persistent_self_grant(client):
    user = _account(legacy=True)
    file = _seed_file(user["id"])
    _as(client, store.new_session(user["id"]))
    assert access.enabled_spaces(user) == ["personal"]
    assert _ok(client.get("/api/auth/me"))["space_modules"] == ["personal"]
    assert [item["id"] for item in _ok(client.get("/api/files"))] == [file["id"]]
    assert client.get(f"/api/files/{file['id']}/download").content == b"unchanged personal evidence\n"
    assert (await tools.execute(user["id"], None, "read_file", {"file_id": file["id"]}))["content"] == "unchanged personal evidence\n"
    assert "space_modules" not in _data(user["id"])
    with pytest.raises(HTTPException) as rejected:
        access.require_space_owner(user["id"], "team")
    assert rejected.value.status_code == 403


def test_space_migration_backfills_missing_json_once_and_preserves_legacy_files_and_master_key(monkeypatch):
    key = Fernet.generate_key()
    key_file = store.DATA / "master.key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    monkeypatch.delenv("EARTHAI_MASTER_KEY")
    store._cipher.cache_clear()
    user = _account(legacy=True, legacy_settings={"keep": [1, False, "原值"]})
    _seed_file(user["id"], storage_name="legacy-personal-blob-key", content=b"legacy file content must not move\n")
    encrypted = store.seal("legacy-credential-offline-only")
    server = store.save_entity(user["id"], "servers", {**_body("servers"), "password": encrypted})
    explicit = [_account(space_modules=value) for value in ([], ["team"], list(MODULES), None, ["unknown"], {"personal": True})]
    before_users = _rows("users")
    entities, blobs = _rows("entities"), _blobs()
    assert _rows("platform_settings", "WHERE key='space_modules_v1'") == []
    access.initialize_spaces()
    current_users = {row[0]: row for row in _rows("users")}
    for row in before_users:
        after = current_users[row[0]]
        assert (after[0], after[1], after[2], after[4]) == (row[0], row[1], row[2], row[4])
        original, updated = store.loads(row[3]), store.loads(after[3])
        if "space_modules" in original:
            assert after == row
        else:
            assert updated == {**original, "space_modules": ["personal"]}
    for account in explicit:
        assert _data(account["id"])["space_modules"] == account["space_modules"]
    marker = _rows("platform_settings", "WHERE key='space_modules_v1'")
    assert len(marker) == 1 and store.loads(marker[0][1]) is True
    assert _rows("entities") == entities and _blobs() == blobs
    frozen = _snapshot()
    access.initialize_spaces()
    assert _snapshot() == frozen
    late_legacy = _account(legacy=True)
    frozen = _snapshot()
    access.initialize_spaces()
    assert _snapshot() == frozen and "space_modules" not in _data(late_legacy["id"])
    assert _rows("platform_settings", "WHERE key='space_modules_v1'") == marker
    assert key_file.read_bytes() == key and key_file.stat().st_mode & 0o777 == 0o600
    assert store.get_entity(user["id"], "servers", server["id"])["password"] == encrypted
    assert store.unseal(encrypted) == "legacy-credential-offline-only"
    assert _rows("entities") == entities and _blobs() == blobs
    with store.connect() as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("actorflag", ["role-user", "disabled", "must-change-password", "missing-user"])
async def test_change_users_rejects_stale_admin_before_target_grants_sessions_or_cancellation(
    client, administrator, monkeypatch, actorflag,
):
    stale_actor = _account(role="admin")
    target = _account(space_modules=list(MODULES), allowed_control_levels=["observe", "approve"])
    store.new_session(stale_actor["id"])
    target_token = store.new_session(target["id"])
    run = _run(target["id"])
    store.update_run(target["id"], run["id"], control_level="approve")
    if actorflag == "missing-user":
        with store.connect() as db:
            db.execute("DELETE FROM users WHERE id=?", (stale_actor["id"],))
    else:
        _set_user(stale_actor["id"], **{
            "role-user": {"role": "user"},
            "disabled": {"disabled": True},
            "must-change-password": {"must_change_password": True},
        }[actorflag])
    before, sessions = _snapshot(), _rows("sessions")
    cancel = Mock(side_effect=AssertionError("invalid admin must not cancel target runs"))
    proposals = Mock(wraps=admin.validate_account)
    monkeypatch.setattr(engine, "cancel_run", cancel)
    monkeypatch.setattr(admin, "validate_account", proposals)
    with pytest.raises(HTTPException) as rejected:
        await admin.change_users(stale_actor, [target["id"]], "update", {
            "allowed_control_levels": ["observe"], "space_modules": ["team"],
        })
    assert rejected.value.status_code == 403
    proposals.assert_not_called()
    cancel.assert_not_called()
    assert _snapshot() == before and _rows("sessions") == sessions
    assert store.user_for_token(target_token)["id"] == target["id"]


async def test_admin_patch_cannot_restore_own_role_after_downgrade_while_awaiting_body(client, administrator, monkeypatch):
    actor = _account(role="admin", space_modules=[])
    token = store.new_session(actor["id"])
    started, release = asyncio.Event(), asyncio.Event()
    body = {"role": "admin", "space_modules": list(MODULES), "allowed_control_levels": ["autonomous"]}

    async def receive():
        started.set()
        await release.wait()
        return {"type": "http.request", "body": store.dumps(body).encode(), "more_body": False}

    request = main.Request({
        "type": "http", "method": "PATCH", "path": f"/api/admin/users/{actor['id']}",
        "headers": [(b"cookie", f"earthai_session={token}".encode())],
    }, receive)
    stale_actor = main.current_admin(main.current_user(request))
    assert stale_actor["role"] == "admin"
    endpoint = next(route.endpoint for route in main.app.routes
                    if getattr(route, "path", None) == "/api/admin/users/{id_}" and "PATCH" in route.methods)
    cancel = Mock(side_effect=AssertionError("revoked admin must not cancel runs"))
    proposals = Mock(wraps=admin.validate_account)
    monkeypatch.setattr(engine, "cancel_run", cancel)
    monkeypatch.setattr(admin, "validate_account", proposals)
    pending = asyncio.create_task(endpoint(actor["id"], request, user=stale_actor))
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        _set_user(actor["id"], role="user")
        before, sessions = _snapshot(), _rows("sessions")
        release.set()
        with pytest.raises(HTTPException) as rejected:
            await asyncio.wait_for(pending, timeout=3)
        assert rejected.value.status_code == 403
        proposals.assert_not_called()
        cancel.assert_not_called()
        assert _snapshot() == before and _rows("sessions") == sessions
        assert _data(actor["id"])["role"] == "user"
        assert _data(actor["id"])["space_modules"] == []
        assert store.user_for_token(token)["role"] == "user"
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
