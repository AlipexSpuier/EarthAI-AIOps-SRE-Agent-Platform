from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import access, defaults, engine, main, presets, store, tools

PASSWORD = "Personal-Defaults-2026!"
ADMIN_PASSWORD = "Personal-Defaults-Admin-2026!"
ORIGINAL_TEXT = "originalpersonaldefaulttoken\n" + "采集证据，核实授权，再验证结果。\n" * 260
RETIRED_TEXT = "retiredpersonaldefaulttoken 此文档可由个人删除。"
PERSONAL_TEXT = "owneronlydocumenttoken\n" + "仅当前用户保留的完整个人补充。\n" * 240
UPDATED_TEXT = "updatedadmindefaulttoken\n" + "管理员后续修订，不应覆盖个人版本。\n" * 250
SNAPSHOT_TABLES = (
    "entities", "documents", "chunks", "default_owner_states", "default_sync_revisions",
    "agent_orders", "default_templates", "template_documents", "platform_settings", "audit",
)


@pytest.fixture
def personal_store(monkeypatch, tmp_path):
    data = tmp_path / "personal-defaults"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "personal-defaults.db")
    monkeypatch.setenv("EARTHAI_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EARTHAI_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("EARTHAI_COOKIE_SECURE", "false")
    monkeypatch.delenv("EARTHAI_STATE_DIR", raising=False)
    monkeypatch.setattr(presets, "PRESETS", ())
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})

    async def idle_scheduler():
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "scheduler_loop", idle_scheduler)
    blocked = (
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected model request"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure execution"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected server connection"))),
        (tools, "ssh_connect", Mock(side_effect=AssertionError("unexpected SSH connection"))),
        (httpx.HTTPTransport, "handle_request", Mock(side_effect=AssertionError("unexpected HTTP request"))),
        (httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(side_effect=AssertionError("unexpected HTTP request"))),
    )
    for target, name, replacement in blocked:
        monkeypatch.setattr(target, name, replacement)
    yield data
    store.close_connections()
    for _, name, replacement in blocked:
        assert replacement.call_count == 0, name


@pytest.fixture
def client(personal_store):
    with TestClient(main.app, raise_server_exceptions=False) as http:
        yield http


@pytest.fixture
def catalog(client):
    return _catalog(client)


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _session(http, token):
    http.cookies.clear()
    http.cookies.set("earthai_session", token)


def _body(resource_kind, name, **changes):
    values = {
        "knowledge": {"name": name, "description": "系统运行手册"},
        "skills": {"name": name, "content": "先取证，再经授权执行。", "enabled": True},
        "providers": {
            "name": name, "base_url": "https://models.example.invalid/v1", "api_key": "offline-test-only",
            "models": ["offline-model"], "default_model": "offline-model",
        },
        "servers": {"name": name, "host": "192.0.2.10", "password": "offline-test-only"},
        "agents": {"name": name, "kind": "local", "system_prompt": "只读检查并提供证据。", "control_level": "observe"},
        "projects": {"name": name, "description": "默认项目"},
        "schedules": {
            "name": name, "prompt": "只读巡检", "cron": "0 9 * * *", "timezone": "UTC", "enabled": False,
        },
    }
    return {**values[resource_kind], **changes}


def _default(http, resource_kind, name, **changes):
    return _ok(http.post(f"/api/admin/defaults/{resource_kind}", json=_body(resource_kind, name, **changes)))


def _copies(http, kind):
    return {item["default_template_id"]: item for item in _ok(http.get(f"/api/{kind}")) if item.get("default_template_id")}


def _catalog(http):
    _ok(http.post("/api/auth/login", json={"email": "admin", "password": "admin"}))
    _ok(http.post("/api/auth/password", json={"current_password": "admin", "new_password": ADMIN_PASSWORD}))
    admin_token = http.cookies.get("earthai_session")
    sources = {}
    for kind in ("knowledge", "skills", "providers", "servers"):
        sources[kind] = _default(http, kind, "默认-" + kind)
    sources["agents"] = _default(
        http, "agents", "默认本地智能体", provider_id=sources["providers"]["id"],
        skill_ids=[sources["skills"]["id"]], knowledge_ids=[sources["knowledge"]["id"]],
    )
    sources["projects"] = _default(
        http, "projects", "默认项目", server_ids=[sources["servers"]["id"]], knowledge_ids=[sources["knowledge"]["id"]],
    )
    sources["schedules"] = _default(
        http, "schedules", "默认定时任务", agent_id=sources["agents"]["id"], provider_id=sources["providers"]["id"],
        server_id=sources["servers"]["id"], enabled=True,
    )
    remote = _default(http, "agents", "默认远程智能体", kind="remote", url="https://agent.example.invalid/embed")
    documents = [
        _ok(http.post(f"/api/admin/defaults/knowledge/{sources['knowledge']['id']}/documents", json={"name": name, "content": text}))
        for name, text in (("original.md", ORIGINAL_TEXT), ("retired.md", RETIRED_TEXT))
    ]
    owners = []
    for index in range(2):
        http.cookies.clear()
        user = _ok(http.post("/api/auth/register", json={
            "email": f"personal-{index}@example.test", "password": PASSWORD, "name": f"个人用户{index}",
        }))
        copies = {kind: _copies(http, kind)[source["id"]] for kind, source in sources.items()}
        copies["remote"] = _copies(http, "agents")[remote["id"]]
        owners.append({"id": user["id"], "token": http.cookies.get("earthai_session"), "copies": copies})
    return {"admin_token": admin_token, "sources": sources, "remote": remote, "documents": documents, "owners": owners}


