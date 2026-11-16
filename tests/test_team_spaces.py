import asyncio
import os
import sqlite3
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from itertools import count
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from backend import access, defaults, engine, guides, main, store, text_tools, tools, usage


PASSWORD = "Team-spaces-local-test-password!"
MAX_FILE = 20 * 1024 * 1024
CONTENT = "团队共享文件只保存内容，不运行模型或工具。\n".encode()


@pytest.fixture(scope="module")
def password_hash():
    return store.password_hash(PASSWORD)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    data = tmp_path / "data"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    for name, value in (("DATA_ROOT", data), ("DATA", data), ("UPLOADS", uploads), ("DB_PATH", data / "teams.db")):
        monkeypatch.setattr(store, name, value)
    monkeypatch.setattr(store, "_CONNECTIONS", {})
    monkeypatch.setattr(store, "_CONNECTION_LOCK", threading.Lock())
    monkeypatch.setattr(store, "_CONNECTION_LOCAL", threading.local())
    for name, value in {
        "EARTHAI_DATA_DIR": str(data), "EARTHAI_STATE_DIR": str(data), "EARTHAI_UPLOADS_DIR": str(uploads),
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
        (httpx.HTTPTransport, "handle_request", Mock(side_effect=AssertionError("unexpected external HTTP"))),
        (httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(side_effect=AssertionError("unexpected external HTTP"))),
    ]
    for module, name, replacement in blocked:
        monkeypatch.setattr(module, name, replacement)
    store.init_db()
    defaults.init_tables()
    guides.initialize()
    usage.initialize()
    try:
        yield data
    finally:
        store.close_connections()
        for _, name, replacement in blocked:
            assert replacement.call_count == 0, name
        assert engine.TASKS == {} and engine.CANCEL_TOKENS == {}


@pytest.fixture
def client(isolated_store):
    # Schema is isolated explicitly; omitting lifespan also avoids starting the scheduler.
    http = TestClient(main.app, raise_server_exceptions=False)
    try:
        yield http
    finally:
        http.close()


@pytest.fixture
def account(isolated_store, password_hash):
    serial = count()

    def create(**changes):
        index = next(serial)
        email = changes.pop("email", f"team-{index}@example.test")
        user_id = store.uid()
        data = {
            "name": f"Team user {index}", "role": "user", "disabled": False, "must_change_password": False,
            "allowed_control_levels": ["observe"], "control_level": "observe", "theme": "light",
            "space_modules": ["personal", "team"], "team_invites_blocked": False, **changes,
        }
        with store.connect() as db:
            db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (user_id, email, password_hash, store.dumps(data), store.now()))
        return {"id": user_id, "email": email, **data, "token": store.new_session(user_id)}

    return create


@pytest.fixture
def administrator(account):
    return account(email="team-platform-admin", role="admin", space_modules=[])


@pytest.fixture
def team(client, account):
    people = {role: account() for role in ("owner", "manager", "peer_manager", "editor", "viewer", "outsider")}
    space = _space(client, people["owner"])
    for key, role in (("manager", "manager"), ("peer_manager", "manager"), ("editor", "editor"), ("viewer", "viewer")):
        _invite(client, people["owner"], space, people[key], role)
    shared = _upload(client, people["owner"], space)
    return {**people, "space": space, "file": shared}


def _base(admin=False):
    return "/api/admin/team-spaces" if admin else "/api/team-spaces"


def _url(space, suffix="", *, admin=False):
    return f"{_base(admin)}/{space['id']}{suffix}"


def _request(client, actor, method, path, **kwargs):
    client.cookies.clear()
    if actor is not None:
        client.cookies.set("earthai_session", actor["token"])
    return client.request(method, path, **kwargs)


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _denied(response, statuses=(403, 404)):
    assert response.status_code in statuses, response.text


def _space(client, owner, name="共享团队", *, admin=False, **changes):
    return _ok(_request(client, owner, "POST", _base(admin), json={"name": name, "description": "本地合约测试", **changes}))


def _invite(client, actor, space, target, role="viewer", *, admin=False):
    return _ok(_request(client, actor, "POST", _url(space, "/members", admin=admin), json={"email": target["email"], "role": role}))


def _upload(client, actor, space, content=CONTENT, name="shared.txt", *, admin=False):
    return _ok(_request(client, actor, "POST", _url(space, "/files", admin=admin), files={"file": (name, content, "text/plain")}))


def _user_data(user):
    with store.connect() as db:
        return store.loads(db.execute("SELECT data FROM users WHERE id=?", (user["id"],)).fetchone()[0])


def _set_user(user, **changes):
    with store.connect() as db:
        data = store.loads(db.execute("SELECT data FROM users WHERE id=?", (user["id"],)).fetchone()[0])
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps({**data, **changes}), user["id"]))


def _file_row(shared):
    with store.connect() as db:
        row = db.execute("SELECT * FROM team_files WHERE id=?", (shared["id"],)).fetchone()
        assert row is not None
        return dict(row)


def _blob(shared):
    return store.UPLOADS / _file_row(shared)["storage_name"]


def _members(space):
    with store.connect() as db:
        return {row["user_id"]: row["role"] for row in db.execute("SELECT user_id,role FROM team_members WHERE space_id=?", (space["id"],))}


def _snapshot():
    with store.connect() as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
        )]
        return {table: sorted((tuple(row) for row in db.execute(f'SELECT * FROM "{table}"')), key=repr) for table in tables}


def _blobs():
    return {str(path.relative_to(store.UPLOADS)): path.read_bytes() for path in store.UPLOADS.rglob("*") if path.is_file()}


def _state():
    return _snapshot(), _blobs()


def _public(value):
    if isinstance(value, dict):
        assert "storage_name" not in value and "password" not in value
        for child in value.values():
            _public(child)
    elif isinstance(value, list):
        for child in value:
            _public(child)


def _audit_failure(action):
    with store.connect() as db:
        db.execute(f"""CREATE TRIGGER fail_team_audit BEFORE INSERT ON audit
            WHEN NEW.action='{action}' BEGIN SELECT RAISE(ABORT,'test-only audit failure'); END""")


def test_init_db_initializes_team_tables_and_reinitialization_preserves_rows(client, team):
    before = _state()
    store.init_db()
    assert _state() == before
    with store.connect() as db:
        assert {"team_spaces", "team_members", "team_files"} <= set(before[0])
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        member_keys = {row["from"]: row["on_delete"] for row in db.execute("PRAGMA foreign_key_list(team_members)")}
        file_keys = {row["from"]: row["on_delete"] for row in db.execute("PRAGMA foreign_key_list(team_files)")}
    assert member_keys["user_id"] == "CASCADE"
    assert file_keys["uploader_id"] == "SET NULL"
    assert _members(team["space"])[team["owner"]["id"]] == "owner"


def test_registration_defaults_personal_and_profile_cannot_self_enable_team(client):
    user = _ok(client.post("/api/auth/register", json={
        "email": "registered-team@example.test", "password": PASSWORD, "space_modules": ["team"], "team_invites_blocked": False,
    }))
    assert user["space_modules"] == ["personal"]
    assert _ok(client.get("/api/auth/me"))["space_modules"] == ["personal"]
    changed = _ok(client.patch("/api/auth/me", json={"name": "仍是普通用户", "space_modules": ["personal", "team"]}))
    assert changed["space_modules"] == ["personal"]
    assert _user_data(user)["space_modules"] == ["personal"]
    _ok(client.get("/api/files"))
    _ok(client.get(_base()), 403)
    _ok(client.post(_base(), json={"name": "不得自启"}), 403)


