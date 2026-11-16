import asyncio
import copy
import os
import sqlite3
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import defaults, engine, main, model_client, store, text_tools, tools, usage


PASSWORD = "Usage-test-password-2026!"
ADMIN_PASSWORD = "Usage-admin-password-2026!"
HIT = "usagestatisticshittoken"
MISS = "usagestatisticsnomatchzz"
KINDS = ("agents", "knowledge", "skills")
TABLES = (
    "users", "sessions", "entities", "messages", "runs", "events", "approvals",
    "documents", "chunks", "audit", "agent_orders", "default_templates", "template_documents",
    "platform_settings", "help_guides", "default_sync_revisions", "default_owner_states",
    "resource_usage", "remote_agent_clicks",
)
FINAL = {"role": "assistant", "content": "已根据本地资料完成说明。"}


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    data = tmp_path / "data"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "usage-statistics.db")
    for name in tuple(os.environ):
        if name.endswith(("_API_KEY", "_ACCESS_TOKEN")) or name == "EARTHAI_STATE_DIR":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EARTHAI_DATA_DIR", str(data))
    monkeypatch.setenv("EARTHAI_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("EARTHAI_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EARTHAI_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("EARTHAI_COOKIE_SECURE", "false")
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})

    async def catalog(provider):
        return list(provider.get("models", []))

    monkeypatch.setattr(engine, "provider_models", catalog)
    asynchronous = []
    for module, name in (
        (engine, "model_completion"), (model_client, "complete"),
        (text_tools, "complete"), (httpx.AsyncClient, "send"),
    ):
        guard = AsyncMock(side_effect=AssertionError("unexpected external/model request: " + name))
        monkeypatch.setattr(module, name, guard)
        asynchronous.append(guard)
    synchronous = []
    for name in ("test_server", "ssh_command", "kube_operation"):
        guard = Mock(side_effect=AssertionError("unexpected infrastructure operation: " + name))
        monkeypatch.setattr(tools, name, guard)
        synchronous.append(guard)

    execute = tools.execute
    unexpected_tools = []

    async def local_execute(owner, server, name, arguments, knowledge_ids=None):
        if name != "knowledge_search":
            unexpected_tools.append(name)
            raise AssertionError("only local knowledge_search is permitted")
        return await execute(owner, server, name, arguments, knowledge_ids)

    monkeypatch.setattr(tools, "execute", local_execute)
    yield data
    store.close_connections()
    for guard in asynchronous:
        guard.assert_not_awaited()
    for guard in synchronous:
        guard.assert_not_called()
    assert unexpected_tools == []


@pytest.fixture
def client(isolated_store):
    with TestClient(main.app) as http:
        yield http


@pytest.fixture
def administrator(client):
    _login(client, "admin", "admin")
    _ok(client.post("/api/auth/password", json={
        "current_password": "admin", "new_password": ADMIN_PASSWORD,
    }))
    return client


@pytest.fixture
def catalog(administrator):
    http = administrator
    knowledge = _default(http, "knowledge", "统计测试知识库")
    _ok(http.post(f"/api/admin/defaults/knowledge/{knowledge['id']}/documents", json={
        "name": "usage-evidence.md", "content": (HIT + " evidence for local knowledge retrieval.\n") * 75,
    }))
    skill = _default(http, "skills", "统计测试技能", content="USAGE_ENABLED_SKILL: 只说明本地资料，不执行远端操作。")
    agent = _default(http, "agents", "统计测试智能体", system_prompt="只说明知识库参考。",
                     skill_ids=[skill["id"]], knowledge_ids=[knowledge["id"]], control_level="observe")
    return {"agents": agent, "skills": skill, "knowledge": knowledge}


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _login(http, email, password=PASSWORD):
    http.cookies.clear()
    return _ok(http.post("/api/auth/login", json={"email": email, "password": password}))


def _register(http, email="usage-owner@example.test"):
    http.cookies.clear()
    return _ok(http.post("/api/auth/register", json={"email": email, "password": PASSWORD, "name": "统计测试用户"}))


def _session(http, token):
    http.cookies.clear()
    http.cookies.set("earthai_session", token)


