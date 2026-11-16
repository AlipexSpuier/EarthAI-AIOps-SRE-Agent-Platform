from collections import defaultdict, deque
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import defaults, engine, main, store, tools


REORDER = "/api/admin/defaults/agents/reorder"
CATALOG = "/api/admin/defaults/agents"
PASSWORD = "Agent-order-user-password!"
ADMIN_PASSWORD = "Agent-order-admin-password!"
TABLES = (
    "users", "sessions", "entities", "messages", "runs", "events", "approvals",
    "documents", "chunks", "audit", "agent_orders", "default_templates",
    "template_documents", "platform_settings", "default_sync_revisions", "default_owner_states",
)


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    data = tmp_path / "data"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(store, "DATA_ROOT", data)
    monkeypatch.setattr(store, "DATA", data)
    monkeypatch.setattr(store, "UPLOADS", uploads)
    monkeypatch.setattr(store, "DB_PATH", data / "admin-agent-order.db")
    monkeypatch.setenv("EARTHAI_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EARTHAI_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("EARTHAI_COOKIE_SECURE", "false")
    monkeypatch.setattr(main, "login_attempts", defaultdict(deque))
    monkeypatch.setattr(engine, "TASKS", {})
    monkeypatch.setattr(engine, "CANCEL_TOKENS", {})
    blocked = (
        (engine, "model_completion", AsyncMock(side_effect=AssertionError("unexpected model request"))),
        (engine, "provider_models", AsyncMock(side_effect=AssertionError("unexpected provider request"))),
        (engine, "trigger_schedule", Mock(side_effect=AssertionError("unexpected scheduled execution"))),
        (tools, "execute", AsyncMock(side_effect=AssertionError("unexpected infrastructure execution"))),
        (tools, "test_server", Mock(side_effect=AssertionError("unexpected server connection"))),
    )
    for module, name, replacement in blocked:
        monkeypatch.setattr(module, name, replacement)
    yield data
    for _, name, replacement in blocked:
        assert replacement.call_count == 0, name


@pytest.fixture
def administrator(isolated_store):
    with TestClient(main.app, raise_server_exceptions=False) as client:
        _administrator(client)
        yield client


@pytest.fixture
def populated_catalog(administrator):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    ids = [item["id"] for item in _ok(client.get(CATALOG))]
    owner = _register(client, "order-existing@example.test")
    copies = _copies(client)
    _session(client, admin_token)
    defaults.sync_all()
    assert defaults.sync_all_if_needed() is False
    assert len(ids) >= 3 and set(copies) == set(ids)
    return client, ids, owner, copies


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def _administrator(client):
    user = _ok(client.post("/api/auth/login", json={"email": "admin", "password": "admin"}))
    _ok(client.post("/api/auth/password", json={"current_password": "admin", "new_password": ADMIN_PASSWORD}))
    return user


def _register(client, email):
    client.cookies.clear()
    return _ok(client.post("/api/auth/register", json={"email": email, "password": PASSWORD, "name": "排序测试用户"}))


def _session(client, token):
    client.cookies.clear()
    client.cookies.set("earthai_session", token)


def _copies(client):
    return {item["default_template_id"]: item for item in _ok(client.get("/api/agents")) if item.get("default_template_id")}


def _snapshot():
    with store.connect() as db:
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in TABLES}


def _template_rows():
    with store.connect() as db:
        return {row["id"]: dict(row) for row in db.execute("SELECT * FROM default_templates ORDER BY id")}


def _agent_content(value):
    return {key: item for key, item in value.items() if key not in {"sort_order", "default_revision", "updated_at", "usage_count"}}


def _swapped(ids):
    return [ids[-1], *ids[1:-1], ids[0]]