def test_legacy_missing_space_modules_defaults_personal_but_explicit_empty_stays_empty(client, account):
    legacy, empty = account(), account(space_modules=[])
    with store.connect() as db:
        data = _user_data(legacy)
        data.pop("space_modules")
        db.execute("UPDATE users SET data=? WHERE id=?", (store.dumps(data), legacy["id"]))
    assert _ok(_request(client, legacy, "GET", "/api/auth/me"))["space_modules"] == ["personal"]
    _ok(_request(client, legacy, "GET", "/api/files"))
    _ok(_request(client, legacy, "GET", _base()), 403)
    assert _ok(_request(client, empty, "GET", "/api/auth/me"))["space_modules"] == []
    for path in ("/api/files", _base()):
        _ok(_request(client, empty, "GET", path), 403)
    assert "space_modules" not in _user_data(legacy)
    assert _user_data(empty)["space_modules"] == []


@pytest.mark.parametrize("modules", [[], ["personal"], ["team"], ["team", "personal"]])
def test_admin_account_space_modules_accept_exact_subsets_in_create_patch_and_batch(client, administrator, account, modules):
    created = _ok(_request(client, administrator, "POST", "/api/admin/users", json={
        "email": "managed-team", "name": "Managed", "password": PASSWORD, "space_modules": modules,
    }))
    expected = [module for module in ("personal", "team") if module in modules]
    assert created["space_modules"] == _user_data(created)["space_modules"] == expected
    other = account()
    assert _ok(_request(client, administrator, "PATCH", f"/api/admin/users/{other['id']}", json={"space_modules": modules}))["space_modules"] == expected
    assert _ok(_request(client, administrator, "POST", "/api/admin/users/batch", json={
        "ids": [created["id"], other["id"]], "action": "update", "changes": {"space_modules": modules},
    }))["count"] == 2
    assert _user_data(other)["space_modules"] == expected


@pytest.mark.parametrize("modules", [None, "team", True, ["Team"], ["unknown"], ["team", "team"], [False], ["personal", None]])
def test_invalid_space_modules_reject_whole_admin_write_without_side_effects(client, administrator, account, modules):
    one, two = account(), account()
    before = _state()
    for method, path, body in (
        ("POST", "/api/admin/users", {"email": "bad-spaces", "name": "Invalid", "password": PASSWORD, "space_modules": modules}),
        ("PATCH", f"/api/admin/users/{one['id']}", {"name": "不应改名", "space_modules": modules}),
        ("POST", "/api/admin/users/batch", {"ids": [one["id"], two["id"]], "action": "update",
                                              "changes": {"name": "不应改名", "space_modules": modules}}),
    ):
        _ok(_request(client, administrator, method, path, json=body), 422)
        assert _state() == before


def test_admin_created_account_also_defaults_personal(client, administrator):
    user = _ok(_request(client, administrator, "POST", "/api/admin/users", json={
        "email": "default-spaces", "name": "Default", "password": PASSWORD,
    }))
    assert user["space_modules"] == ["personal"]
    assert user["team_invites_blocked"] is False


@pytest.mark.parametrize("admin", [False, True])
def test_anonymous_team_routes_require_authentication(client, admin):
    before = _state()
    for method, path, kwargs in (
        ("GET", _base(admin), {}), ("POST", _base(admin), {"json": {"name": "No session"}}),
        ("GET", _base(admin) + "/missing", {}),
        ("POST", _base(admin) + "/missing/files", {"files": {"file": ("private.txt", CONTENT)}}),
    ):
        _ok(_request(client, None, method, path, **kwargs), 401)
        assert _state() == before


def test_create_space_sets_current_user_as_unique_owner_and_lists_only_memberships(client, account):
    owner, other = account(), account()
    first = _space(client, owner, "  我的空间  ")
    second = _space(client, other, "其他空间")
    assert first["name"] == "我的空间" and first["owner_id"] == owner["id"] and first["role"] == "owner"
    assert first["member_count"] == 1 and first["file_count"] == first["total_size"] == 0
    assert _members(first) == {owner["id"]: "owner"}
    assert [item["id"] for item in _ok(_request(client, owner, "GET", _base()))] == [first["id"]]
    assert [item["id"] for item in _ok(_request(client, other, "GET", _base()))] == [second["id"]]
    _public(first)
    before = _state()
    _ok(_request(client, owner, "POST", _base(), json={"name": "伪造", "owner_id": other["id"]}), 422)
    assert _state() == before


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": " "}, {"name": False}, {"name": "x", "role": "owner"},
                                       {"name": "x", "description": []}, {"name": "x" * 201}])
def test_invalid_space_create_is_atomic(client, account, body):
    owner = account()
    before = _state()
    _ok(_request(client, owner, "POST", _base(), json=body), 422)
    assert _state() == before


def test_nonmember_cannot_read_or_mutate_even_with_known_space_member_and_file_ids(client, team):
    space, shared, outsider = team["space"], team["file"], team["outsider"]
    before = _state()
    calls = [
        ("GET", "", {}), ("GET", "/members", {}), ("GET", "/files", {}),
        ("GET", f"/files/{shared['id']}", {}), ("GET", f"/files/{shared['id']}/download", {}),
        ("PATCH", "", {"json": {"name": "越权"}}), ("DELETE", "", {}), ("POST", "/restore", {}),
        ("POST", "/members", {"json": {"email": outsider["email"], "role": "viewer"}}),
        ("PATCH", f"/members/{team['viewer']['id']}", {"json": {"role": "editor"}}),
        ("DELETE", f"/members/{team['viewer']['id']}", {}),
        ("POST", "/files", {"files": {"file": ("denied.txt", CONTENT)}}),
        ("PATCH", f"/files/{shared['id']}", {"json": {"name": "denied.txt"}}),
        ("PUT", f"/files/{shared['id']}/content", {"files": {"file": ("denied.txt", CONTENT)}}),
        ("DELETE", f"/files/{shared['id']}", {}),
        ("POST", "/transfer", {"json": {"user_id": outsider["id"]}}),
    ]
    for method, suffix, kwargs in calls:
        _denied(_request(client, outsider, method, _url(space, suffix), **kwargs))
        assert _state() == before
    assert _ok(_request(client, outsider, "GET", _base())) == []


