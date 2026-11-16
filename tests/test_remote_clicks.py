from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

import test_usage_statistics as statistics_tests
from backend import defaults, main, store, usage
from test_usage_statistics import (
    ADMIN_PASSWORD, HIT, KINDS, MISS, PASSWORD, TABLES, _conversation, _copies, _default,
    _insert_run, _login, _ok, _provider, _register, _run, _session, _snapshot, _usage_rows,
)


isolated_store = statistics_tests.isolated_store
client = statistics_tests.client
administrator = statistics_tests.administrator
fake_model = statistics_tests.fake_model
REMOTE_URL = "https://remote-agent.example.invalid/workspace?source=usage-test"


def _click_rows(owner=None):
    with store.connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT id,owner,resource_id,template_id,created_at FROM remote_agent_clicks"
            + (" WHERE owner=?" if owner is not None else "") + " ORDER BY id",
            (owner,) if owner is not None else (),
        )]


@pytest.fixture(params=["default", "private"])
def remote_agent(administrator, request):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    source = None
    if request.param == "default":
        source = _ok(http.post("/api/admin/defaults/agents", json={
            "name": "默认远程统计", "kind": "remote", "url": REMOTE_URL,
        }))
    owner = _register(http)
    if source:
        agent = _copies(http, {"agents": source})["agents"]
    else:
        agent = _ok(http.post("/api/agents", json={"name": "私有远程统计", "kind": "remote", "url": REMOTE_URL}))
    return {
        "http": http, "owner": owner, "agent": agent, "source": source,
        "owner_token": http.cookies.get("earthai_session"), "admin_token": admin_token,
    }


def test_each_sequential_remote_post_creates_one_click(remote_agent):
    http, owner, agent = (remote_agent[key] for key in ("http", "owner", "agent"))
    template_id = agent.get("default_template_id")
    before = datetime.now(timezone.utc)
    assert _click_rows() == []
    for expected in range(1, 5):
        response = http.post(f"/api/agents/{agent['id']}/open", headers={"Origin": "http://testserver"})
        assert _ok(response) == {"ok": True}
        assert "location" not in response.headers
        rows = _click_rows()
        assert len(rows) == expected and len({row["id"] for row in rows}) == expected
        assert {row["owner"] for row in rows} == {owner["id"]}
        assert {row["resource_id"] for row in rows} == {agent["id"]}
        assert {row["template_id"] for row in rows} == {template_id}
        assert all(before <= datetime.fromisoformat(row["created_at"]) <= datetime.now(timezone.utc) for row in rows)
        assert usage.resource_counts(owner["id"], "agents") == {agent["id"]: expected}
        assert usage.counts("agents") == ({template_id: expected} if template_id else {})
        assert usage.summary()["totals"] == {"agents": expected, "knowledge": 0, "skills": 0}
        listed = {item["id"]: item for item in _ok(http.get("/api/agents"))}
        assert listed[agent["id"]]["usage_count"] == expected
        assert all(item["usage_count"] == 0 for id_, item in listed.items() if id_ != agent["id"])
    assert _usage_rows() == []
    assert store.list_runs(owner["id"]) == []


def test_concurrent_remote_posts_are_not_deduplicated(remote_agent):
    http, owner, agent = (remote_agent[key] for key in ("http", "owner", "agent"))
    requests = 8
    barrier = Barrier(requests)
    before = _snapshot()

    def open_once(_):
        barrier.wait(timeout=10)
        return http.post(f"/api/agents/{agent['id']}/open")

    with ThreadPoolExecutor(max_workers=requests) as workers:
        responses = list(workers.map(open_once, range(requests)))
    assert all(_ok(response) == {"ok": True} for response in responses)
    rows = _click_rows()
    assert len(rows) == requests and len({row["id"] for row in rows}) == requests
    assert {row["owner"] for row in rows} == {owner["id"]}
    assert {row["resource_id"] for row in rows} == {agent["id"]}
    assert {row["template_id"] for row in rows} == {agent.get("default_template_id")}
    assert usage.resource_counts(owner["id"], "agents") == {agent["id"]: requests}
    assert usage.counts("agents") == ({agent["default_template_id"]: requests} if remote_agent["source"] else {})
    assert usage.summary()["totals"] == {"agents": requests, "knowledge": 0, "skills": 0}
    after = _snapshot()
    assert "remote_agent_clicks" in TABLES and len(after["remote_agent_clicks"]) == requests
    assert {table: rows for table, rows in after.items() if table != "remote_agent_clicks"} == {
        table: rows for table, rows in before.items() if table != "remote_agent_clicks"
    }