def _default(http, kind, name, **fields):
    return _ok(http.post(f"/api/admin/defaults/{kind}", json={"name": name, **fields}))


def _copies(http, sources):
    return {
        kind: next(item for item in _ok(http.get(f"/api/{kind}")) if item.get("default_template_id") == source["id"])
        for kind, source in sources.items()
    }


def _provider(http, **fields):
    return _ok(http.post("/api/providers", json={
        "name": "本地假模型", "base_url": "https://usage-model.example.invalid/v1", "api_key": "local",
        "models": ["usage-local"], "default_model": "usage-local", **fields,
    }))


def _conversation(http, agent, provider=None, **fields):
    return _ok(http.post("/api/conversations", json={
        "title": "统计测试", "agent_id": agent["id"], "provider_id": provider["id"] if provider else None,
        "server_id": None, "project_id": None, "model": "", "control_level": "observe", **fields,
    }))


def _run(http, conversation, goal=HIT):
    run = _ok(http.post(f"/api/conversations/{conversation['id']}/messages", json={"content": goal}))

    async def join():
        task = engine.TASKS.get(run["id"])
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=10)

    http.portal.call(join)
    return _ok(http.get(f"/api/runs/{run['id']}"))


def _insert_run(owner, conversation, status="completed", timestamp=None, **fields):
    run_id, stamp = store.uid(), timestamp or store.now()
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (
            run_id, owner, conversation["id"], status,
            store.dumps({"goal": HIT, "control_level": "observe", **fields}), stamp, stamp,
        ))
    return run_id


def _usage_rows(run_id=None, owner=None):
    clauses, parameters = [], []
    for column, value in (("run_id", run_id), ("owner", owner)):
        if value is not None:
            clauses.append(column + "=?")
            parameters.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with store.connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT owner,run_id,kind,resource_id,template_id,created_at FROM resource_usage" + where
            + " ORDER BY run_id,kind,resource_id", parameters,
        )]


def _snapshot():
    with store.connect() as db:
        existing = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in TABLES if table in existing
        }


def _search_call(query, call_id):
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": call_id, "type": "function",
        "function": {"name": "knowledge_search", "arguments": store.dumps({"query": query})},
    }]}


class ScriptedModel:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []

    async def _complete(self, protocol, model, messages):
        self.calls.append({
            "protocol": protocol, "model": model, "messages": copy.deepcopy(messages), "usage": _usage_rows(),
        })
        assert self.responses, "unexpected extra model round"
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)

    async def __call__(self, provider, model, messages):
        return await self._complete("native", model, messages)

    async def compatible(self, provider, model, messages, offered_tools, progress, require_action):
        return await self._complete("json", model, messages)


@pytest.fixture
def fake_model(monkeypatch):
    def install(*responses):
        model = ScriptedModel(responses or (FINAL,))
        monkeypatch.setattr(engine, "model_completion", model)
        monkeypatch.setattr(text_tools, "complete", model.compatible)
        return model

    return install