@pytest.mark.parametrize("role", ["owner", "manager", "editor", "viewer"])
def test_members_can_read_shared_metadata_members_files_and_download_without_execution(client, team, role):
    actor, space, shared = team[role], team["space"], team["file"]
    before = _state()
    metadata = _ok(_request(client, actor, "GET", _url(space)))
    assert metadata["role"] == role and metadata["member_count"] == 5
    assert metadata["file_count"] == 1 and metadata["total_size"] == len(CONTENT)
    for suffix in ("/members", "/files", f"/files/{shared['id']}"):
        _public(_ok(_request(client, actor, "GET", _url(space, suffix))))
    files = _ok(_request(client, actor, "GET", _url(space, "/files")))
    assert [item["id"] for item in files] == [shared["id"]]
    downloaded = _request(client, actor, "GET", _url(space, f"/files/{shared['id']}/download"))
    assert downloaded.status_code == 200 and downloaded.content == CONTENT
    assert "attachment" in downloaded.headers["content-disposition"]
    assert _file_row(shared)["storage_name"] not in downloaded.headers["content-disposition"]
    assert _state() == before
    with store.connect() as db:
        for table in ("runs", "messages", "events", "approvals", "resource_usage", "documents", "chunks"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM entities WHERE kind='files'").fetchone()[0] == 0


@pytest.mark.parametrize("role", ["owner", "manager", "editor"])
def test_file_writers_can_crud_files_uploaded_by_another_member(client, team, role):
    actor, space, shared = team[role], team["space"], team["file"]
    original = _blob(shared)
    uploaded = _upload(client, actor, space, b"second payload", name=shared["name"])
    assert uploaded["id"] != shared["id"] and _blob(uploaded) != original
    renamed = _ok(_request(client, actor, "PATCH", _url(space, f"/files/{shared['id']}"), json={"name": "renamed.txt"}))
    assert renamed["id"] == shared["id"] and renamed["name"] == "renamed.txt"
    assert _blob(shared) == original and original.read_bytes() == CONTENT
    replaced = _ok(_request(client, actor, "PUT", _url(space, f"/files/{shared['id']}/content"), files={
        "file": ("ignored-new-name.txt", b"replacement payload", "application/octet-stream"),
    }))
    assert replaced["id"] == shared["id"] and replaced["name"] == "renamed.txt"
    assert replaced["size"] == len(b"replacement payload")
    assert replaced["created_at"] == shared["created_at"] and replaced["uploader_id"] == shared["uploader_id"]
    replacement = _blob(shared)
    assert replacement != original and not original.exists() and replacement.read_bytes() == b"replacement payload"
    assert _request(client, actor, "GET", _url(space, f"/files/{shared['id']}/download")).content == b"replacement payload"
    _ok(_request(client, actor, "DELETE", _url(space, f"/files/{shared['id']}")))
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM team_files WHERE id=?", (shared["id"],)).fetchone() is None
    assert not replacement.exists()
    assert _blob(uploaded).read_bytes() == b"second payload"
    _ok(_request(client, actor, "GET", _url(space, f"/files/{shared['id']}/download")), 404)
    _public([uploaded, renamed, replaced])


def test_viewer_file_writes_are_denied_without_blob_or_database_changes(client, team):
    actor, space, shared = team["viewer"], team["space"], team["file"]
    before = _state()
    for method, suffix, kwargs in (
        ("POST", "/files", {"files": {"file": ("blocked.txt", CONTENT)}}),
        ("PATCH", f"/files/{shared['id']}", {"json": {"name": "blocked.txt"}}),
        ("PUT", f"/files/{shared['id']}/content", {"files": {"file": ("blocked.txt", CONTENT)}}),
        ("DELETE", f"/files/{shared['id']}", {}),
    ):
        _ok(_request(client, actor, method, _url(space, suffix), **kwargs), 403)
        assert _state() == before


@pytest.mark.parametrize("role", ["viewer", "editor"])
def test_nonmanagers_cannot_manage_metadata_members_archive_transfer_or_restore(client, team, account, role):
    actor, space, target = team[role], team["space"], account(space_modules=[])
    before = _state()
    for method, suffix, body in (
        ("PATCH", "", {"name": "不能改名"}),
        ("POST", "/members", {"email": target["email"], "role": "viewer"}),
        ("PATCH", f"/members/{team['manager']['id']}", {"role": "editor"}),
        ("DELETE", f"/members/{team['manager']['id']}", None),
        ("DELETE", "", None), ("POST", "/restore", None),
        ("POST", "/transfer", {"user_id": team["viewer"]["id"]}),
    ):
        _ok(_request(client, actor, method, _url(space, suffix), **({"json": body} if body is not None else {})), 403)
        assert _state() == before
    assert _user_data(target)["space_modules"] == []


@pytest.mark.parametrize("initial", ["viewer", "editor"])
def test_manager_can_edit_space_and_add_edit_remove_viewers_and_editors(client, team, account, initial):
    manager, space, target = team["manager"], team["space"], account(space_modules=["personal"])
    changed = _ok(_request(client, manager, "PATCH", _url(space), json={"name": "管理者更新", "description": "新描述"}))
    assert changed["name"] == "管理者更新" and changed["description"] == "新描述"
    assert _invite(client, manager, space, target, initial)["role"] == initial
    other = "editor" if initial == "viewer" else "viewer"
    assert _ok(_request(client, manager, "PATCH", _url(space, f"/members/{target['id']}"), json={"role": other}))["role"] == other
    _ok(_request(client, manager, "DELETE", _url(space, f"/members/{target['id']}")))
    assert target["id"] not in _members(space)
    assert _user_data(target)["space_modules"] == ["personal", "team"]


def test_manager_cannot_grant_or_modify_managers_owner_transfer_or_archive(client, team, account):
    actor, space, target = team["manager"], team["space"], account(space_modules=[])
    before = _state()
    for method, suffix, body in (
        ("POST", "/members", {"email": target["email"], "role": "manager"}),
        ("PATCH", f"/members/{team['viewer']['id']}", {"role": "manager"}),
        ("PATCH", f"/members/{team['peer_manager']['id']}", {"role": "viewer"}),
        ("PATCH", f"/members/{actor['id']}", {"role": "editor"}),
        ("DELETE", f"/members/{team['peer_manager']['id']}", None),
        ("PATCH", f"/members/{team['owner']['id']}", {"role": "viewer"}),
        ("DELETE", f"/members/{team['owner']['id']}", None),
        ("POST", "/transfer", {"user_id": team["viewer"]["id"]}),
        ("DELETE", "", None), ("POST", "/restore", None),
    ):
        _denied(_request(client, actor, method, _url(space, suffix), **({"json": body} if body is not None else {})), (403, 409))
        assert _state() == before


def test_owner_can_grant_change_and_remove_managers_but_cannot_create_another_owner(client, team, account):
    owner, space, target = team["owner"], team["space"], account()
    assert _invite(client, owner, space, target, "manager")["role"] == "manager"
    assert _ok(_request(client, owner, "PATCH", _url(space, f"/members/{team['viewer']['id']}"), json={"role": "manager"}))["role"] == "manager"
    assert _ok(_request(client, owner, "PATCH", _url(space, f"/members/{target['id']}"), json={"role": "viewer"}))["role"] == "viewer"
    _ok(_request(client, owner, "DELETE", _url(space, f"/members/{team['peer_manager']['id']}")))
    before = _state()
    for method, suffix, body in (
        ("POST", "/members", {"email": team["outsider"]["email"], "role": "owner"}),
        ("PATCH", f"/members/{target['id']}", {"role": "owner"}),
    ):
        _ok(_request(client, owner, method, _url(space, suffix), json=body), 422)
        assert _state() == before
    assert list(_members(space).values()).count("owner") == 1


@pytest.mark.parametrize("admin", [False, True])
def test_owner_cannot_be_removed_downgraded_or_leave_through_ordinary_member_operations(client, team, administrator, admin):
    actor, space, owner = administrator if admin else team["owner"], team["space"], team["owner"]
    before = _state()
    for method, suffix, kwargs in (
        ("PATCH", f"/members/{owner['id']}", {"json": {"role": "manager"}}),
        ("DELETE", f"/members/{owner['id']}", {}),
    ):
        _ok(_request(client, actor, method, _url(space, suffix, admin=admin), **kwargs), 409)
        assert _state() == before
    if not admin:
        _ok(_request(client, actor, "POST", _url(space, "/leave")), 409)
        assert _state() == before


@pytest.mark.parametrize("role", ["viewer", "editor", "manager"])
@pytest.mark.parametrize("surface", ["leave", "delete-self"])
def test_nonowner_can_leave_without_disabling_team_or_deleting_uploaded_content(client, account, role, surface):
    owner, actor = account(), account()
    space = _space(client, owner)
    _invite(client, owner, space, actor, "editor")
    shared = _upload(client, actor, space)
    _ok(_request(client, owner, "PATCH", _url(space, f"/members/{actor['id']}"), json={"role": role}))
    path, data = _blob(shared), _user_data(actor)
    method, suffix = ("POST", "/leave") if surface == "leave" else ("DELETE", f"/members/{actor['id']}")
    _ok(_request(client, actor, method, _url(space, suffix)))
    assert actor["id"] not in _members(space) and _user_data(actor) == data
    assert _file_row(shared)["uploader_id"] == actor["id"] and path.read_bytes() == CONTENT
    _denied(_request(client, actor, "GET", _url(space)))
    assert _request(client, owner, "GET", _url(space, f"/files/{shared['id']}/download")).content == CONTENT


def test_invite_auto_grants_team_union_without_touching_personal_files_other_users_or_grants(client, account):
    owner = account()
    target = account(space_modules=["personal"], allowed_control_levels=["approve", "autonomous"], control_level="autonomous",
                     chat_preferences={"control_level": "autonomous", "model": "private-choice"}, custom_marker={"keep": True})
    unrelated = account(space_modules=[])
    personal = _ok(_request(client, target, "POST", "/api/files", files={"file": ("personal.txt", b"private payload")}))
    private = store.get_entity(target["id"], "files", personal["id"])
    assert private is not None
    private_path = store.UPLOADS / private["storage_name"]
    other_before = _user_data(unrelated)
    before_data = _user_data(target)
    space = _space(client, owner)
    member = _invite(client, owner, space, target, "editor")
    assert member["user_id"] == target["id"] and member["team_module_enabled"] is True
    assert _user_data(target) == {**before_data, "space_modules": ["personal", "team"]}
    assert _user_data(unrelated) == other_before
    assert store.get_entity(target["id"], "files", personal["id"]) == private
    assert private_path.read_bytes() == b"private payload"
    assert _ok(_request(client, target, "GET", "/api/auth/me"))["space_modules"] == ["personal", "team"]
    assert _ok(_request(client, target, "GET", _url(space)))["role"] == "editor"
    assert _request(client, target, "GET", f"/api/files/{personal['id']}/download").content == b"private payload"


def test_already_enabled_invitee_is_not_regranted_or_rewritten(client, account):
    owner, target = account(), account(space_modules=["team"], allowed_control_levels=["autonomous"], control_level="autonomous")
    spaces = [_space(client, owner, name) for name in ("First", "Second")]
    before_data = _user_data(target)
    with store.connect() as db:
        before_audits = db.execute("SELECT count(*) FROM audit WHERE action='team.module.enable'").fetchone()[0]
    for space in spaces:
        _invite(client, owner, space, target)
    assert _user_data(target) == before_data
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE action='team.module.enable'").fetchone()[0] == before_audits


@pytest.mark.parametrize("blocked", [False, True])
def test_duplicate_invite_409_cannot_regrant_module_or_produce_any_side_effect(client, team, blocked):
    target, space = team["viewer"], team["space"]
    _set_user(target, space_modules=["personal"], team_invites_blocked=blocked)
    before = _state()
    _ok(_request(client, team["owner"], "POST", _url(space, "/members"), json={"email": target["email"], "role": "editor"}), 409)
    assert _state() == before
    assert _members(space)[target["id"]] == "viewer"


@pytest.mark.parametrize("flags", [{"disabled": True}, {"must_change_password": True}, {"role": "admin"}])
def test_invites_reject_inactive_initial_password_and_admin_targets_without_grants(client, account, flags):
    owner, target = account(), account(space_modules=[], **flags)
    space = _space(client, owner)
    before = _state()
    _denied(_request(client, owner, "POST", _url(space, "/members"), json={"email": target["email"], "role": "viewer"}), (403, 404, 409))
    assert _state() == before


def test_invite_requires_exact_existing_email_and_does_not_publish_all_user_search(client, account):
    owner, target = account(), account(space_modules=[])
    space = _space(client, owner)
    before = _state()
    for email in ("unknown@example.test", target["email"].split("@")[0], target["name"], target["id"]):
        _denied(_request(client, owner, "POST", _url(space, "/members"), json={"email": email, "role": "viewer"}), (404, 422))
        assert _state() == before
    for path in ("/api/users", "/api/users/search?q=team", "/api/admin/users", _url(space, "/users?query=team")):
        _denied(_request(client, owner, "GET", path))
        assert _state() == before
    assert _invite(client, owner, space, target)["user_id"] == target["id"]


@pytest.mark.parametrize("body", [{"email": "a@example.test"}, {"role": "viewer"}, {"email": "", "role": "viewer"},
                                       {"email": "a@example.test", "role": "root"}, {"email": "a@example.test", "role": True},
                                       {"email": "a@example.test", "role": "viewer", "user_id": "forged"}])
def test_member_input_validation_never_writes_or_grants(client, team, body):
    before = _state()
    _ok(_request(client, team["owner"], "POST", _url(team["space"], "/members"), json=body), 422)
    assert _state() == before


def test_explicit_admin_team_revocation_blocks_new_invites_until_admin_reenables(client, account, administrator):
    owner, target = account(), account()
    first, second = _space(client, owner), _space(client, owner, "Second")
    _invite(client, owner, first, target)
    closed = _ok(_request(client, administrator, "PATCH", f"/api/admin/users/{target['id']}", json={"space_modules": ["personal"]}))
    assert closed["team_invites_blocked"] is True and closed["space_modules"] == ["personal"]
    before = _state()
    for actor, admin in ((owner, False), (administrator, True)):
        _ok(_request(client, actor, "POST", _url(second, "/members", admin=admin), json={"email": target["email"], "role": "viewer"}), 409)
        assert _state() == before
    assert _members(first)[target["id"]] == "viewer" and target["id"] not in _members(second)
    reopened = _ok(_request(client, administrator, "PATCH", f"/api/admin/users/{target['id']}", json={"space_modules": ["personal", "team"]}))
    assert reopened["team_invites_blocked"] is False
    assert _invite(client, owner, second, target)["user_id"] == target["id"]


def test_transfer_promotes_member_demotes_previous_owner_and_enforces_new_permissions_immediately(client, team):
    space, old, new = team["space"], team["owner"], team["viewer"]
    result = _ok(_request(client, old, "POST", _url(space, "/transfer"), json={"user_id": new["id"]}))
    assert result["owner_id"] == new["id"] and result["role"] == "manager"
    roles = _members(space)
    assert roles[old["id"]] == "manager" and roles[new["id"]] == "owner" and list(roles.values()).count("owner") == 1
    for method, suffix, body in (("DELETE", "", None), ("POST", "/transfer", {"user_id": team["editor"]["id"]})):
        before = _state()
        _ok(_request(client, old, method, _url(space, suffix), **({"json": body} if body is not None else {})), 403)
        assert _state() == before
    _ok(_request(client, old, "PATCH", _url(space), json={"name": "旧所有者仍是管理者"}))
    _ok(_request(client, new, "DELETE", _url(space)))
    assert _ok(_request(client, new, "POST", _url(space, "/restore")))["owner_id"] == new["id"]


@pytest.mark.parametrize("modules", [[], ["personal"]])
def test_transfer_auto_enables_unblocked_existing_member_without_losing_other_grants(client, team, modules):
    target, space = team["viewer"], team["space"]
    _set_user(target, space_modules=modules, team_invites_blocked=False, allowed_control_levels=["approve"], control_level="approve")
    before_data = _user_data(target)
    changed = _ok(_request(client, team["owner"], "POST", _url(space, "/transfer"), json={"user_id": target["id"]}))
    assert changed["owner_id"] == target["id"]
    assert _user_data(target) == {**before_data, "space_modules": [*modules, "team"]}
    assert _ok(_request(client, target, "GET", _url(space)))["role"] == "owner"


@pytest.mark.parametrize("reason", ["nonmember", "self", "disabled", "must_change_password", "admin", "blocked"])
def test_invalid_transfer_targets_leave_owner_members_modules_and_audit_unchanged(client, team, reason):
    space = team["space"]
    target = team["outsider"] if reason == "nonmember" else team["owner"] if reason == "self" else team["viewer"]
    if reason == "admin":
        _set_user(target, role="admin")
    elif reason in {"disabled", "must_change_password"}:
        _set_user(target, **{reason: True})
    elif reason == "blocked":
        _set_user(target, space_modules=[], team_invites_blocked=True)
    before = _state()
    _denied(_request(client, team["owner"], "POST", _url(space, "/transfer"), json={"user_id": target["id"]}), (403, 404, 409))
    assert _state() == before


def test_concurrent_transfers_from_same_old_owner_commit_only_one_new_owner(client, team):
    space, old = team["space"], team["owner"]
    targets = [team["viewer"], team["editor"]]
    for target in targets:
        _set_user(target, space_modules=[], team_invites_blocked=False)
    barrier = threading.Barrier(2)

    def transfer(target):
        http = TestClient(main.app, raise_server_exceptions=False)
        try:
            barrier.wait(timeout=5)
            response = _request(http, old, "POST", _url(space, "/transfer"), json={"user_id": target["id"]})
            return target, response.status_code, response.text
        finally:
            http.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(transfer, targets))
    assert sum(status == 200 for _, status, _ in results) == 1, results
    assert all(status in {200, 403, 409} for _, status, _ in results), results
    winner = next(target for target, status, _ in results if status == 200)
    loser = next(target for target, status, _ in results if status != 200)
    roles = _members(space)
    assert roles[old["id"]] == "manager" and roles[winner["id"]] == "owner"
    assert list(roles.values()).count("owner") == 1
    assert _user_data(winner)["space_modules"] == ["team"] and _user_data(loser)["space_modules"] == []
    with store.connect() as db:
        assert db.execute("SELECT owner_id FROM team_spaces WHERE id=?", (space["id"],)).fetchone()[0] == winner["id"]
        assert db.execute("SELECT count(*) FROM audit WHERE action='team.space.transfer' AND resource=?", (space["id"],)).fetchone()[0] == 1