def test_reorder_persists_whole_catalog_updates_only_changed_rows_and_audits(isolated_store, monkeypatch):
    with TestClient(main.app, raise_server_exceptions=False) as client:
        actor = _administrator(client)
        remote = _ok(client.post(CATALOG, json={
            "name": "远程智能体", "kind": "remote", "url": "https://agent.example.test/chat", "description": "只打开网页",
        }))
        original = _ok(client.get(CATALOG))
        ids = [item["id"] for item in original]
        requested = _swapped(ids)
        before = _template_rows()
        original_sync = defaults.sync_all

        def sync_in_transaction(db):
            assert db.in_transaction
            ranks = dict(db.execute("SELECT id,json_extract(data,'$.sort_order') FROM default_templates WHERE kind='agents'"))
            assert ranks == {id_: index for index, id_ in enumerate(requested)}
            return original_sync(db)

        sync = Mock(side_effect=sync_in_transaction)
        with monkeypatch.context() as patch:
            patch.setattr(defaults, "sync_all", sync)
            assert _ok(client.post(REORDER, json={"agent_ids": requested})) == {"ok": True, "count": len(ids)}
        sync.assert_called_once()
        listed = _ok(client.get(CATALOG))
        assert [item["id"] for item in listed] == requested
        assert [item["sort_order"] for item in listed] == list(range(len(ids)))
        assert next(item for item in listed if item["id"] == remote["id"])["kind"] == "remote"
        after = _template_rows()
        changed = []
        for id_, old in before.items():
            row = after[id_]
            if old["kind"] != "agents":
                assert row == old
                continue
            position = requested.index(id_)
            old_data = store.loads(old["data"])
            assert store.loads(row["data"]) == {**old_data, "sort_order": position}
            assert {key: value for key, value in row.items() if key not in {"data", "updated_at"}} == {
                key: value for key, value in old.items() if key not in {"data", "updated_at"}
            }
            if position == old_data["sort_order"]:
                assert row == old
            else:
                changed.append(id_)
                assert row["updated_at"] != old["updated_at"]
        assert set(changed) == {ids[0], ids[-1]}
        assert len({after[id_]["updated_at"] for id_ in changed}) == 1
        with store.connect() as db:
            audit = [dict(row) for row in db.execute("SELECT * FROM audit WHERE action='admin.defaults.agents.reorder'")]
        assert len(audit) == 1
        assert audit[0]["owner"] == actor["id"]
        assert audit[0]["resource"] == ",".join(requested)[:500]
        assert store.loads(audit[0]["detail"]) == {"actor": actor["id"], "count": len(ids)}
    with TestClient(main.app, raise_server_exceptions=False) as restarted:
        _ok(restarted.post("/api/auth/login", json={"email": "admin", "password": ADMIN_PASSWORD}))
        assert [item["id"] for item in _ok(restarted.get(CATALOG))] == requested
        assert _template_rows() == after
        assert defaults.sync_all_if_needed() is False


def test_reorder_syncs_existing_and_new_users_but_preserves_personal_order(administrator, monkeypatch):
    client = administrator
    admin_token = client.cookies.get("earthai_session")
    ids = [item["id"] for item in _ok(client.get(CATALOG))]
    follower = _register(client, "order-follower@example.test")
    follower_token = client.cookies.get("earthai_session")
    follower_before = _copies(client)
    assert list(follower_before) == ids
    personal = _register(client, "order-personal@example.test")
    personal_token = client.cookies.get("earthai_session")
    personal_before = _copies(client)
    private = _ok(client.post("/api/agents", json={"name": "私人智能体", "system_prompt": "私人正文", "kind": "local"}))
    personal_order = [private["id"], *[personal_before[id_]["id"] for id_ in ids[1:]], personal_before[ids[0]]["id"]]
    assert [item["id"] for item in _ok(client.post("/api/agents/reorder", json={"agent_ids": personal_order}))] == personal_order
    private_before = store.get_entity(personal["id"], "agents", private["id"])
    with store.connect() as db:
        personal_rows = [tuple(row) for row in db.execute("SELECT * FROM agent_orders ORDER BY owner")]
        assert db.execute("SELECT 1 FROM agent_orders WHERE owner=?", (follower["id"],)).fetchone() is None
    _session(client, admin_token)
    requested = _swapped(ids)
    sync = Mock(wraps=defaults.sync_all)
    with monkeypatch.context() as patch:
        patch.setattr(defaults, "sync_all", sync)
        assert _ok(client.post(REORDER, json={"agent_ids": requested})) == {"ok": True, "count": len(ids)}
    sync.assert_called_once()
    sources = {item["id"]: item for item in _ok(client.get(CATALOG))}
    for token, before in ((follower_token, follower_before), (personal_token, personal_before)):
        _session(client, token)
        after = _copies(client)
        assert set(after) == set(before)
        for source, old in before.items():
            assert _agent_content(after[source]) == _agent_content(old)
            assert after[source]["sort_order"] == requested.index(source)
            assert after[source]["default_revision"] == sources[source]["updated_at"]
    _session(client, follower_token)
    assert [item["default_template_id"] for item in _ok(client.get("/api/agents"))] == requested
    _session(client, personal_token)
    assert [item["id"] for item in _ok(client.get("/api/agents"))] == personal_order
    assert store.get_entity(personal["id"], "agents", private["id"]) == private_before
    newcomer = _register(client, "order-newcomer@example.test")
    inherited = _copies(client)
    assert list(inherited) == requested
    assert not ({item["id"] for item in inherited.values()} & {item["id"] for item in follower_before.values()})
    with store.connect() as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM agent_orders ORDER BY owner")] == personal_rows
        for owner in (follower, newcomer):
            assert db.execute("SELECT 1 FROM agent_orders WHERE owner=?", (owner["id"],)).fetchone() is None