def test_two_users_aggregate_owner_copies_into_the_same_templates(catalog, administrator, fake_model):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    model = fake_model(FINAL, FINAL)
    owners, copies_by_owner = [], []
    for index in range(2):
        owner = _register(http, f"usage-{index}@example.test")
        copies = _copies(http, catalog)
        conversation = _conversation(http, copies["agents"], _provider(http))
        result = _run(http, conversation)
        assert result["run"]["status"] == "completed"
        rows = _usage_rows(result["run"]["id"])
        assert {(row["kind"], row["resource_id"], row["template_id"]) for row in rows} == {
            (kind, copies[kind]["id"], catalog[kind]["id"]) for kind in KINDS
        }
        assert {row["owner"] for row in rows} == {owner["id"]}
        for kind in KINDS:
            assert usage.resource_counts(owner["id"], kind) == {copies[kind]["id"]: 1}
            listed = {item["id"]: item for item in _ok(http.get(f"/api/{kind}"))}
            assert listed[copies[kind]["id"]]["usage_count"] == 1
            assert all(item["usage_count"] == 0 for id_, item in listed.items() if id_ != copies[kind]["id"])
        assert [row for row in model.calls[index]["usage"] if row["run_id"] == result["run"]["id"]] == rows
        owners.append(owner["id"])
        copies_by_owner.append({value["id"] for value in copies.values()})
    assert owners[0] != owners[1]
    assert copies_by_owner[0].isdisjoint(copies_by_owner[1])
    assert len(model.calls) == 2 and not model.responses
    _session(http, admin_token)
    for kind in KINDS:
        assert usage.counts(kind) == {catalog[kind]["id"]: 2}
        listed = {item["id"]: item for item in _ok(http.get(f"/api/admin/defaults/{kind}"))}
        assert listed[catalog[kind]["id"]]["usage_count"] == 2
        assert all(item["usage_count"] == 0 for id_, item in listed.items() if id_ != catalog[kind]["id"])
    statistics = _ok(http.get("/api/admin/overview"))["usage"]
    assert {"totals", "started_at", "method", "scope", "description"} <= statistics.keys()
    assert statistics["totals"] == dict.fromkeys(KINDS, 2)
    assert statistics["scope"] == "all_resources"
    assert statistics["method"] == "per_run_resource_and_remote_click"
    assert datetime.fromisoformat(statistics["started_at"]).tzinfo is not None
    assert isinstance(statistics["description"], str) and statistics["description"].strip()


def test_private_resources_and_their_deleted_history_are_in_platform_overview(administrator, fake_model):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    owner = _register(http)
    knowledge = _ok(http.post("/api/knowledge", json={"name": "私人知识"}))
    _ok(http.post(f"/api/knowledge/{knowledge['id']}/documents", files={
        "file": ("private.md", (HIT + " private evidence").encode(), "text/markdown"),
    }))
    skill = _ok(http.post("/api/skills", json={"name": "私人技能", "content": "仅说明资料。"}))
    agent = _ok(http.post("/api/agents", json={
        "name": "私人智能体", "skill_ids": [skill["id"]], "knowledge_ids": [knowledge["id"]],
    }))
    model = fake_model()
    result = _run(http, _conversation(http, agent, _provider(http)))
    assert result["run"]["status"] == "completed" and len(model.calls) == 1
    rows = _usage_rows(result["run"]["id"])
    assert {(row["kind"], row["resource_id"]) for row in rows} == {
        ("agents", agent["id"]), ("skills", skill["id"]), ("knowledge", knowledge["id"]),
    }
    assert {row["owner"] for row in rows} == {owner["id"]}
    assert all(row["template_id"] is None for row in rows)
    resources = {"agents": agent, "skills": skill, "knowledge": knowledge}
    for kind, resource in resources.items():
        assert usage.resource_counts(owner["id"], kind) == {resource["id"]: 1}
        listed = {item["id"]: item for item in _ok(http.get(f"/api/{kind}"))}
        assert listed[resource["id"]]["usage_count"] == 1
    owner_token = http.cookies.get("earthai_session")
    _session(http, admin_token)
    before = _ok(http.get("/api/admin/overview"))["usage"]
    assert before["totals"] == dict.fromkeys(KINDS, 1)
    for kind in KINDS:
        assert usage.counts(kind) == {}
        assert all(item["usage_count"] == 0 for item in _ok(http.get(f"/api/admin/defaults/{kind}")))
    _session(http, owner_token)
    for kind, resource in resources.items():
        assert _ok(http.delete(f"/api/{kind}/{resource['id']}")) == {"ok": True}
        assert resource["id"] not in {item["id"] for item in _ok(http.get(f"/api/{kind}"))}
        assert usage.resource_counts(owner["id"], kind) == {resource["id"]: 1}
        assert _usage_rows(result["run"]["id"]) == rows
        assert usage.summary() == before
    _session(http, admin_token)
    assert _ok(http.get("/api/admin/overview"))["usage"] == before