def _snapshot(tables=SNAPSHOT_TABLES, owner=None):
    with store.connect() as db:
        where, params = (" WHERE owner=?", (owner,)) if owner else ("", ())
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}{where} ORDER BY rowid", params)] for table in tables}


def _states(owner):
    with store.connect() as db:
        return [tuple(row) for row in db.execute(
            "SELECT owner,template_id,entity_id,state FROM default_owner_states WHERE owner=? ORDER BY template_id", (owner,),
        )]


def _assert_state(owner, source, entity, state):
    assert (owner, source, entity, state) in _states(owner)


def _resource(http, kind, id_):
    return next(item for item in _ok(http.get(f"/api/{kind}")) if item["id"] == id_)


def _document_bundle(http, knowledge_id):
    documents = _ok(http.get(f"/api/knowledge/{knowledge_id}/documents"))
    return sorted([
        {**document, "text": _ok(http.get(f"/api/knowledge/{knowledge_id}/documents/{document['id']}"))["text"]}
        for document in documents
    ], key=lambda item: item["id"])


def _search(http, knowledge_id, query):
    return _ok(http.post("/api/knowledge/search", json={"query": query, "knowledge_ids": [knowledge_id]}))["results"]


def _batch(http, kind, ids, action="update", **changes):
    return _ok(http.post(f"/api/admin/defaults/{kind}/batch", json={"ids": ids, "action": action, "changes": changes}))


@pytest.mark.parametrize(("kind", "agent_kind", "expected"), [
    ("skills", None, False), ("knowledge", None, False), ("agents", "local", False), ("agents", None, False),
    ("agents", "remote", True), ("servers", None, True), ("providers", None, True), ("projects", None, True),
    ("schedules", None, True),
])
def test_read_only_depends_on_default_source_and_type_not_stored_flag(kind, agent_kind, expected):
    resource = {"default_template_id": "source", "read_only": not expected}
    if agent_kind is not None:
        resource["kind"] = agent_kind
    assert access.read_only(kind, resource) is expected
    if expected:
        with pytest.raises(HTTPException) as error:
            access.writable(kind, resource)
        assert error.value.status_code == 403
    else:
        assert access.writable(kind, resource) is resource
    private = {key: value for key, value in resource.items() if key != "default_template_id"}
    private["read_only"] = True
    assert access.read_only(kind, private) is False
    assert access.writable(kind, private) is private


def test_public_flags_are_dynamic_and_remote_and_other_defaults_stay_read_only(client, catalog):
    first, second = catalog["owners"]
    _session(client, first["token"])
    with store.connect() as db:
        for key, item in first["copies"].items():
            kind = "agents" if key == "remote" else key
            value = store.get_entity(first["id"], kind, item["id"])
            assert value is not None
            data = {name: value for name, value in value.items() if name not in {"id", "created_at", "updated_at"}}
            data["read_only"] = key in {"skills", "knowledge", "agents"}
            db.execute("UPDATE entities SET data=? WHERE owner=? AND id=?", (store.dumps(data), first["id"], item["id"]))
    before = _snapshot(("entities",), first["id"])
    for key, item in first["copies"].items():
        kind = "agents" if key == "remote" else key
        value = _resource(client, kind, item["id"])
        assert value["read_only"] is (key not in {"skills", "knowledge", "agents"}), key
        if value["read_only"]:
            assert client.patch(f"/api/{kind}/{item['id']}", json={"name": "不应允许"}).status_code == 403
            assert client.delete(f"/api/{kind}/{item['id']}").status_code == 403
    assert _snapshot(("entities",), first["id"]) == before
    assert not _states(first["id"])
    _session(client, second["token"])
    assert client.patch(f"/api/skills/{first['copies']['skills']['id']}", json={"enabled": False}).status_code == 404
    assert client.delete(f"/api/knowledge/{first['copies']['knowledge']['id']}").status_code == 404
    assert not _states(second["id"])