@pytest.mark.parametrize("admin", [False, True])
def test_archive_is_not_purge_and_requires_restore_before_member_file_writes_or_download(client, team, administrator, account, admin):
    space, shared, actor = team["space"], team["file"], administrator if admin else team["owner"]
    target = account(space_modules=[])
    members, row, path = _members(space), _file_row(shared), _blob(shared)
    _ok(_request(client, actor, "DELETE", _url(space, admin=admin)))
    assert _members(space) == members and _file_row(shared) == row and path.read_bytes() == CONTENT
    assert _ok(_request(client, actor, "GET", _url(space, admin=admin)))["archived"] is True
    assert space["id"] not in {item["id"] for item in _ok(_request(client, actor, "GET", _base(admin)))}
    archived = _ok(_request(client, actor, "GET", _base(admin) + "?include_archived=true"))
    assert next(item for item in archived if item["id"] == space["id"])["archived"] is True
    assert _ok(_request(client, team["viewer"], "GET", _url(space)))["archived"] is True
    _public(_ok(_request(client, team["viewer"], "GET", _url(space, "/members"))))
    before = _state()
    for method, suffix, kwargs in (
        ("PATCH", "", {"json": {"name": "必须先恢复"}}),
        ("POST", "/members", {"json": {"email": target["email"], "role": "viewer"}}),
        ("PATCH", f"/members/{team['viewer']['id']}", {"json": {"role": "editor"}}),
        ("DELETE", f"/members/{team['viewer']['id']}", {}),
        ("POST", "/files", {"files": {"file": ("blocked.txt", CONTENT)}}),
        ("PATCH", f"/files/{shared['id']}", {"json": {"name": "blocked.txt"}}),
        ("PUT", f"/files/{shared['id']}/content", {"files": {"file": ("blocked.txt", CONTENT)}}),
        ("DELETE", f"/files/{shared['id']}", {}),
        ("GET", f"/files/{shared['id']}/download", {}),
    ):
        _ok(_request(client, actor, method, _url(space, suffix, admin=admin), **kwargs), 409)
        assert _state() == before
    _ok(_request(client, team["viewer"], "GET", _url(space, f"/files/{shared['id']}/download")), 409)
    _ok(_request(client, team["manager"], "POST", _url(space, "/restore")), 403)
    restored = _ok(_request(client, actor, "POST", _url(space, "/restore", admin=admin)))
    assert restored["archived"] is False and _members(space) == members and _file_row(shared) == row
    assert _request(client, team["viewer"], "GET", _url(space, f"/files/{shared['id']}/download")).content == CONTENT