@pytest.mark.parametrize("initial_hit", [True, False], ids=["initial-and-tools", "tools-only"])
def test_initial_and_repeated_multifragment_knowledge_hits_count_once(catalog, administrator, fake_model, initial_hit):
    http = administrator
    owner = _register(http)
    copies = _copies(http, catalog)
    model = fake_model(_search_call(HIT, "search-one"), _search_call(HIT, "search-two"), FINAL)
    result = _run(http, _conversation(http, copies["agents"], _provider(http)), HIT if initial_hit else MISS)
    assert result["run"]["status"] == "completed"
    assert len(model.calls) == 3 and not model.responses
    before = [row for row in model.calls[0]["usage"] if row["kind"] == "knowledge"]
    assert len(before) == int(initial_hit)
    assert (copies["knowledge"]["id"] in model.calls[0]["messages"][0]["content"]) is initial_hit
    searches = [event["data"] for event in result["events"] if event["type"] == "tool_result"]
    assert len(searches) == 2
    for search in searches:
        assert search["name"] == "knowledge_search" and search["ok"] and search["executed"]
        fragments = search["output"]["results"]
        assert len({item["id"] for item in fragments}) > 1
        assert {item["knowledge_id"] for item in fragments} == {copies["knowledge"]["id"]}
    assert len(_usage_rows(result["run"]["id"], owner["id"])) == 3
    assert usage.counts("knowledge") == {catalog["knowledge"]["id"]: 1}


def test_initial_and_tool_searches_without_hits_do_not_count_knowledge(catalog, administrator, fake_model):
    http = administrator
    _register(http)
    copies = _copies(http, catalog)
    model = fake_model(_search_call(MISS, "no-hit"), FINAL)
    result = _run(http, _conversation(http, copies["agents"], _provider(http)), MISS)
    assert result["run"]["status"] == "completed" and len(model.calls) == 2
    search = next(event["data"] for event in result["events"] if event["type"] == "tool_result")
    assert search["ok"] and search["executed"] and search["output"]["results"] == []
    assert {row["kind"] for row in _usage_rows(result["run"]["id"])} == {"agents", "skills"}
    assert usage.counts("knowledge") == {}


@pytest.mark.parametrize("failure", ["exception", "nonzero-result"])
def test_unsuccessful_knowledge_tool_does_not_record_hits(catalog, administrator, fake_model, monkeypatch, failure):
    http = administrator
    owner = _register(http)
    copies = _copies(http, catalog)
    fragments = store.search_knowledge(owner["id"], HIT, [copies["knowledge"]["id"]])
    assert fragments
    if failure == "exception":
        execute = AsyncMock(side_effect=tools.ToolError("controlled search failure"))
    else:
        execute = AsyncMock(return_value={"exit_code": 1, "results": fragments})
    monkeypatch.setattr(tools, "execute", execute)
    fake_model(_search_call(HIT, "failed-search"), FINAL)
    result = _run(http, _conversation(http, copies["agents"], _provider(http)), MISS)
    assert result["run"]["status"] == "completed"
    execute.assert_awaited_once()
    search = next(event["data"] for event in result["events"] if event["type"] == "tool_result")
    assert not search["ok"] and search["executed"]
    assert usage.counts("knowledge") == {}
    assert {row["kind"] for row in _usage_rows(result["run"]["id"])} == {"agents", "skills"}


def test_page_views_and_manual_knowledge_search_do_not_count_usage(catalog, administrator):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    _register(http)
    copies = _copies(http, catalog)
    for _ in range(2):
        for kind in KINDS:
            assert _ok(http.get(f"/api/{kind}"))
        documents = _ok(http.get(f"/api/knowledge/{copies['knowledge']['id']}/documents"))
        assert documents
        _ok(http.get(f"/api/knowledge/{copies['knowledge']['id']}/documents/{documents[0]['id']}"))
        hits = _ok(http.post("/api/knowledge/search", json={
            "query": HIT, "knowledge_ids": [copies["knowledge"]["id"]],
        }))["results"]
        assert len(hits) > 1
        assert _ok(http.post("/api/knowledge/search", json={"query": MISS}))["results"] == []
    _session(http, admin_token)
    for kind in KINDS:
        assert all(item["usage_count"] == 0 for item in _ok(http.get(f"/api/admin/defaults/{kind}")))
        assert _ok(http.get(f"/api/admin/defaults/{kind}/{catalog[kind]['id']}"))["usage_count"] == 0
    assert _ok(http.get("/api/admin/overview"))["usage"]["totals"] == dict.fromkeys(KINDS, 0)
    assert _usage_rows() == []