@pytest.mark.parametrize("kind", ("skills", "knowledge", "agents"))
def test_personal_edits_keep_identity_and_source_metadata_and_isolate_owners(client, catalog, kind):
    first, second = catalog["owners"]
    source, original = catalog["sources"][kind], first["copies"][kind]
    templates = _snapshot(("default_templates", "template_documents"))
    other = _snapshot(("entities", "documents", "chunks", "default_owner_states"), second["id"])
    changes: dict[str, str | bool] = {"name": "我的个人版本", "description": "仅对当前账号生效"}
    if kind == "skills":
        changes.update(content="个人技能内容，不反写管理员模板。", enabled=False)
    elif kind == "agents":
        changes.update(system_prompt="个人本地系统提示词。", icon="Wrench", color="#123456")
    spoofed = {
        "id": second["copies"][kind]["id"], "owner": second["id"], "created_at": "forged-created",
        "default_template_id": catalog["remote"]["id"], "default_revision": "forged-revision", "personal_override": False,
        "read_only": True, "builtin_key": "forged-builtin", "builtin_domain": "forged-domain", "builtin_version": -1,
        "sort_order": 99999,
    }
    _session(client, first["token"])
    value = _ok(client.patch(f"/api/{kind}/{original['id']}", json={**spoofed, **changes}))
    for key, expected in changes.items():
        assert value[key] == expected
    assert value["id"] == original["id"] and value["created_at"] == original["created_at"]
    assert value["default_template_id"] == source["id"]
    assert value["default_revision"] == original["default_revision"]
    assert value["read_only"] is False
    raw = store.get_entity(first["id"], kind, original["id"])
    assert raw is not None
    for field in ("builtin_key", "builtin_domain", "builtin_version", "sort_order"):
        assert raw.get(field) == original.get(field)
    assert "owner" not in raw
    assert _states(first["id"]) == [(first["id"], source["id"], original["id"], "override")]
    defaults.sync_user(first["id"])
    defaults.sync_all()
    assert _resource(client, kind, original["id"])["name"] == changes["name"]
    assert _snapshot(("default_templates", "template_documents")) == templates
    assert _snapshot(("entities", "documents", "chunks", "default_owner_states"), second["id"]) == other
    assert value["personal_override"] is True


def test_private_resources_cannot_forge_default_metadata_and_private_agent_types_remain_editable(client, catalog):
    first = catalog["owners"][0]
    _session(client, first["token"])
    for kind in ("skills", "knowledge", "agents"):
        value = _ok(client.post(f"/api/{kind}", json=_body(
            kind, "我的私有-" + kind, default_template_id=catalog["sources"][kind]["id"], default_revision="forged",
            personal_override=True, read_only=True, builtin_key="forged",
        )))
        assert not value.get("default_template_id") and not value.get("default_revision")
        assert not value.get("personal_override") and not value.get("builtin_key") and value["read_only"] is False
        changed = _ok(client.patch(f"/api/{kind}/{value['id']}", json={"name": "私有修订", "default_template_id": "forged"}))
        assert changed["name"] == "私有修订" and not changed.get("default_template_id")
        if kind == "agents":
            remote = _ok(client.patch(f"/api/agents/{value['id']}", json={"kind": "remote", "url": "https://private.example.invalid/agent"}))
            assert remote["kind"] == "remote" and remote["read_only"] is False
            local = _ok(client.patch(f"/api/agents/{value['id']}", json={"kind": "local", "system_prompt": "恢复本地"}))
            assert local["kind"] == "local" and local["system_prompt"] == "恢复本地"
        assert _ok(client.delete(f"/api/{kind}/{value['id']}")) == {"ok": True}
    assert not _states(first["id"])


def test_default_local_to_remote_is_422_and_default_remote_to_local_is_403(client, catalog):
    first = catalog["owners"][0]
    _session(client, first["token"])
    before = _snapshot()
    local, remote = first["copies"]["agents"], first["copies"]["remote"]
    assert client.patch(f"/api/agents/{local['id']}", json={"kind": "remote", "url": "https://agent.example.invalid/bypass"}).status_code == 422
    assert client.patch(f"/api/agents/{remote['id']}", json={"kind": "local", "read_only": False}).status_code == 403
    assert _snapshot() == before