def test_template_totals_merge_old_local_runs_and_remote_clicks_across_owners(administrator, fake_model):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    source = _default(http, "agents", "先本地后远程的默认智能体", control_level="observe")
    owners = []
    model = fake_model()
    for index in range(2):
        owner = _register(http, f"remote-aggregate-{index}@example.test")
        agent = _copies(http, {"agents": source})["agents"]
        if index == 0:
            assert _run(http, _conversation(http, agent, _provider(http)), MISS)["run"]["status"] == "completed"
        owners.append((owner, http.cookies.get("earthai_session"), agent))
    _session(http, admin_token)
    _ok(http.patch(f"/api/admin/defaults/agents/{source['id']}", json={"kind": "remote", "url": REMOTE_URL}))
    private_ids = []
    for index, (owner, token, old_agent) in enumerate(owners):
        _session(http, token)
        agent = _copies(http, {"agents": source})["agents"]
        assert agent["id"] == old_agent["id"] and agent["kind"] == "remote"
        for _ in range((2, 4)[index]):
            assert _ok(http.post(f"/api/agents/{agent['id']}/open")) == {"ok": True}
        private = _ok(http.post("/api/agents", json={"name": "各自私有远程", "kind": "remote", "url": REMOTE_URL}))
        private_ids.append(private["id"])
        for _ in range(index + 1):
            assert _ok(http.post(f"/api/agents/{private['id']}/open")) == {"ok": True}
        expected = {agent["id"]: (3, 4)[index], private["id"]: index + 1}
        assert usage.resource_counts(owner["id"], "agents") == expected
        listed = {item["id"]: item["usage_count"] for item in _ok(http.get("/api/agents"))}
        assert all(type(count) is int and count == expected.get(id_, 0) for id_, count in listed.items())
        assert owners[1 - index][2]["id"] not in listed
        for kind in ("knowledge", "skills"):
            assert usage.resource_counts(owner["id"], kind) == {}
    assert private_ids[0] != private_ids[1]
    assert len(_usage_rows()) == 1 and len(_click_rows()) == 9
    assert len(model.calls) == 1
    assert usage.counts("agents") == {source["id"]: 7}
    assert usage.counts("knowledge") == usage.counts("skills") == {}
    _session(http, admin_token)
    listed = {item["id"]: item for item in _ok(http.get("/api/admin/defaults/agents"))}
    assert listed[source["id"]]["usage_count"] == 7
    assert all(item["usage_count"] == 0 for id_, item in listed.items() if id_ != source["id"])
    assert _ok(http.get(f"/api/admin/defaults/agents/{source['id']}"))["usage_count"] == 7
    summary = _ok(http.get("/api/admin/overview"))["usage"]
    assert summary["totals"] == {"agents": 10, "knowledge": 0, "skills": 0}
    assert summary["scope"] == "all_resources" and summary["method"] == "per_run_resource_and_remote_click"