def test_model_failure_still_counts_resources_used_for_the_request(catalog, administrator, fake_model):
    http = administrator
    _register(http)
    copies = _copies(http, catalog)
    model = fake_model(RuntimeError("controlled failure after model request"))
    result = _run(http, _conversation(http, copies["agents"], _provider(http)))
    assert result["run"]["status"] == "failed"
    assert "controlled failure after model request" in result["run"]["error"]
    assert len(model.calls) == 1
    assert model.calls[0]["usage"] == _usage_rows(result["run"]["id"])
    assert len(_usage_rows(result["run"]["id"])) == 3
    assert usage.summary()["totals"] == dict.fromkeys(KINDS, 1)


def test_native_protocol_retry_and_multiple_model_turns_do_not_recount(catalog, administrator, fake_model):
    http = administrator
    _register(http)
    copies = _copies(http, catalog)
    model = fake_model(
        model_client.ModelResponseError("controlled protocol retry", code="empty_response", metadata={}),
        _search_call(HIT, "retry-search"), _search_call(HIT, "next-turn-search"), FINAL,
    )
    result = _run(http, _conversation(http, copies["agents"], _provider(http)))
    assert result["run"]["status"] == "completed"
    assert [call["protocol"] for call in model.calls] == ["native", "json", "json", "json"]
    assert not model.responses
    assert any(event["type"] == "notice" and event["data"].get("code") == "tool_protocol_fallback" for event in result["events"])
    assert all(len(call["usage"]) == 3 for call in model.calls)
    assert len(_usage_rows(result["run"]["id"])) == 3
    assert usage.summary()["totals"] == dict.fromkeys(KINDS, 1)


@pytest.mark.parametrize("failure", ["missing-provider", "disabled-provider", "missing-model", "invalid-project"])
def test_failures_before_the_first_model_request_do_not_count(catalog, administrator, fake_model, failure):
    http = administrator
    _register(http)
    copies = _copies(http, catalog)
    provider, fields = None, {}
    expected = "可用的模型供应商"
    if failure == "disabled-provider":
        provider = _provider(http, enabled=False)
    elif failure == "missing-model":
        provider = _provider(http, models=[], default_model="")
        expected = "默认模型"
    elif failure == "invalid-project":
        provider = _provider(http)
        servers = [_ok(http.post("/api/servers", json={
            "name": f"项目服务器{index}", "host": f"192.0.2.{index + 1}", "password": "local-test-only",
        })) for index in range(2)]
        project = _ok(http.post("/api/projects", json={"name": "限制服务器的项目", "server_ids": [servers[1]["id"]]}))
        assert http.post("/api/conversations", json={"agent_id": copies["agents"]["id"], "project_id": "missing-project"}).status_code == 404
        fields = {"server_id": servers[0]["id"], "project_id": project["id"]}
        expected = "不属于此项目"
    model = fake_model()
    result = _run(http, _conversation(http, copies["agents"], provider, **fields))
    assert result["run"]["status"] == "failed" and expected in result["run"]["error"]
    assert model.calls == []
    assert not any(event["type"] == "model_start" for event in result["events"])
    assert _usage_rows() == []
    assert usage.summary()["totals"] == dict.fromkeys(KINDS, 0)


def test_cancelling_a_queued_run_before_dispatch_does_not_count(catalog, administrator, fake_model):
    http = administrator
    owner = _register(http)
    copies = _copies(http, catalog)
    conversation = _conversation(http, copies["agents"], _provider(http))
    model = fake_model()

    async def enqueue_and_cancel():
        run = engine.create_run(owner["id"], conversation, HIT)
        assert run is not None
        task = engine.TASKS[run["id"]]
        queued = store.get_run(owner["id"], run["id"])
        assert queued is not None and queued["status"] == "queued"
        assert _usage_rows(run["id"]) == []
        cancelled = engine.cancel_run(owner["id"], run["id"])
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=10)
        assert task.cancelled()
        return cancelled

    cancelled = http.portal.call(enqueue_and_cancel)
    assert cancelled["status"] == "cancelled" and model.calls == []
    assert not any(event["type"] == "model_start" for event in store.events(cancelled["id"]))
    assert _usage_rows() == []