def test_personal_rank_does_not_create_override_and_unmodified_defaults_keep_following(client, catalog):
    first = catalog["owners"][0]
    _session(client, first["token"])
    before = _snapshot(("entities",), first["id"])
    templates = _snapshot(("default_templates", "template_documents"))
    order = [item["id"] for item in reversed(_ok(client.get("/api/agents")))]
    assert [item["id"] for item in _ok(client.post("/api/agents/reorder", json={"agent_ids": order}))] == order
    assert not _states(first["id"])
    assert _snapshot(("entities",), first["id"]) == before
    assert _snapshot(("default_templates", "template_documents")) == templates
    _session(client, catalog["admin_token"])
    _batch(client, "agents", [catalog["sources"]["agents"]["id"]], name="管理员排序后修订", sort_order=70)
    _session(client, first["token"])
    agents = _ok(client.get("/api/agents"))
    assert [item["id"] for item in agents] == order
    inherited = next(item for item in agents if item["id"] == first["copies"]["agents"]["id"])
    assert inherited["name"] == "管理员排序后修订" and inherited["sort_order"] == 70
    assert inherited["personal_override"] is False and not _states(first["id"])


@pytest.mark.parametrize("mutation", ("upload", "delete"))
def test_personal_documents_keep_full_text_search_and_ids_across_admin_changes_and_restart(personal_store, mutation):
    with TestClient(main.app, raise_server_exceptions=False) as http:
        catalog = _catalog(http)
        first, second = catalog["owners"]
        knowledge = first["copies"]["knowledge"]
        other_knowledge = second["copies"]["knowledge"]
        source = catalog["sources"]["knowledge"]
        templates = _snapshot(("default_templates", "template_documents"))
        _session(http, first["token"])
        original = _document_bundle(http, knowledge["id"])
        kept = next(item for item in original if item["name"] == "original.md")
        retired = next(item for item in original if item["name"] == "retired.md")
        if mutation == "upload":
            _ok(http.post(f"/api/knowledge/{knowledge['id']}/documents", files={"file": ("mine.md", PERSONAL_TEXT.encode(), "text/markdown")}))
        else:
            _ok(http.delete(f"/api/knowledge/{knowledge['id']}/documents/{retired['id']}"))
        personal_documents = _document_bundle(http, knowledge["id"])
        assert next(item for item in personal_documents if item["id"] == kept["id"]) == kept
        assert len(personal_documents) == (3 if mutation == "upload" else 1)
        assert _search(http, knowledge["id"], "originalpersonaldefaulttoken")
        assert bool(_search(http, knowledge["id"], "owneronlydocumenttoken")) is (mutation == "upload")
        assert bool(_search(http, knowledge["id"], "retiredpersonaldefaulttoken")) is (mutation == "upload")
        _assert_state(first["id"], source["id"], knowledge["id"], "override")
        assert _snapshot(("default_templates", "template_documents")) == templates
        _session(http, second["token"])
        other_documents = _document_bundle(http, other_knowledge["id"])
        other_kept = next(item for item in other_documents if item["name"] == "original.md")
        assert http.get(f"/api/knowledge/{other_knowledge['id']}/documents/{kept['id']}").status_code == 404
        assert http.post(f"/api/knowledge/{knowledge['id']}/documents", files={"file": ("cross.md", b"blocked", "text/markdown")}).status_code == 404
        assert http.delete(f"/api/knowledge/{knowledge['id']}/documents/{kept['id']}").status_code == 404
        assert not _search(http, other_knowledge["id"], "owneronlydocumenttoken")
        assert not _states(second["id"])
        _session(http, catalog["admin_token"])
        _ok(http.patch(f"/api/admin/defaults/knowledge/{source['id']}/documents/{catalog['documents'][0]['id']}", json={
            "name": "updated.md", "content": UPDATED_TEXT,
        }))
        _ok(http.delete(f"/api/admin/defaults/knowledge/{source['id']}/documents/{catalog['documents'][1]['id']}"))
        _batch(http, "knowledge", [source["id"]], description="管理员修订的描述")
        _session(http, second["token"])
        updated = _document_bundle(http, other_knowledge["id"])
        assert len(updated) == 1 and updated[0]["id"] == other_kept["id"]
        assert updated[0]["text"] == UPDATED_TEXT and _search(http, other_knowledge["id"], "updatedadmindefaulttoken")
        assert not _search(http, other_knowledge["id"], "originalpersonaldefaulttoken")
        _session(http, catalog["admin_token"])
        _ok(http.delete(f"/api/admin/defaults/knowledge/{source['id']}"))
        new_source = _default(http, "knowledge", source["name"])
        assert new_source["id"] != source["id"]
        defaults.sync_user(first["id"])
        defaults.sync_all()
        _session(http, first["token"])
        assert _document_bundle(http, knowledge["id"]) == personal_documents
        assert new_source["id"] in _copies(http, "knowledge")
        assert store.get_entity(second["id"], "knowledge", other_knowledge["id"]) is None
        personal_rows = _snapshot(("documents", "chunks"), first["id"])
    with TestClient(main.app, raise_server_exceptions=False) as restarted:
        _session(restarted, first["token"])
        assert _document_bundle(restarted, knowledge["id"]) == personal_documents
        assert _snapshot(("documents", "chunks"), first["id"]) == personal_rows
        value = _resource(restarted, "knowledge", knowledge["id"])
        assert value["default_template_id"] == source["id"]
        assert _search(restarted, knowledge["id"], "originalpersonaldefaulttoken")
        assert not _search(restarted, knowledge["id"], "updatedadmindefaulttoken")
        assert new_source["id"] in _copies(restarted, "knowledge")
        assert value["personal_override"] is True