@pytest.mark.parametrize("admin", [False, True])
def test_archived_space_transfer_requires_restore_even_for_global_admin(client, team, administrator, admin):
    space, owner, target = team["space"], team["owner"], team["viewer"]
    _ok(_request(client, owner, "DELETE", _url(space)))
    before = _state()
    actor = administrator if admin else owner
    response = _request(client, actor, "POST", _url(space, "/transfer", admin=admin), json={"user_id": target["id"]})
    _ok(response, 409)
    assert _state() == before


def test_team_blobs_are_flat_unique_uuid_names_and_never_exposed_as_public_storage_names(client, team):
    first = team["file"]
    second = _upload(client, team["editor"], team["space"], b"independent payload", "../../shared.txt")
    assert second["name"] == "shared.txt" and second["id"] != first["id"]
    names = {_file_row(value)["storage_name"] for value in (first, second)}
    assert len(names) == 2
    for name in names:
        assert Path(name).name == name and name.startswith("team-")
        UUID(name.removeprefix("team-"))
        assert (store.UPLOADS / name).is_file()
    assert all(path.is_file() for path in store.UPLOADS.iterdir())
    response = _ok(_request(client, team["viewer"], "GET", _url(team["space"], "/files")))
    _public(response)
    assert not any(name in store.dumps(response) for name in names)


@pytest.mark.parametrize("operation", ["upload", "replace"])
@pytest.mark.parametrize(("size", "status"), [(0, 422), (MAX_FILE + 1, 413)])
def test_invalid_upload_or_replacement_content_is_atomic(client, team, operation, size, status):
    space, shared = team["space"], team["file"]
    before = _state()
    method, suffix = ("POST", "/files") if operation == "upload" else ("PUT", f"/files/{shared['id']}/content")
    _ok(_request(client, team["editor"], method, _url(space, suffix), files={"file": ("invalid.txt", b"x" * size)}), status)
    assert _state() == before