def test_only_enabled_existing_skills_in_the_first_twelve_slots_are_counted(administrator, fake_model):
    http = administrator
    skills = []
    for index in range(13):
        skills.append(_default(http, "skills", f"统计技能{index}", content=f"USAGE_SLOT_{index}_MARKER", enabled=index != 1))
    source = _default(http, "agents", "技能上限测试", skill_ids=[skill["id"] for skill in skills], control_level="observe")
    owner = _register(http)
    agents = _copies(http, {"agents": source})
    by_template = {item.get("default_template_id"): item for item in _ok(http.get("/api/skills"))}
    missing = by_template[skills[2]["id"]]
    store.delete_entity(owner["id"], "skills", missing["id"])
    model = fake_model()
    result = _run(http, _conversation(http, agents["agents"], _provider(http)), MISS)
    assert result["run"]["status"] == "completed" and len(model.calls) == 1
    expected = {skill["id"] for index, skill in enumerate(skills[:12]) if index not in {1, 2}}
    skill_rows = [row for row in _usage_rows(result["run"]["id"]) if row["kind"] == "skills"]
    assert {row["template_id"] for row in skill_rows} == expected
    assert len(skill_rows) == 10
    assert usage.counts("skills") == dict.fromkeys(expected, 1)
    prompt = model.calls[0]["messages"][0]["content"]
    for index in range(13):
        assert (f"USAGE_SLOT_{index}_MARKER" in prompt) is (index < 12 and index not in {1, 2})
    assert usage.summary()["totals"] == {"agents": 1, "knowledge": 0, "skills": 10}


def test_record_is_idempotent_and_keeps_the_template_id_snapshot(catalog, administrator):
    http = administrator
    alternate = _default(http, "agents", "另一默认智能体")
    owner = _register(http)
    copies = _copies(http, catalog)
    conversation = _conversation(http, copies["agents"])
    run_id = _insert_run(owner["id"], conversation, agent_id=copies["agents"]["id"])
    resources = [(kind, copies[kind]) for kind in KINDS]
    usage.record(owner["id"], run_id, resources * 2 + [("other", copies["agents"]), ("agents", None), ("skills", {})])
    usage.record(owner["id"], run_id, resources)
    usage.record_knowledge(owner["id"], run_id, [
        {"knowledge_id": copies["knowledge"]["id"]}, {"knowledge_id": copies["knowledge"]["id"]},
        {"knowledge_id": "not-owned-or-missing"}, {}, None, "not-a-result",
    ])
    before = _usage_rows(run_id)
    assert len(before) == 3
    assert {row["owner"] for row in before} == {owner["id"]}
    assert all(row["template_id"] == catalog[row["kind"]]["id"] for row in before)
    assert all(datetime.fromisoformat(row["created_at"]).tzinfo is not None for row in before)
    changed = {**copies["agents"], "default_template_id": alternate["id"]}
    store.save_entity(owner["id"], "agents", changed, changed["id"])
    usage.record(owner["id"], run_id, [("agents", changed)])
    assert _usage_rows(run_id) == before
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as db:
            db.execute("INSERT INTO resource_usage SELECT * FROM resource_usage WHERE run_id=? LIMIT 1", (run_id,))
    assert _usage_rows(run_id) == before
    next_run = _insert_run(owner["id"], conversation, agent_id=changed["id"])
    usage.record(owner["id"], next_run, [("agents", changed)])
    assert usage.counts("agents") == {catalog["agents"]["id"]: 1, alternate["id"]: 1}
    assert usage.counts("knowledge") == {catalog["knowledge"]["id"]: 1}
    assert usage.counts("skills") == {catalog["skills"]["id"]: 1}
    assert usage.summary()["totals"] == {"agents": 2, "knowledge": 1, "skills": 1}