def test_override_and_tombstone_survive_batch_sync_remote_source_deletion_and_restart(personal_store):
    with TestClient(main.app, raise_server_exceptions=False) as http:
        catalog = _catalog(http)
        first, second = catalog["owners"]
        sources = catalog["sources"]
        _session(http, catalog["admin_token"])
        following = _default(http, "skills", "未改动的技能")
        _session(http, first["token"])
        for kind, changes in (("skills", {"name": "我的技能", "enabled": False, "content": "我的技能正文"}),
                              ("agents", {"name": "我的本地智能体", "system_prompt": "个人本地提示词"})):
            _ok(http.patch(f"/api/{kind}/{first['copies'][kind]['id']}", json=changes))
        _ok(http.delete(f"/api/knowledge/{first['copies']['knowledge']['id']}"))
        _session(http, catalog["admin_token"])
        _batch(http, "skills", [sources["skills"]["id"], following["id"]], name="管理员批量新版本", content="全局新正文", enabled=True)
        _batch(http, "knowledge", [sources["knowledge"]["id"]], name="管理员修改了已被个人删除的模板")
        _ok(http.patch(f"/api/admin/defaults/agents/{sources['agents']['id']}", json={
            "kind": "remote", "url": "https://agent.example.invalid/new-remote", "name": "管理员改成远程",
        }))
        for owner in (first, second):
            defaults.sync_user(owner["id"])
        _session(http, first["token"])
        assert _resource(http, "skills", first["copies"]["skills"]["id"])["enabled"] is False
        local = _resource(http, "agents", first["copies"]["agents"]["id"])
        assert local["kind"] == "local" and local["system_prompt"] == "个人本地提示词" and local["read_only"] is False
        assert sources["knowledge"]["id"] not in _copies(http, "knowledge")
        assert _copies(http, "skills")[following["id"]]["name"] == "管理员批量新版本"
        _session(http, second["token"])
        assert _resource(http, "skills", second["copies"]["skills"]["id"])["content"] == "全局新正文"
        remote = _resource(http, "agents", second["copies"]["agents"]["id"])
        assert remote["kind"] == "remote" and remote["read_only"] is True
        assert _resource(http, "knowledge", second["copies"]["knowledge"]["id"])["name"] == "管理员修改了已被个人删除的模板"
        _session(http, catalog["admin_token"])
        for kind in ("skills", "knowledge", "agents"):
            _batch(http, kind, [sources[kind]["id"]], action="delete")
        replacement = _default(http, "knowledge", sources["knowledge"]["name"])
        defaults.sync_all()
        _session(http, first["token"])
        preserved = {kind: store.get_entity(first["id"], kind, first["copies"][kind]["id"]) for kind in ("skills", "agents")}
        assert preserved["skills"] is not None and preserved["agents"] is not None
        assert preserved["skills"]["name"] == "我的技能" and preserved["agents"]["kind"] == "local"
        assert replacement["id"] in _copies(http, "knowledge")
        for kind in ("skills", "knowledge", "agents"):
            assert store.get_entity(second["id"], kind, second["copies"][kind]["id"]) is None
        states = _states(first["id"])
        assert len(states) == 3
        _assert_state(first["id"], sources["knowledge"]["id"], first["copies"]["knowledge"]["id"], "deleted")
    with TestClient(main.app, raise_server_exceptions=False) as restarted:
        defaults.sync_user(first["id"])
        defaults.sync_all()
        _session(restarted, first["token"])
        for kind, original in preserved.items():
            assert original is not None
            current = store.get_entity(first["id"], kind, original["id"])
            assert current == original
        assert store.get_entity(first["id"], "knowledge", first["copies"]["knowledge"]["id"]) is None
        assert replacement["id"] in _copies(restarted, "knowledge")
        assert _states(first["id"]) == states
        assert all(_resource(restarted, kind, value["id"])["personal_override"] is True
                   for kind, value in preserved.items() if value is not None)