def test_file_size_limit_is_inclusive_and_upload_requires_multipart(client, account):
    owner = account()
    space = _space(client, owner)
    before = _state()
    _ok(_request(client, owner, "POST", _url(space, "/files"), json={"name": "fake.txt", "content": "not multipart"}), 422)
    assert _state() == before
    shared = _upload(client, owner, space, b"x" * MAX_FILE)
    assert shared["size"] == MAX_FILE and _blob(shared).stat().st_size == MAX_FILE


@pytest.mark.parametrize("body", [{"name": ""}, {"name": ".."}, {"name": False}, {"name": "bad\u0000.txt"},
                                       {"name": "bad\n.txt"}, {"name": "x" * 201}, {"name": "safe.txt", "storage_name": "forged"}])
def test_invalid_file_rename_cannot_change_metadata_or_storage(client, team, body):
    before = _state()
    _ok(_request(client, team["editor"], "PATCH", _url(team["space"], f"/files/{team['file']['id']}"), json=body), 422)
    assert _state() == before


def test_file_rename_sanitizes_path_components_without_moving_or_rewriting_blob(client, team):
    space, shared, original = team["space"], team["file"], _file_row(team["file"])
    renamed = _ok(_request(client, team["editor"], "PATCH", _url(space, f"/files/{shared['id']}"), json={"name": "..\\outside\\renamed.txt"}))
    assert renamed["name"] == "renamed.txt"
    assert _file_row(shared)["storage_name"] == original["storage_name"] and _blob(shared).read_bytes() == CONTENT


@pytest.mark.parametrize("operation", ["replace", "delete"])
def test_old_blob_unlink_occurs_only_after_database_commit(client, team, monkeypatch, operation):
    shared, space, old_path = team["file"], team["space"], _blob(team["file"])
    original_unlink, observations = Path.unlink, []

    def checked_unlink(path, *args, **kwargs):
        if path == old_path:
            with sqlite3.connect(store.DB_PATH) as db:
                row = db.execute("SELECT storage_name FROM team_files WHERE id=?", (shared["id"],)).fetchone()
            observations.append(row)
            assert row is None if operation == "delete" else row is not None and row[0] != old_path.name
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", checked_unlink)
    if operation == "delete":
        response = _request(client, team["editor"], "DELETE", _url(space, f"/files/{shared['id']}"))
    else:
        response = _request(client, team["editor"], "PUT", _url(space, f"/files/{shared['id']}/content"), files={"file": ("new.txt", b"new blob")})
    _ok(response)
    assert len(observations) == 1 and not old_path.exists()


@pytest.mark.parametrize("operation", ["upload", "replace", "delete"])
def test_commit_failure_rolls_back_file_metadata_audit_and_cleans_only_uncommitted_blob(client, team, monkeypatch, operation):
    space, shared, before = team["space"], team["file"], _state()
    original_connect = store.connect
    failures = []

    @contextmanager
    def fail_commit():
        with original_connect() as db:
            changed = db.total_changes
            yield db
            if db.in_transaction and db.total_changes > changed:
                failures.append(True)
                raise sqlite3.OperationalError("test-only commit failure")

    monkeypatch.setattr(store, "connect", fail_commit)
    if operation == "delete":
        response = _request(client, team["editor"], "DELETE", _url(space, f"/files/{shared['id']}"))
    else:
        method, suffix = ("POST", "/files") if operation == "upload" else ("PUT", f"/files/{shared['id']}/content")
        response = _request(client, team["editor"], method, _url(space, suffix), files={"file": ("uncommitted.txt", b"uncommitted blob")})
    assert response.status_code == 500, response.text
    assert failures == [True] and _state() == before


@pytest.mark.parametrize("operation", ["upload", "replace"])
def test_blob_write_failure_leaves_no_partial_file_database_or_audit_writes(client, team, monkeypatch, operation):
    before = _state()
    fsync = Mock(side_effect=OSError("test-only blob fsync failure"))
    monkeypatch.setattr(os, "fsync", fsync)
    method, suffix = ("POST", "/files") if operation == "upload" else ("PUT", f"/files/{team['file']['id']}/content")
    response = _request(client, team["editor"], method, _url(team["space"], suffix), files={"file": ("partial.txt", b"partial blob")})
    assert response.status_code == 500, response.text
    fsync.assert_called_once()
    assert _state() == before


@pytest.mark.parametrize(("operation", "action"), [
    ("create", "team.space.create"), ("metadata", "team.space.update"), ("archive", "team.space.archive"),
    ("restore", "team.space.restore"), ("invite", "team.member.add"), ("member-role", "team.member.update"),
    ("member-remove", "team.member.remove"), ("transfer", "team.space.transfer"),
    ("upload", "team.file.upload"), ("rename", "team.file.rename"), ("replace", "team.file.replace"), ("delete", "team.file.delete"),
])
def test_audit_failure_rolls_back_entire_team_operation_including_module_grants_and_blobs(client, team, account, operation, action):
    actor, space, shared = team["owner"], team["space"], team["file"]
    target = account(space_modules=["personal"])
    if operation == "restore":
        _ok(_request(client, actor, "DELETE", _url(space)))
    if operation == "transfer":
        target = team["viewer"]
        _set_user(target, space_modules=["personal"], team_invites_blocked=False)
    _audit_failure(action)
    before = _state()
    calls = {
        "create": ("POST", _base(), {"json": {"name": "rollback space"}}),
        "metadata": ("PATCH", _url(space), {"json": {"name": "rollback metadata"}}),
        "archive": ("DELETE", _url(space), {}), "restore": ("POST", _url(space, "/restore"), {}),
        "invite": ("POST", _url(space, "/members"), {"json": {"email": target["email"], "role": "viewer"}}),
        "member-role": ("PATCH", _url(space, f"/members/{team['viewer']['id']}"), {"json": {"role": "editor"}}),
        "member-remove": ("DELETE", _url(space, f"/members/{team['viewer']['id']}"), {}),
        "transfer": ("POST", _url(space, "/transfer"), {"json": {"user_id": target["id"]}}),
        "upload": ("POST", _url(space, "/files"), {"files": {"file": ("rollback.txt", b"rollback blob")}}),
        "rename": ("PATCH", _url(space, f"/files/{shared['id']}"), {"json": {"name": "rollback.txt"}}),
        "replace": ("PUT", _url(space, f"/files/{shared['id']}/content"), {"files": {"file": ("rollback.txt", b"rollback blob")}}),
        "delete": ("DELETE", _url(space, f"/files/{shared['id']}"), {}),
    }
    method, path, kwargs = calls[operation]
    response = _request(client, actor, method, path, **kwargs)
    assert response.status_code == 500, response.text
    assert _state() == before