def test_listing_details_and_manual_document_reads_do_not_create_clicks(remote_agent):
    http = remote_agent["http"]
    knowledge = _ok(http.post("/api/knowledge", json={"name": "只读统计知识"}))
    _ok(http.post(f"/api/knowledge/{knowledge['id']}/documents", files={
        "file": ("remote-read.md", (HIT + " manual read evidence").encode(), "text/markdown"),
    }))
    before = _snapshot()
    for _ in range(2):
        _session(http, remote_agent["owner_token"])
        for kind in KINDS:
            assert all(item["usage_count"] == 0 for item in _ok(http.get(f"/api/{kind}")))
        documents = _ok(http.get(f"/api/knowledge/{knowledge['id']}/documents"))
        assert len(documents) == 1
        _ok(http.get(f"/api/knowledge/{knowledge['id']}/documents/{documents[0]['id']}"))
        assert _ok(http.post("/api/knowledge/search", json={
            "query": HIT, "knowledge_ids": [knowledge["id"]],
        }))["results"]
        _session(http, remote_agent["admin_token"])
        for kind in KINDS:
            for template in _ok(http.get(f"/api/admin/defaults/{kind}")):
                assert template["usage_count"] == 0
                assert _ok(http.get(f"/api/admin/defaults/{kind}/{template['id']}"))["usage_count"] == 0
        assert _ok(http.get("/api/admin/overview"))["usage"]["totals"] == dict.fromkeys(KINDS, 0)
    assert _snapshot() == before
    assert _click_rows() == _usage_rows() == []


@pytest.mark.parametrize(("case", "status"), [
    ("noauth", 401), ("admin", 403), ("disabled", 403), ("mustchange", 403),
    ("otherowner", 404), ("template-id", 404), ("local", 422), ("missing", 404), ("origin", 403),
])
def test_rejected_remote_opens_do_not_count_or_mutate(remote_agent, monkeypatch, case, status):
    http, owner, agent = (remote_agent[key] for key in ("http", "owner", "agent"))
    assert _ok(http.post(f"/api/agents/{agent['id']}/open")) == {"ok": True}
    target, headers = agent["id"], {}
    if case == "noauth":
        http.cookies.clear()
    elif case == "admin":
        _session(http, remote_agent["admin_token"])
    elif case in {"disabled", "mustchange"}:
        field = "disabled" if case == "disabled" else "must_change_password"
        with store.connect() as db:
            db.execute("UPDATE users SET data=json_set(data,?,json('true')) WHERE id=?", ("$." + field, owner["id"]))
    elif case == "otherowner":
        _register(http, "remote-other-owner@example.test")
    elif case == "template-id":
        target = (remote_agent["source"] or defaults.list_templates("agents")[0])["id"]
    elif case == "local":
        target = _ok(http.post("/api/agents", json={"name": "不能远程打开的本地智能体"}))["id"]
    elif case == "missing":
        target = "missing-remote-agent"
    elif case == "origin":
        monkeypatch.setenv("EARTHAI_ALLOWED_ORIGINS", "http://testserver")
        headers = {"Origin": "https://untrusted-origin.example.invalid"}
    before = _snapshot()
    response = http.post(f"/api/agents/{target}/open", headers=headers)
    assert response.status_code == status, response.text
    assert _snapshot() == before
    assert len(_click_rows()) == 1 and _usage_rows() == []
    assert usage.summary()["totals"] == {"agents": 1, "knowledge": 0, "skills": 0}


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "file:///tmp/not-a-remote-agent", "https://user:password@remote.example.invalid",
    "https://remote.example.invalid/white space", "https://remote.example.invalid:invalid",
    "https://remote.example.invalid/\\unsafe", "", None,
])
def test_invalid_stored_remote_urls_are_revalidated_without_counting(remote_agent, url):
    http, owner, agent = (remote_agent[key] for key in ("http", "owner", "agent"))
    assert _ok(http.post(f"/api/agents/{agent['id']}/open")) == {"ok": True}
    store.save_entity(owner["id"], "agents", {**agent, "url": url}, agent["id"])
    before = _snapshot()
    response = http.post(f"/api/agents/{agent['id']}/open")
    assert response.status_code == 422, response.text
    assert _snapshot() == before
    assert len(_click_rows()) == 1 and _usage_rows() == []