def test_personal_deletion_clears_owner_refs_and_future_remaps_keep_schedules_disabled(personal_store):
    with TestClient(main.app, raise_server_exceptions=False) as http:
        catalog = _catalog(http)
        first, second = catalog["owners"]
        copies, sources = first["copies"], catalog["sources"]
        _session(http, first["token"])
        private_agent = _ok(http.post("/api/agents", json=_body(
            "agents", "私有依赖智能体", skill_ids=[copies["skills"]["id"]], knowledge_ids=[copies["knowledge"]["id"]],
        )))
        private_project = _ok(http.post("/api/projects", json=_body("projects", "私有依赖项目", knowledge_ids=[copies["knowledge"]["id"]])))
        conversation = _ok(http.post("/api/conversations", json={"agent_id": copies["agents"]["id"], "project_id": private_project["id"]}))
        private_schedule = _ok(http.post("/api/schedules", json=_body(
            "schedules", "私有依赖定时任务", agent_id=copies["agents"]["id"], provider_id=copies["providers"]["id"], enabled=True,
        )))
        other = _snapshot(("entities", "documents", "chunks", "default_owner_states"), second["id"])
        templates = _snapshot(("default_templates", "template_documents"))
        for kind in ("skills", "knowledge", "agents"):
            _ok(http.delete(f"/api/{kind}/{copies[kind]['id']}"))
            assert store.get_entity(first["id"], kind, copies[kind]["id"]) is None
            _assert_state(first["id"], sources[kind]["id"], copies[kind]["id"], "deleted")
        private_agent = store.get_entity(first["id"], "agents", private_agent["id"])
        private_project = store.get_entity(first["id"], "projects", private_project["id"])
        conversation = store.get_entity(first["id"], "conversations", conversation["id"])
        assert private_agent is not None and private_project is not None and conversation is not None
        assert not private_agent["skill_ids"] and not private_agent["knowledge_ids"]
        assert not private_project["knowledge_ids"]
        assert conversation["agent_id"] is None
        for schedule_id in (copies["schedules"]["id"], private_schedule["id"]):
            value = store.get_entity(first["id"], "schedules", schedule_id)
            assert value is not None
            assert value["agent_id"] is None and value["enabled"] is False
        with store.connect() as db:
            assert not db.execute("SELECT 1 FROM documents WHERE owner=? AND knowledge_id=?", (first["id"], copies["knowledge"]["id"])).fetchone()
            assert not db.execute("SELECT 1 FROM chunks WHERE owner=? AND knowledge_id=?", (first["id"], copies["knowledge"]["id"])).fetchone()
        assert not store.search_knowledge(first["id"], "originalpersonaldefaulttoken")
        assert _snapshot(("entities", "documents", "chunks", "default_owner_states"), second["id"]) == other
        assert _snapshot(("default_templates", "template_documents")) == templates
        _session(http, catalog["admin_token"])
        new_agent = _default(http, "agents", "以后下发的新关联智能体", skill_ids=[sources["skills"]["id"]], knowledge_ids=[sources["knowledge"]["id"]])
        new_schedule = _default(
            http, "schedules", "以后下发的新定时任务", agent_id=sources["agents"]["id"], provider_id=sources["providers"]["id"], enabled=True,
        )
        for revision in range(2):
            _batch(http, "schedules", [sources["schedules"]["id"], new_schedule["id"]], enabled=True, name=f"再次启用-{revision}")
            _batch(http, "projects", [sources["projects"]["id"]], description=f"推动引用重新映射-{revision}")
            defaults.sync_user(first["id"])
            defaults.sync_all()
            _session(http, first["token"])
            assert not _copies(http, "projects")[sources["projects"]["id"]]["knowledge_ids"]
            inherited = _copies(http, "agents")[new_agent["id"]]
            assert inherited["skill_ids"] == [] and inherited["knowledge_ids"] == []
            for source in (sources["schedules"], new_schedule):
                value = _copies(http, "schedules")[source["id"]]
                assert value["agent_id"] is None and value["enabled"] is False
            _session(http, catalog["admin_token"])
        _session(http, second["token"])
        assert _copies(http, "agents")[new_agent["id"]]["skill_ids"] == [second["copies"]["skills"]["id"]]
        assert _copies(http, "schedules")[new_schedule["id"]]["enabled"] is True
        states = _states(first["id"])
    with TestClient(main.app, raise_server_exceptions=False) as restarted:
        defaults.sync_all()
        _session(restarted, first["token"])
        assert _states(first["id"]) == states
        for kind in ("skills", "knowledge", "agents"):
            assert sources[kind]["id"] not in _copies(restarted, kind)
        for source in (sources["schedules"], new_schedule):
            value = _copies(restarted, "schedules")[source["id"]]
            assert value["agent_id"] is None and value["enabled"] is False
        private = store.get_entity(first["id"], "schedules", private_schedule["id"])
        assert private is not None
        assert private["agent_id"] is None and private["enabled"] is False