def test_reorder_requires_admin_and_authentication_without_mutating_catalog(populated_catalog, monkeypatch):
    client, ids, owner, _ = populated_catalog
    owner_token = store.new_session(owner["id"])
    before = _snapshot()
    sync = Mock(wraps=defaults.sync_all)
    with monkeypatch.context() as patch:
        patch.setattr(defaults, "sync_all", sync)
        _session(client, owner_token)
        assert client.post(REORDER, json={"agent_ids": _swapped(ids)}).status_code == 403
        assert _snapshot() == before
        client.cookies.clear()
        assert client.post(REORDER, json={"agent_ids": _swapped(ids)}).status_code == 401
        assert _snapshot() == before
    sync.assert_not_called()


@pytest.mark.parametrize("case", (
    "missing-field", "missing-id", "empty-ids", "duplicate-id", "unknown-id", "extra-id", "cross-kind-id", "owner-copy-id",
    "private-agent-id", "id-empty-string", "ids-null", "ids-string", "ids-number", "ids-boolean", "ids-object", "id-null", "id-number", "id-float",
    "id-boolean", "id-list", "id-object", "body-null", "body-list", "body-string", "body-number", "body-boolean", "malformed-json",
))
def test_invalid_reorder_is_atomic_for_templates_copies_and_sync_versions(populated_catalog, monkeypatch, case):
    client, ids, owner, copies = populated_catalog
    requested = list(reversed(ids))
    private = store.save_entity(owner["id"], "agents", {"name": "不应排序的私人智能体", "kind": "local", "sort_order": len(ids)})
    other_kind = defaults.list_templates("skills")[0]["id"]
    replacements = {
        "unknown-id": "missing-agent-template", "cross-kind-id": other_kind, "owner-copy-id": copies[ids[0]]["id"],
        "private-agent-id": private["id"], "id-empty-string": "", "id-null": None, "id-number": 7, "id-float": 1.5,
        "id-boolean": True, "id-list": [ids[0]], "id-object": {"id": ids[0]},
    }
    bodies = {
        "missing-field": {}, "missing-id": {"agent_ids": requested[:-1]}, "empty-ids": {"agent_ids": []},
        "duplicate-id": {"agent_ids": [requested[0], *requested[:-1]]}, "extra-id": {"agent_ids": [*requested, "extra-template"]},
        "ids-null": {"agent_ids": None}, "ids-string": {"agent_ids": ids[0]}, "ids-number": {"agent_ids": 1},
        "ids-boolean": {"agent_ids": True}, "ids-object": {"agent_ids": {"first": ids[0]}},
        "body-null": None, "body-list": requested, "body-string": "agents", "body-number": 1, "body-boolean": False,
    }
    if case in replacements:
        body = {"agent_ids": [replacements[case], *requested[1:]]}
    else:
        body = bodies.get(case)
    content = '{"agent_ids":' if case == "malformed-json" else store.dumps(body)
    before = _snapshot()
    assert before["entities"] and before["default_sync_revisions"] and before["platform_settings"]
    sync = Mock(wraps=defaults.sync_all)
    with monkeypatch.context() as patch:
        patch.setattr(defaults, "sync_all", sync)
        response = client.post(REORDER, content=content, headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    sync.assert_not_called()
    assert _snapshot() == before


def test_repeated_noop_reorder_does_not_resync_or_touch_catalog_rows(populated_catalog, monkeypatch):
    client, ids, _, _ = populated_catalog
    before = _snapshot()
    sync = Mock(wraps=defaults.sync_all)
    with monkeypatch.context() as patch:
        patch.setattr(defaults, "sync_all", sync)
        for _ in range(2):
            assert _ok(client.post(REORDER, json={"agent_ids": ids})) == {"ok": True, "count": len(ids)}
    sync.assert_not_called()
    after = _snapshot()
    assert {table: rows for table, rows in after.items() if table != "audit"} == {
        table: rows for table, rows in before.items() if table != "audit"
    }
    assert len(after["audit"]) == len(before["audit"]) + 2
    assert defaults.sync_all_if_needed() is False


@pytest.mark.parametrize("table", ("entities", "default_sync_revisions", "platform_settings"))
def test_sync_failure_rolls_back_template_order_all_copies_and_versions(populated_catalog, monkeypatch, table):
    client, ids, owner, _ = populated_catalog
    admin_token = client.cookies.get("earthai_session")
    second = _register(client, "order-rollback-second@example.test")
    _session(client, admin_token)
    defaults.sync_all()
    last_owner = max(owner["id"], second["id"])
    condition = f"NEW.key='{defaults.SYNC_SIGNATURE_KEY}'" if table == "platform_settings" else f"NEW.owner='{last_owner}'"
    with store.connect() as db:
        db.execute(f"""CREATE TRIGGER reject_admin_order BEFORE INSERT ON {table}
            WHEN {condition} BEGIN SELECT RAISE(ABORT,'forced order sync failure'); END""")
    before = _snapshot()
    sync = Mock(wraps=defaults.sync_all)
    with monkeypatch.context() as patch:
        patch.setattr(defaults, "sync_all", sync)
        response = client.post(REORDER, json={"agent_ids": _swapped(ids)})
    assert response.status_code == 500, response.text
    sync.assert_called_once()
    assert _snapshot() == before
    assert [item["id"] for item in _ok(client.get(CATALOG))] == ids
    assert defaults.sync_all_if_needed() is False
    with store.connect() as db:
        db.execute("DROP TRIGGER reject_admin_order")
    assert _ok(client.post(REORDER, json={"agent_ids": _swapped(ids)})) == {"ok": True, "count": len(ids)}
    assert [item["id"] for item in _ok(client.get(CATALOG))] == _swapped(ids)


@pytest.mark.parametrize("status", ("queued", "running", "waiting_approval"))
def test_active_run_blocks_content_edit_but_not_pure_reorder(populated_catalog, status):
    client, ids, owner, copies = populated_catalog
    source = ids[0]
    copy = copies[source]
    conversation = store.save_entity(owner["id"], "conversations", {"title": "活动排序测试", "agent_id": copy["id"]})
    run_id, stamp = store.uid(), store.now()
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (
            run_id, owner["id"], conversation["id"], status,
            store.dumps({"agent_id": copy["id"], "goal": "不执行真实任务"}), stamp, stamp,
        ))
    before = _snapshot()
    assert client.patch(f"{CATALOG}/{source}", json={"name": "活动任务期间禁止改名"}).status_code == 422
    assert _snapshot() == before
    assert _ok(client.post(REORDER, json={"agent_ids": _swapped(ids)})) == {"ok": True, "count": len(ids)}
    after = _snapshot()
    assert after["runs"] == before["runs"]
    assert after["events"] == before["events"]
    assert after["approvals"] == before["approvals"]
    conversation_after = store.get_entity(owner["id"], "conversations", conversation["id"])
    assert conversation_after is not None and conversation_after["agent_id"] == copy["id"]
    before_entities = {row[0]: store.loads(row[3]) for row in before["entities"] if row[2] == "agents"}
    for template_id, old in copies.items():
        current = store.get_entity(owner["id"], "agents", old["id"])
        assert current is not None
        assert _agent_content(current) == _agent_content({
            **before_entities[old["id"]], "id": old["id"], "created_at": old["created_at"],
        })
        assert current["sort_order"] == _swapped(ids).index(template_id)
    assert engine.TASKS == {} and engine.CANCEL_TOKENS == {}