@pytest.mark.parametrize("operation", ["upload", "replace"])
@pytest.mark.parametrize("revocation", ["viewer", "remove", "module-off", "disabled", "must-change", "admin", "archive"])
def test_upload_await_rechecks_live_role_membership_account_module_and_archive(client, team, monkeypatch, operation, revocation):
    actor, space, shared = team["editor"], team["space"], team["file"]
    original_read, snapshots = UploadFile.read, []

    async def revoke_after_read(file, size=-1):
        content = await original_read(file, size)
        if content and not snapshots:
            if revocation in {"viewer", "remove", "archive"}:
                with store.connect() as db:
                    if revocation == "viewer":
                        db.execute("UPDATE team_members SET role='viewer' WHERE space_id=? AND user_id=?", (space["id"], actor["id"]))
                    elif revocation == "remove":
                        db.execute("DELETE FROM team_members WHERE space_id=? AND user_id=?", (space["id"], actor["id"]))
                    else:
                        db.execute("UPDATE team_spaces SET deleted_at=? WHERE id=?", (store.now(), space["id"]))
            else:
                changes = {
                    "module-off": {"space_modules": []}, "disabled": {"disabled": True},
                    "must-change": {"must_change_password": True}, "admin": {"role": "admin"},
                }[revocation]
                _set_user(actor, **changes)
            snapshots.append(_state())
        return content

    monkeypatch.setattr(UploadFile, "read", revoke_after_read)
    method, suffix = ("POST", "/files") if operation == "upload" else ("PUT", f"/files/{shared['id']}/content")
    response = _request(client, actor, method, _url(space, suffix), files={"file": ("revoked.txt", b"must not persist")})
    expected = 404 if revocation == "remove" else 409 if revocation == "archive" else 403
    _ok(response, expected)
    assert len(snapshots) == 1 and _state() == snapshots[0]


def test_downgrading_editor_takes_effect_on_next_request_with_same_session(client, team):
    actor, space, shared = team["editor"], team["space"], team["file"]
    _ok(_request(client, actor, "PATCH", _url(space, f"/files/{shared['id']}"), json={"name": "allowed.txt"}))
    _ok(_request(client, team["owner"], "PATCH", _url(space, f"/members/{actor['id']}"), json={"role": "viewer"}))
    before = _state()
    _ok(_request(client, actor, "PATCH", _url(space, f"/files/{shared['id']}"), json={"name": "no-longer-allowed.txt"}), 403)
    assert _state() == before
    assert _ok(_request(client, actor, "GET", _url(space)))["role"] == "viewer"


def test_file_and_member_ids_cannot_be_mixed_between_spaces_even_for_owner_of_both(client, account):
    owner, member = account(), account()
    first, second = _space(client, owner), _space(client, owner, "Second")
    _invite(client, owner, second, member, "viewer")
    shared = _upload(client, owner, second)
    before = _state()
    for method, suffix, kwargs in (
        ("GET", f"/files/{shared['id']}", {}), ("GET", f"/files/{shared['id']}/download", {}),
        ("PATCH", f"/files/{shared['id']}", {"json": {"name": "mixed.txt"}}),
        ("PUT", f"/files/{shared['id']}/content", {"files": {"file": ("mixed.txt", CONTENT)}}),
        ("DELETE", f"/files/{shared['id']}", {}),
        ("PATCH", f"/members/{member['id']}", {"json": {"role": "editor"}}), ("DELETE", f"/members/{member['id']}", {}),
        ("POST", "/transfer", {"json": {"user_id": member["id"]}}),
    ):
        _ok(_request(client, owner, method, _url(first, suffix), **kwargs), 404)
        assert _state() == before


def test_personal_and_team_file_ids_do_not_cross_authorization_namespaces(client, team):
    owner, space, shared = team["owner"], team["space"], team["file"]
    private = _ok(_request(client, owner, "POST", "/api/files", files={"file": ("personal.txt", b"personal payload")}))
    before = _state()
    for path in (f"/api/files/{shared['id']}/download", _url(space, f"/files/{private['id']}/download")):
        _ok(_request(client, owner, "GET", path), 404)
        assert _state() == before


def test_admin_global_team_routes_work_without_module_or_membership_but_user_execution_stays_forbidden(client, team, administrator, account):
    owner, new_member, space = team["owner"], account(space_modules=["personal"]), team["space"]
    second = _space(client, account(), "Other owner's space")
    listed = _ok(_request(client, administrator, "GET", _base(True)))
    assert {space["id"], second["id"]} <= {item["id"] for item in listed}
    assert administrator["id"] not in _members(space) and _user_data(administrator)["space_modules"] == []
    assert _ok(_request(client, administrator, "GET", _url(space, admin=True)))["role"] == "admin"
    _ok(_request(client, administrator, "PATCH", _url(space, admin=True), json={"description": "全局管理员管理"}))
    assert _invite(client, administrator, space, new_member, "manager", admin=True)["role"] == "manager"
    _ok(_request(client, administrator, "PATCH", _url(space, f"/members/{new_member['id']}", admin=True), json={"role": "editor"}))
    shared = _upload(client, administrator, second, b"admin shared payload", admin=True)
    assert _request(client, administrator, "GET", _url(second, f"/files/{shared['id']}/download", admin=True)).content == b"admin shared payload"
    _ok(_request(client, administrator, "PATCH", _url(second, f"/files/{shared['id']}", admin=True), json={"name": "admin-renamed.txt"}))
    _ok(_request(client, administrator, "PUT", _url(second, f"/files/{shared['id']}/content", admin=True), files={"file": ("new.txt", b"admin replacement")}))
    _ok(_request(client, administrator, "DELETE", _url(second, f"/files/{shared['id']}", admin=True)))
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM team_files WHERE id=?", (shared["id"],)).fetchone() is None
    changed = _ok(_request(client, administrator, "POST", _url(space, "/transfer", admin=True), json={"user_id": new_member["id"]}))
    assert changed["owner_id"] == new_member["id"] and _members(space)[owner["id"]] == "manager"
    _ok(_request(client, administrator, "DELETE", _url(space, f"/members/{owner['id']}", admin=True)))
    _ok(_request(client, administrator, "DELETE", _url(space, admin=True)))
    assert _ok(_request(client, administrator, "POST", _url(space, "/restore", admin=True)))["archived"] is False
    before = _state()
    for method, path, kwargs in (
        ("GET", _base(), {}), ("GET", _url(space), {}), ("GET", "/api/conversations", {}),
        ("POST", "/api/conversations", {"json": {}}),
        ("POST", "/api/conversations/missing/messages", {"json": {"content": "不得执行"}}),
        ("POST", "/api/schedules/missing/run", {"json": {}}), ("GET", "/api/runs", {}),
    ):
        _ok(_request(client, administrator, method, path, **kwargs), 403)
        assert _state() == before
    assert _user_data(administrator)["space_modules"] == []


def test_admin_can_create_space_for_ordinary_owner_and_auto_enable_team_atomically(client, account, administrator):
    owner = account(space_modules=[])
    space = _space(client, administrator, admin=True, owner_id=owner["id"])
    assert space["owner_id"] == owner["id"] and space["role"] == "admin"
    assert _members(space) == {owner["id"]: "owner"} and _user_data(owner)["space_modules"] == ["team"]
    assert _ok(_request(client, owner, "GET", _url(space)))["role"] == "owner"
    target = account(space_modules=["personal"])
    _audit_failure("admin.team.space.create")
    before = _state()
    response = _request(client, administrator, "POST", _base(True), json={"name": "Must roll back", "owner_id": target["id"]})
    assert response.status_code == 500, response.text
    assert _state() == before