def test_missing_copy_without_tombstone_is_repaired_but_personal_deletion_is_not(client, catalog):
    first, second = catalog["owners"]
    knowledge = first["copies"]["knowledge"]
    _session(client, first["token"])
    original_documents = _document_bundle(client, knowledge["id"])
    defaults.sync_all()
    store.delete_entity(first["id"], "knowledge", knowledge["id"])
    assert not _states(first["id"])
    assert defaults.sync_all_if_needed() is False
    defaults.sync_user(first["id"])
    repaired = _resource(client, "knowledge", knowledge["id"])
    assert repaired["default_template_id"] == knowledge["default_template_id"] and repaired["personal_override"] is False
    assert [{key: item[key] for key in ("id", "name", "text")} for item in _document_bundle(client, knowledge["id"])] == [
        {key: item[key] for key in ("id", "name", "text")} for item in original_documents
    ]
    assert _search(client, knowledge["id"], "originalpersonaldefaulttoken")
    _ok(client.delete(f"/api/knowledge/{knowledge['id']}"))
    defaults.sync_user(first["id"])
    defaults.sync_all()
    assert store.get_entity(first["id"], "knowledge", knowledge["id"]) is None
    assert store.get_entity(second["id"], "knowledge", second["copies"]["knowledge"]["id"]) is not None
    _assert_state(first["id"], knowledge["default_template_id"], knowledge["id"], "deleted")


@pytest.mark.parametrize("mutation", ("update", "delete", "document_upload", "document_delete"))
def test_write_failure_rolls_back_personal_state_contents_documents_and_references(client, catalog, mutation):
    first = catalog["owners"][0]
    _session(client, first["token"])
    knowledge = first["copies"]["knowledge"]
    dependent = _ok(client.post("/api/projects", json=_body("projects", "事务依赖", knowledge_ids=[knowledge["id"]])))
    document = _document_bundle(client, knowledge["id"])[0]
    if mutation == "update":
        table, event, id_ = "entities", "UPDATE", first["copies"]["skills"]["id"]
    elif mutation == "delete":
        table, event, id_ = "entities", "UPDATE", dependent["id"]
    elif mutation == "document_upload":
        table, event, id_ = "documents", "INSERT", None
    else:
        table, event, id_ = "documents", "DELETE", document["id"]
    row = "NEW" if event == "INSERT" else "OLD"
    condition = f"{row}.owner='{first['id']}'" + (f" AND {row}.id='{id_}'" if id_ else "")
    with store.connect() as db:
        db.execute(f"CREATE TRIGGER fail_personal_write AFTER {event} ON {table} WHEN {condition} "
                   "BEGIN SELECT RAISE(ABORT,'injected personal write failure'); END")
    before = _snapshot()
    try:
        if mutation == "update":
            response = client.patch(f"/api/skills/{id_}", json={"content": "不应落盘", "enabled": False})
        elif mutation == "delete":
            response = client.delete(f"/api/knowledge/{knowledge['id']}")
        elif mutation == "document_upload":
            response = client.post(f"/api/knowledge/{knowledge['id']}/documents", files={"file": ("failed.md", PERSONAL_TEXT.encode(), "text/markdown")})
        else:
            response = client.delete(f"/api/knowledge/{knowledge['id']}/documents/{document['id']}")
        assert response.status_code >= 400, response.text
        assert _snapshot() == before
        assert not _states(first["id"])
        assert _search(client, knowledge["id"], "originalpersonaldefaulttoken")
    finally:
        with store.connect() as db:
            db.execute("DROP TRIGGER fail_personal_write")


@pytest.mark.parametrize("race", ("deleted", "changed_owner"))
def test_document_upload_rechecks_resource_owner_after_extraction(client, catalog, monkeypatch, race):
    first, second = catalog["owners"]
    knowledge = first["copies"]["knowledge"]
    _session(client, first["token"])
    snapshots = []
    original_extract = main.extract_text

    def extract_then_change_resource(name, content):
        text = original_extract(name, content)
        if race == "deleted":
            defaults.delete_personal(first["id"], "knowledge", knowledge["id"])
        else:
            with store.connect() as db:
                db.execute("UPDATE entities SET owner=? WHERE owner=? AND id=?", (second["id"], first["id"], knowledge["id"]))
        snapshots.append(_snapshot())
        return text

    monkeypatch.setattr(main, "extract_text", extract_then_change_resource)
    response = client.post(f"/api/knowledge/{knowledge['id']}/documents", files={"file": ("racing.md", PERSONAL_TEXT.encode(), "text/markdown")})
    assert response.status_code == 404, response.text
    assert len(snapshots) == 1 and _snapshot() == snapshots[0]
    assert not store.search_knowledge(first["id"], "owneronlydocumenttoken")
    if race == "deleted":
        _assert_state(first["id"], knowledge["default_template_id"], knowledge["id"], "deleted")
    else:
        assert not _states(first["id"])