def test_record_knowledge_cannot_attribute_another_users_copy(catalog, administrator):
    http = administrator
    first = _register(http, "knowledge-first@example.test")
    first_copy = _copies(http, catalog)["knowledge"]
    second = _register(http, "knowledge-second@example.test")
    second_copy = _copies(http, catalog)["knowledge"]
    run_id = store.uid()
    usage.record_knowledge(first["id"], run_id, [{"knowledge_id": second_copy["id"]}])
    assert _usage_rows() == []
    usage.record_knowledge(first["id"], run_id, [
        {"knowledge_id": second_copy["id"]}, {"knowledge_id": first_copy["id"]},
    ])
    rows = _usage_rows(run_id)
    assert len(rows) == 1 and rows[0]["owner"] == first["id"] != second["id"]
    assert rows[0]["resource_id"] == first_copy["id"] and rows[0]["template_id"] == catalog["knowledge"]["id"]


def test_lifespan_initializes_usage_without_backfilling_history_and_preserves_start_time(isolated_store):
    store.init_db()
    defaults.initialize()
    owner = store.uid()
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='resource_usage'").fetchone() is None
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (
            owner, "historical@example.test", store.password_hash(PASSWORD), store.dumps({"role": "user"}), store.now(),
        ))
    defaults.sync_user(owner)
    agent = store.list_entities(owner, "agents")[0]
    conversation = store.save_entity(owner, "conversations", {"title": "上线前的历史任务", "agent_id": agent["id"]})
    historical = _insert_run(owner, conversation, timestamp="2001-01-01T00:00:00+00:00", agent_id=agent["id"])
    store.emit(historical, "model_start", {"turn": 1})
    store.emit(historical, "tool_result", {
        "name": "knowledge_search", "ok": True, "executed": True,
        "output": {"results": [{"knowledge_id": agent["knowledge_ids"][0]}]},
    })
    before = datetime.now(timezone.utc)
    with TestClient(main.app) as http:
        _login(http, "admin", "admin")
        _ok(http.post("/api/auth/password", json={"current_password": "admin", "new_password": ADMIN_PASSWORD}))
        first = _ok(http.get("/api/admin/overview"))["usage"]
        assert before <= datetime.fromisoformat(first["started_at"]) <= datetime.now(timezone.utc)
        assert first["totals"] == dict.fromkeys(KINDS, 0)
        assert _usage_rows() == []
        usage.initialize()
        usage.initialize()
        assert usage.summary()["started_at"] == first["started_at"]
    with TestClient(main.app) as http:
        _login(http, "admin", ADMIN_PASSWORD)
        restarted = _ok(http.get("/api/admin/overview"))["usage"]
        assert restarted == first
        assert _usage_rows() == []
        historical_run = store.get_run(owner, historical)
        assert historical_run is not None and historical_run["status"] == "completed"
        assert len(store.events(historical)) == 2


def test_deleting_a_user_removes_only_their_usage(catalog, administrator, fake_model):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    fake_model(FINAL, FINAL)
    owners = []
    for index in range(2):
        owner = _register(http, f"delete-usage-{index}@example.test")
        copies = _copies(http, catalog)
        result = _run(http, _conversation(http, copies["agents"], _provider(http)))
        assert result["run"]["status"] == "completed"
        owners.append(owner)
    private = store.save_entity(owners[0]["id"], "skills", {"name": "待清理私人技能"})
    usage.record(owners[0]["id"], store.uid(), [("skills", private)])
    survivor_rows = _usage_rows(owner=owners[1]["id"])
    assert len(_usage_rows(owner=owners[0]["id"])) == 4
    _session(http, admin_token)
    assert _ok(http.get("/api/admin/overview"))["usage"]["totals"] == {"agents": 2, "knowledge": 2, "skills": 3}
    assert _ok(http.delete(f"/api/admin/users/{owners[0]['id']}"))["count"] == 1
    assert _usage_rows(owner=owners[0]["id"]) == []
    assert _usage_rows(owner=owners[1]["id"]) == survivor_rows
    assert _ok(http.get("/api/admin/overview"))["usage"]["totals"] == dict.fromkeys(KINDS, 1)
    for kind in KINDS:
        assert usage.counts(kind) == {catalog[kind]["id"]: 1}