def test_deleting_remote_resource_or_template_does_not_erase_click_history(remote_agent):
    http, owner, agent = (remote_agent[key] for key in ("http", "owner", "agent"))
    for _ in range(2):
        assert _ok(http.post(f"/api/agents/{agent['id']}/open")) == {"ok": True}
    before, summary = _click_rows(), usage.summary()
    source = remote_agent["source"]
    if source:
        _session(http, remote_agent["admin_token"])
        assert _ok(http.delete(f"/api/admin/defaults/agents/{source['id']}"))["count"] == 1
        assert source["id"] not in {item["id"] for item in _ok(http.get("/api/admin/defaults/agents"))}
        _session(http, remote_agent["owner_token"])
    else:
        assert _ok(http.delete(f"/api/agents/{agent['id']}")) == {"ok": True}
    assert store.get_entity(owner["id"], "agents", agent["id"]) is None
    assert agent["id"] not in {item["id"] for item in _ok(http.get("/api/agents"))}
    assert http.post(f"/api/agents/{agent['id']}/open").status_code == 404
    assert _click_rows() == before and _usage_rows() == []
    assert usage.resource_counts(owner["id"], "agents") == {agent["id"]: 2}
    assert usage.counts("agents") == ({source["id"]: 2} if source else {})
    _session(http, remote_agent["admin_token"])
    assert _ok(http.get("/api/admin/overview"))["usage"] == summary


def test_upgrade_and_restart_preserve_old_usage_and_start_without_backfilling_clicks(isolated_store):
    store.init_db()
    defaults.initialize()
    usage.initialize()
    owner = store.uid()
    with store.connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (
            owner, "remote-legacy@example.test", store.password_hash(PASSWORD), store.dumps({"role": "user"}), store.now(),
        ))
    defaults.sync_user(owner)
    local = store.list_entities(owner, "agents")[0]
    skill = store.save_entity(owner, "skills", {"name": "旧私有技能", "content": "历史内容"})
    knowledge = store.save_entity(owner, "knowledge", {"name": "旧私有知识"})
    remote = store.save_entity(owner, "agents", {"name": "上线前远程智能体", "kind": "remote", "url": REMOTE_URL})
    conversation = store.save_entity(owner, "conversations", {"title": "旧任务", "agent_id": local["id"]})
    historical = _insert_run(owner, conversation, timestamp="2003-01-01T00:00:00+00:00", agent_id=local["id"])
    usage.record(owner, historical, [("agents", local), ("skills", skill), ("knowledge", knowledge)])
    remote_run = _insert_run(owner, conversation, timestamp="2004-01-01T00:00:00+00:00", agent_id=remote["id"])
    store.emit(remote_run, "model_start", {"turn": 1})
    store.audit(owner, "agents.open", remote["id"], "上线前已有浏览记录，不能回填为新功能点击")
    started_at = "2002-01-01T00:00:00+00:00"
    with store.connect() as db:
        db.execute("UPDATE resource_usage SET created_at=?", ("2003-01-01T00:00:00+00:00",))
        db.execute("UPDATE platform_settings SET value=?,updated_at=? WHERE key='usage_started_at'", (
            store.dumps(started_at), started_at,
        ))
        db.execute("DROP TABLE remote_agent_clicks")
    old_rows = _usage_rows()
    assert len(old_rows) == 3
    with TestClient(main.app) as http:
        _login(http, "admin", "admin")
        _ok(http.post("/api/auth/password", json={"current_password": "admin", "new_password": ADMIN_PASSWORD}))
        first = _ok(http.get("/api/admin/overview"))["usage"]
        assert first["started_at"] == started_at
        assert first["totals"] == dict.fromkeys(KINDS, 1)
        assert first["scope"] == "all_resources" and first["method"] == "per_run_resource_and_remote_click"
        assert _usage_rows() == old_rows and _click_rows() == []
        with store.connect() as db:
            columns = db.execute("PRAGMA table_info(remote_agent_clicks)").fetchall()
        assert [column["name"] for column in columns] == ["id", "owner", "resource_id", "template_id", "created_at"]
        assert [column["name"] for column in columns if column["pk"]] == ["id"]
        usage.initialize()
        usage.initialize()
        assert usage.summary() == first
        assert _usage_rows() == old_rows and _click_rows() == []
        _login(http, "remote-legacy@example.test")
        assert _ok(http.post(f"/api/agents/{remote['id']}/open")) == {"ok": True}
        clicks, after_click = _click_rows(), usage.summary()
        assert len(clicks) == 1
        assert datetime.fromisoformat(clicks[0]["created_at"]) > datetime.fromisoformat(started_at)
        usage.initialize()
        assert _click_rows() == clicks and _usage_rows() == old_rows
    with TestClient(main.app) as http:
        _login(http, "admin", ADMIN_PASSWORD)
        assert _ok(http.get("/api/admin/overview"))["usage"] == after_click
        assert after_click["totals"] == {"agents": 2, "knowledge": 1, "skills": 1}
        assert after_click["started_at"] == started_at
        assert _click_rows() == clicks and _usage_rows() == old_rows
        historical_run, legacy_remote_run = store.get_run(owner, historical), store.get_run(owner, remote_run)
        assert historical_run is not None and historical_run["status"] == "completed"
        assert legacy_remote_run is not None and legacy_remote_run["status"] == "completed"
        assert len(store.events(remote_run)) == 1
        _login(http, "remote-legacy@example.test")
        assert _ok(http.post(f"/api/agents/{remote['id']}/open")) == {"ok": True}
        assert len(_click_rows()) == 2 and _usage_rows() == old_rows
        assert usage.summary()["started_at"] == started_at
        assert usage.summary()["totals"] == {"agents": 3, "knowledge": 1, "skills": 1}