def test_deleted_user_cascades_default_owner_states_without_affecting_other_owner(client, catalog):
    first, second = catalog["owners"]
    _session(client, first["token"])
    _ok(client.patch(f"/api/skills/{first['copies']['skills']['id']}", json={"enabled": False}))
    _ok(client.delete(f"/api/knowledge/{first['copies']['knowledge']['id']}"))
    assert {row[3] for row in _states(first["id"])} == {"override", "deleted"}
    _session(client, second["token"])
    _ok(client.patch(f"/api/agents/{second['copies']['agents']['id']}", json={"system_prompt": "另一用户的个人版本"}))
    other = _snapshot(("entities", "documents", "chunks", "default_owner_states"), second["id"])
    _session(client, catalog["admin_token"])
    _ok(client.post("/api/admin/users/batch", json={"ids": [first["id"]], "action": "delete"}))
    assert _states(first["id"]) == []
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM users WHERE id=?", (first["id"],)).fetchone() is None
        for table in ("entities", "documents", "chunks", "default_sync_revisions"):
            assert db.execute(f"SELECT 1 FROM {table} WHERE owner=?", (first["id"],)).fetchone() is None
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    defaults.sync_all()
    assert _snapshot(("entities", "documents", "chunks", "default_owner_states"), second["id"]) == other


@pytest.mark.parametrize("kind", ("skills", "knowledge"))
@pytest.mark.parametrize("status", ("queued", "running", "waiting_approval"))
def test_active_owner_runs_block_default_deletion_without_affecting_private_or_other_owners(client, catalog, kind, status):
    first, second = catalog["owners"]
    source = catalog["sources"][kind]
    original = first["copies"][kind]
    _session(client, first["token"])
    private = _ok(client.post(f"/api/{kind}", json=_body(kind, "活动任务期间仍可删除的私有资源")))
    conversation = _ok(client.post("/api/conversations", json={"title": "无关联资源的活动任务"}))
    run_id, stamp = store.uid(), store.now()
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (
            run_id, first["id"], conversation["id"], status,
            store.dumps({"goal": "仅验证删除保护，不启动执行引擎"}), stamp, stamp,
        ))
    before = _snapshot((*SNAPSHOT_TABLES, "runs"))
    response = client.delete(f"/api/{kind}/{original['id']}")
    assert response.status_code == 409, response.text
    assert _snapshot((*SNAPSHOT_TABLES, "runs")) == before
    assert not _states(first["id"])
    assert _ok(client.delete(f"/api/{kind}/{private['id']}")) == {"ok": True}
    assert store.get_entity(first["id"], kind, private["id"]) is None
    assert not _states(first["id"])

    first_before = _snapshot(("entities", "documents", "chunks", "default_owner_states", "runs"), first["id"])
    _session(client, second["token"])
    other_copy = second["copies"][kind]
    assert _ok(client.delete(f"/api/{kind}/{other_copy['id']}")) == {"ok": True}
    _assert_state(second["id"], source["id"], other_copy["id"], "deleted")
    assert _snapshot(("entities", "documents", "chunks", "default_owner_states", "runs"), first["id"]) == first_before

    with store.connect() as db:
        db.execute("UPDATE runs SET status='cancelled',updated_at=? WHERE owner=? AND id=?", (store.now(), first["id"], run_id))
    _session(client, first["token"])
    assert _ok(client.delete(f"/api/{kind}/{original['id']}")) == {"ok": True}
    defaults.sync_user(first["id"])
    defaults.sync_all()
    for owner in (first, second):
        deleted = owner["copies"][kind]
        assert store.get_entity(owner["id"], kind, deleted["id"]) is None
        _assert_state(owner["id"], source["id"], deleted["id"], "deleted")
        if kind == "knowledge":
            with store.connect() as db:
                for table in ("documents", "chunks"):
                    assert db.execute(f"SELECT 1 FROM {table} WHERE owner=? AND knowledge_id=?", (owner["id"], deleted["id"])).fetchone() is None
    assert source["id"] not in _copies(client, kind)