def test_ordinary_template_and_private_edits_without_sort_order_preserve_order(populated_catalog):
    client, ids, owner, _ = populated_catalog
    admin_token = client.cookies.get("earthai_session")
    requested = _swapped(ids)
    _ok(client.post(REORDER, json={"agent_ids": requested}))
    template_id = requested[0]
    old = _ok(client.get(f"{CATALOG}/{template_id}"))
    updated = _ok(client.patch(f"{CATALOG}/{template_id}", json={"name": "普通编辑保留位置", "system_prompt": "改正文但不改排序"}))
    assert updated["sort_order"] == old["sort_order"]
    assert updated["name"] == "普通编辑保留位置" and updated["system_prompt"] == "改正文但不改排序"
    assert [item["id"] for item in _ok(client.get(CATALOG))] == requested
    _session(client, store.new_session(owner["id"]))
    assert list(_copies(client)) == requested
    assert _copies(client)[template_id]["name"] == updated["name"]
    private = _ok(client.post("/api/agents", json={"name": "普通私人智能体", "system_prompt": "私人正文"}))
    order = [item["id"] for item in _ok(client.get("/api/agents"))]
    changed = _ok(client.patch(f"/api/agents/{private['id']}", json={"name": "私人改名不移动", "system_prompt": "新的私人正文"}))
    assert changed["sort_order"] == private["sort_order"]
    assert [item["id"] for item in _ok(client.get("/api/agents"))] == order
    _session(client, admin_token)
    assert [item["id"] for item in _ok(client.get(CATALOG))] == requested