def test_deleting_user_clears_only_their_default_and_private_clicks_and_usage(administrator):
    http = administrator
    admin_token = http.cookies.get("earthai_session")
    source = _ok(http.post("/api/admin/defaults/agents", json={
        "name": "删除用户远程统计", "kind": "remote", "url": REMOTE_URL,
    }))
    owners = []
    for index in range(2):
        owner = _register(http, f"remote-delete-{index}@example.test")
        agent = _copies(http, {"agents": source})["agents"]
        private = _ok(http.post("/api/agents", json={"name": "待清理私有远程", "kind": "remote", "url": REMOTE_URL}))
        for resource in (agent, private):
            for _ in range(index + 1):
                assert _ok(http.post(f"/api/agents/{resource['id']}/open")) == {"ok": True}
        skill = store.save_entity(owner["id"], "skills", {"name": "待清理技能"})
        usage.record(owner["id"], store.uid(), [("skills", skill)])
        owners.append(owner)
    first, second = (owner["id"] for owner in owners)
    survivor_clicks, survivor_usage = _click_rows(second), _usage_rows(owner=second)
    assert len(_click_rows(first)) == 2 and len(survivor_clicks) == 4
    assert len(_usage_rows(owner=first)) == len(survivor_usage) == 1
    _session(http, admin_token)
    before = _ok(http.get("/api/admin/overview"))["usage"]
    assert before["totals"] == {"agents": 6, "knowledge": 0, "skills": 2}
    assert _ok(http.delete(f"/api/admin/users/{first}"))["count"] == 1
    assert _click_rows(first) == _usage_rows(owner=first) == []
    assert _click_rows(second) == survivor_clicks and _usage_rows(owner=second) == survivor_usage
    assert usage.resource_counts(first, "agents") == usage.resource_counts(first, "skills") == {}
    assert usage.counts("agents") == {source["id"]: 2}
    after = _ok(http.get("/api/admin/overview"))["usage"]
    assert after["totals"] == {"agents": 4, "knowledge": 0, "skills": 1}
    assert after["started_at"] == before["started_at"]