def test_ordinary_team_owner_never_gains_global_admin_routes(client, team):
    space, actor = team["space"], team["owner"]
    before = _state()
    for method, suffix, kwargs in (
        ("GET", "", {}), ("PATCH", "", {"json": {"name": "不得提升"}}), ("DELETE", "", {}),
        ("GET", "/members", {}), ("POST", "/restore", {}),
        ("POST", "/files", {"files": {"file": ("forbidden.txt", CONTENT)}}),
    ):
        _ok(_request(client, actor, method, _url(space, suffix, admin=True), **kwargs), 403)
        assert _state() == before
    _ok(_request(client, actor, "GET", _base(True)), 403)


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("operation", ["single-delete", "batch-delete", "single-promote", "batch-promote"])
def test_owner_account_delete_or_admin_promotion_preflights_before_any_account_session_file_or_run_mutation(
    client, team, administrator, account, monkeypatch, archived, operation,
):
    owner, space, nonowner = team["owner"], team["space"], account()
    _invite(client, owner, space, nonowner, "editor")
    _upload(client, nonowner, space, b"nonowner shared payload")
    for user in (owner, nonowner):
        _ok(_request(client, user, "POST", "/api/files", files={"file": ("private.txt", b"private payload")}))
        conversation = store.save_entity(user["id"], "conversations", {"title": "Must survive preflight"})
        with store.connect() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (
                store.uid(), user["id"], conversation["id"], "running", store.dumps({"control_level": "observe"}), store.now(), store.now(),
            ))
    if archived:
        _ok(_request(client, owner, "DELETE", _url(space)))
    cancel = Mock(side_effect=AssertionError("ownership preflight must happen before cancellation"))
    monkeypatch.setattr(engine, "cancel_run", cancel)
    before = _state()
    if operation == "single-delete":
        response = _request(client, administrator, "DELETE", f"/api/admin/users/{owner['id']}")
    elif operation == "single-promote":
        response = _request(client, administrator, "PATCH", f"/api/admin/users/{owner['id']}", json={
            "role": "admin", "name": "Must not change", "password": "Must-not-reset-password!", "disabled": True,
        })
    else:
        deleting = operation == "batch-delete"
        response = _request(client, administrator, "POST", "/api/admin/users/batch", json={
            "ids": [nonowner["id"], owner["id"]], "action": "delete" if deleting else "update",
            **({} if deleting else {"changes": {"role": "admin", "name": "Must not change", "disabled": True,
                                                 "password": "Must-not-reset-password!", "allowed_control_levels": ["autonomous"]}}),
        })
    _ok(response, 409)
    cancel.assert_not_called()
    assert _state() == before
    assert store.user_for_token(owner["token"]) is not None and store.user_for_token(nonowner["token"]) is not None


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("batch", [False, True])
def test_deleting_nonowner_cascades_membership_sets_uploader_null_and_keeps_shared_content(client, team, administrator, account, archived, batch):
    owner, target, space = team["owner"], team["editor"], team["space"]
    second = _space(client, account(), "Second membership")
    _invite(client, administrator, second, target, "viewer", admin=True)
    shared = _upload(client, target, space, b"survives uploader deletion")
    path = _blob(shared)
    personal = _ok(_request(client, target, "POST", "/api/files", files={"file": ("delete-private.txt", b"private only")}))
    private = store.get_entity(target["id"], "files", personal["id"])
    assert private is not None
    personal_path = store.UPLOADS / private["storage_name"]
    if archived:
        _ok(_request(client, owner, "DELETE", _url(space)))
    if batch:
        response = _request(client, administrator, "POST", "/api/admin/users/batch", json={"ids": [target["id"]], "action": "delete"})
    else:
        response = _request(client, administrator, "DELETE", f"/api/admin/users/{target['id']}")
    assert _ok(response)["count"] == 1
    assert target["id"] not in _members(space) and target["id"] not in _members(second)
    assert _file_row(shared)["uploader_id"] is None and path.read_bytes() == b"survives uploader deletion"
    assert not personal_path.exists() and store.user_for_token(target["token"]) is None
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM users WHERE id=?", (target["id"],)).fetchone() is None
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    if archived:
        _ok(_request(client, owner, "POST", _url(space, "/restore")))
    listed = _ok(_request(client, team["viewer"], "GET", _url(space, "/files")))
    assert next(item for item in listed if item["id"] == shared["id"])["uploader_id"] is None
    _public(listed)
    assert _request(client, team["viewer"], "GET", _url(space, f"/files/{shared['id']}/download")).content == b"survives uploader deletion"


def test_transferred_previous_owner_can_be_deleted_without_destroying_team_files(client, team, administrator):
    old, new, space, shared = team["owner"], team["viewer"], team["space"], team["file"]
    path = _blob(shared)
    _ok(_request(client, old, "POST", _url(space, "/transfer"), json={"user_id": new["id"]}))
    _ok(_request(client, administrator, "DELETE", f"/api/admin/users/{old['id']}"))
    assert _members(space)[new["id"]] == "owner" and old["id"] not in _members(space)
    assert _file_row(shared)["uploader_id"] is None and path.read_bytes() == CONTENT
    assert _request(client, new, "GET", _url(space, f"/files/{shared['id']}/download")).content == CONTENT


@pytest.mark.parametrize("restriction", ["disabled", "module-off"])
def test_disabling_account_or_team_module_denies_apis_but_preserves_membership_files_and_reenable_access(
    client, team, administrator, restriction,
):
    actor, space = team["editor"], team["space"]
    shared = _upload(client, actor, space)
    members, row, path = _members(space), _file_row(shared), _blob(shared)
    changes = {"disabled": True} if restriction == "disabled" else {"space_modules": ["personal"]}
    _ok(_request(client, administrator, "PATCH", f"/api/admin/users/{actor['id']}", json=changes))
    before = _state()
    for method, suffix, kwargs in (
        ("GET", "", {}), ("GET", "/members", {}), ("GET", "/files", {}),
        ("GET", f"/files/{shared['id']}/download", {}),
        ("POST", "/files", {"files": {"file": ("denied.txt", CONTENT)}}),
        ("DELETE", f"/files/{shared['id']}", {}),
    ):
        _denied(_request(client, actor, method, _url(space, suffix), **kwargs), (401, 403))
        assert _state() == before
    assert _members(space) == members and _file_row(shared) == row and path.read_bytes() == CONTENT
    changes = {"disabled": False} if restriction == "disabled" else {"space_modules": ["personal", "team"]}
    _ok(_request(client, administrator, "PATCH", f"/api/admin/users/{actor['id']}", json=changes))
    if restriction == "disabled":
        _ok(_request(client, None, "POST", "/api/auth/login", json={"email": actor["email"], "password": PASSWORD}))
        actor = {**actor, "token": client.cookies.get("earthai_session")}
    assert _ok(_request(client, actor, "GET", _url(space)))["role"] == "editor"
    assert _request(client, actor, "GET", _url(space, f"/files/{shared['id']}/download")).content == CONTENT
    _ok(_request(client, actor, "PATCH", _url(space, f"/files/{shared['id']}"), json={"name": "back-to-editor.txt"}))
    assert _members(space) == members and _blob(shared) == path


def test_access_helpers_treat_empty_modules_as_disabled_not_legacy():
    assert access.enabled_spaces({}) == ["personal"]
    assert access.enabled_spaces({"space_modules": []}) == []
    assert access.enabled_spaces({"space_modules": ["team"]}) == ["team"]
    assert access.enabled_spaces({"space_modules": ["unknown"]}) == []


async def test_content_reading_does_not_schedule_background_model_or_tool_tasks(client, team):
    before_tasks = set(asyncio.all_tasks())
    shared = team["file"]
    response = _request(client, team["viewer"], "GET", _url(team["space"], f"/files/{shared['id']}/download"))
    assert response.status_code == 200 and response.content == CONTENT
    assert set(asyncio.all_tasks()) == before_tasks
    assert engine.TASKS == {}