@pytest.mark.parametrize("personal_order", (False, True), ids=("inherit-default-order", "keep-personal-order"))
def test_overridden_local_agent_syncs_only_rank_and_preserves_personal_content(populated_catalog, personal_order):
    client, ids, owner, copies = populated_catalog
    admin_token = client.cookies.get("earthai_session")
    template_id = ids[0]
    _session(client, store.new_session(owner["id"]))
    copy_id = copies[template_id]["id"]
    changed = _ok(client.patch(f"/api/agents/{copy_id}", json={
        "name": "我的本地覆盖智能体", "system_prompt": "只能保留这段私人正文，不能被默认模板覆盖。",
        "description": "我的私人说明", "control_level": "observe", "model": "personal-model",
        "skill_ids": [], "knowledge_ids": [], "icon": "Terminal", "color": "#123456",
    }))
    assert changed["kind"] == "local" and changed["default_template_id"] == template_id
    assert changed["read_only"] is False
    personal_ids = [copies[source]["id"] for source in [*ids[1:], ids[0]]]
    if personal_order:
        assert [item["id"] for item in _ok(client.post("/api/agents/reorder", json={"agent_ids": personal_ids}))] == personal_ids
    before = store.get_entity(owner["id"], "agents", copy_id)
    assert before is not None
    with store.connect() as db:
        state_before = [tuple(row) for row in db.execute("SELECT * FROM default_owner_states ORDER BY owner,template_id")]
        order_before = [tuple(row) for row in db.execute("SELECT * FROM agent_orders ORDER BY owner")]
    assert state_before == [(owner["id"], template_id, copy_id, "override")]
    _session(client, admin_token)
    requested = _swapped(ids)
    assert _ok(client.post(REORDER, json={"agent_ids": requested})) == {"ok": True, "count": len(ids)}
    current = store.get_entity(owner["id"], "agents", copy_id)
    assert current is not None
    assert _agent_content(current) == _agent_content(before)
    assert current["default_revision"] == before["default_revision"]
    assert current["sort_order"] == len(ids) - 1 and current["sort_order"] != before["sort_order"]
    with store.connect() as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM default_owner_states ORDER BY owner,template_id")] == state_before
        assert [tuple(row) for row in db.execute("SELECT * FROM agent_orders ORDER BY owner")] == order_before
    snapshot = _snapshot()
    defaults.sync_all()
    assert _snapshot() == snapshot
    assert defaults.sync_all_if_needed() is False
    _session(client, store.new_session(owner["id"]))
    order = [item["id"] for item in _ok(client.get("/api/agents"))]
    assert order == (personal_ids if personal_order else [copies[source]["id"] for source in requested])
    revised = _ok(client.patch(f"/api/agents/{copy_id}", json={"description": "排序之后仍能正常编辑，位置不变"}))
    assert revised["sort_order"] == current["sort_order"]
    assert revised["name"] == changed["name"] and revised["system_prompt"] == changed["system_prompt"]
    assert [item["id"] for item in _ok(client.get("/api/agents"))] == order