@pytest.mark.parametrize("kind", KINDS)
def test_deleting_templates_preserves_usage_history_in_overview(catalog, administrator, fake_model, kind):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    owner = _register(http)
    copies = _copies(http, catalog)
    fake_model()
    assert _run(http, _conversation(http, copies["agents"], _provider(http)))["run"]["status"] == "completed"
    _session(http, admin_token)
    before = _usage_rows()
    statistics = _ok(http.get("/api/admin/overview"))["usage"]
    assert statistics["totals"] == dict.fromkeys(KINDS, 1)
    assert _ok(http.delete(f"/api/admin/defaults/{kind}/{catalog[kind]['id']}"))["count"] == 1
    assert _ok(http.get("/api/admin/overview"))["usage"] == statistics
    assert _usage_rows() == before
    assert usage.counts(kind) == {catalog[kind]["id"]: 1}
    assert usage.resource_counts(owner["id"], kind) == {copies[kind]["id"]: 1}
    assert catalog[kind]["id"] not in {item["id"] for item in _ok(http.get(f"/api/admin/defaults/{kind}"))}
    assert store.get_entity(owner["id"], kind, copies[kind]["id"]) is None


@pytest.mark.parametrize("kind", KINDS)
def test_admin_usage_count_is_read_only_and_cannot_be_forged_by_patch(catalog, administrator, fake_model, kind):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    _register(http)
    copies = _copies(http, catalog)
    fake_model()
    assert _run(http, _conversation(http, copies["agents"], _provider(http)))["run"]["status"] == "completed"
    path = f"/api/admin/defaults/{kind}/{catalog[kind]['id']}"
    assert http.get(path).status_code == 403
    assert http.patch(path, json={"usage_count": 999999}).status_code == 403
    _session(http, admin_token)
    before = _usage_rows()
    assert _ok(http.get(path))["usage_count"] == 1
    response = http.patch(path, json={"usage_count": 999999})
    assert response.status_code in {200, 422}, response.text
    if response.status_code == 200:
        assert response.json()["usage_count"] == 1
    assert _ok(http.get(path))["usage_count"] == 1
    saved = defaults.get_template(kind, catalog[kind]["id"])
    assert saved is not None and "usage_count" not in saved
    assert _usage_rows() == before
    assert _ok(http.get("/api/admin/overview"))["usage"]["totals"] == dict.fromkeys(KINDS, 1)


@pytest.mark.parametrize("kind", KINDS)
def test_admin_default_list_aggregates_usage_in_one_query(administrator, monkeypatch, kind):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    sources = [_default(http, kind, name) for name in ("批量统计一", "批量统计二")]
    owner = _register(http)
    copies = {item["default_template_id"]: item for item in _ok(http.get(f"/api/{kind}")) if item.get("default_template_id")}
    for source, count in zip(sources, (2, 1)):
        for _ in range(count):
            usage.record(owner["id"], store.uid(), [(kind, copies[source["id"]])])
    _session(http, admin_token)
    statements = []
    connect = store.connect

    @contextmanager
    def traced_connect():
        with connect() as db:
            db.set_trace_callback(lambda sql: statements.append(" ".join(sql.lower().split())))
            try:
                yield db
            finally:
                db.set_trace_callback(None)

    aggregate = Mock(wraps=usage.counts)
    with monkeypatch.context() as patch:
        patch.setattr(store, "connect", traced_connect)
        patch.setattr(usage, "counts", aggregate)
        listed = _ok(http.get(f"/api/admin/defaults/{kind}"))
    aggregate.assert_called_once()
    assert aggregate.call_args.args[0] == kind
    connection = aggregate.call_args.args[1] if len(aggregate.call_args.args) > 1 else aggregate.call_args.kwargs.get("db")
    assert connection is not None
    queries = [sql for sql in statements if sql.startswith("select ") and "from resource_usage" in sql]
    assert len(queries) == 1 and "group by template_id" in queries[0]
    expected = {source["id"]: count for source, count in zip(sources, (2, 1))}
    assert len(listed) > len(expected)
    assert all(type(item["usage_count"]) is int and item["usage_count"] == expected.get(item["id"], 0) for item in listed)
