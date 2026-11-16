import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend import engine, progress, store, tools
from backend.main import app, login_attempts


@pytest.fixture
def client():
    login_attempts.clear()
    with TestClient(app) as client:
        yield client


def setup_run(client, level="approve", server=False):
    user = client.post("/api/auth/register", json={"email": f"{store.uid()}@stream.example", "password": "Stream-Test-2026!", "name": "Stream Test"}).json()
    if level != "observe":
        with store.connect() as db:
            db.execute("UPDATE users SET data=json_set(data,'$.allowed_control_levels',json(?)) WHERE id=?", (
                store.dumps(["observe", "approve", "autonomous"]), user["id"],
            ))
    provider = client.post("/api/providers", json={"name": "Test Stream", "base_url": "https://stream.example/v1", "api_key": "stream-secret-key", "default_model": "stream-model"}).json()
    values = {"provider_id": provider["id"], "control_level": level}
    if server:
        srv = client.post("/api/servers", json={"name": "SSH fixture", "host": "192.0.2.1", "password": "fixture-only-password"}).json()
        values["server_id"] = srv["id"]
    response = client.post("/api/conversations", json=values)
    assert response.status_code == 200, response.text
    return user, response.json()


def wait(client, id_, states=None):
    states = states or {"completed", "failed", "cancelled", "waiting_approval"}
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        detail = client.get(f"/api/runs/{id_}").json()
        if detail["run"]["status"] in states:
            return detail
        time.sleep(0.02)
    raise AssertionError("run did not reach expected state")


def test_redaction_across_chunks_never_releases_secret():
    redactor = progress.RedactedText(["secret-provider-key"])
    visible = ""
    for text in ["连接正常，密钥 se", "连接正常，密钥 secret-pro", "连接正常，密钥 secret-provider-key 完成"]:
        change = redactor.update(text)
        if change:
            visible = change["delta"] if change.get("reset") else visible + change["delta"]
        assert "secr" not in visible
    assert "[REDACTED]" in visible
    assert progress.RedactedText([]).render('{"api_key":"test-token"}', final=True) == '{"api_key":"[REDACTED]"}'


def test_public_text_is_streamed_before_model_finishes(client, monkeypatch):
    user, conversation = setup_run(client)
    async def streaming(*args):
        callback = progress.MODEL_EVENTS.get()
        callback("content", {"content": "开始分析"})
        await asyncio.sleep(0.35)
        callback("content", {"content": "开始分析，已完成"})
        callback("metadata", {"finish_reason": "stop", "streamed": True})
        return {"role": "assistant", "content": "开始分析，已完成"}
    monkeypatch.setattr(engine, "model_completion", streaming)
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "检查"}).json()
    deadline = time.monotonic() + 2
    early = None
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/runs/{run['id']}").json()
        if any(event["type"] == "assistant_delta" for event in snapshot["events"]):
            early = snapshot
            break
        time.sleep(0.01)
    assert early and early["run"]["status"] == "running"
    assert not any(event["type"] == "assistant" for event in early["events"])
    detail = wait(client, run["id"])
    assert detail["run"]["status"] == "completed"
    finals = [event for event in detail["events"] if event["type"] == "assistant"]
    assert len(finals) == 1 and finals[0]["data"]["content"] == "开始分析，已完成"
    assert finals[0]["data"]["message_id"] == next(event for event in detail["events"] if event["type"] == "assistant_delta")["data"]["message_id"]
    assert len(store.list_messages(user["id"], conversation["id"])) == 2


def test_tool_trace_distinguishes_approval_from_execution_and_output(client, monkeypatch):
    _, conversation = setup_run(client, server=True)
    calls = 0
    async def model(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"role": "assistant", "content": "准备执行", "tool_calls": [{"id": "command-call", "type": "function", "function": {"name": "ssh_exec", "arguments": json.dumps({"command": "kubectl rollout restart deployment/api", "reason": "验证审批顺序"})}}]}
        return {"role": "assistant", "content": "已验证"}
    async def execute(*args):
        callback = progress.TOOL_EVENTS.get()
        callback("stdout", {"content": "first line\n"})
        await asyncio.sleep(0.1)
        callback("stdout", {"content": "first line\nsecond line\n"})
        return {"exit_code": 0, "stdout": "first line\nsecond line\n", "stderr": ""}
    monkeypatch.setattr(engine, "model_completion", model)
    monkeypatch.setattr(tools, "execute", execute)
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "执行并验证"}).json()
    pending = wait(client, run["id"])
    assert pending["run"]["status"] == "waiting_approval"
    assert not any(event["type"] in {"tool_execution", "tool_output"} for event in pending["events"])
    start = next(event for event in pending["events"] if event["type"] == "tool_start")
    assert start["data"]["arguments"]["command"] == "kubectl rollout restart deployment/api"
    assert start["data"]["target"]["name"] == "SSH fixture"
    approval = pending["approvals"][0]
    client.post(f"/api/approvals/{approval['id']}", json={"approved": True})
    detail = wait(client, run["id"], {"completed", "failed"})
    assert detail["run"]["status"] == "completed"
    event_types = [event["type"] for event in detail["events"]]
    assert event_types.index("tool_execution") > event_types.index("approval")
    assert event_types.index("tool_output") < event_types.index("tool_result")
    result = next(event["data"] for event in detail["events"] if event["type"] == "tool_result")
    assert result["executed"] is True and result["outcome"] == "succeeded" and result["duration_ms"] >= 80
    assert result["step_index"] == 1


def test_observe_block_does_not_emit_execution(client, monkeypatch):
    _, conversation = setup_run(client, "observe", server=True)
    calls = 0
    async def model(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"role": "assistant", "content": None, "tool_calls": [{"id": "blocked-call", "type": "function", "function": {"name": "ssh_exec", "arguments": '{"command":"touch /tmp/proof","reason":"should block"}'}}]}
        return {"role": "assistant", "content": "变更已阻止"}
    monkeypatch.setattr(engine, "model_completion", model)
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "阻止"}).json()
    detail = wait(client, run["id"])
    assert not any(event["type"] == "tool_execution" for event in detail["events"])
    result = next(event["data"] for event in detail["events"] if event["type"] == "tool_result")
    assert result["executed"] is False and result["outcome"] == "blocked"


def test_cancellation_finalizes_partial_public_text_without_success(client, monkeypatch):
    _, conversation = setup_run(client)
    async def model(*args):
        progress.MODEL_EVENTS.get()("content", {"content": "这是一段正在输出的公开回复"})
        await asyncio.sleep(10)
    monkeypatch.setattr(engine, "model_completion", model)
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "取消"}).json()
    deadline = time.monotonic() + 2
    while not any(event["type"] == "assistant_delta" for event in client.get(f"/api/runs/{run['id']}").json()["events"]):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    client.post(f"/api/runs/{run['id']}/cancel")
    detail = wait(client, run["id"])
    assert detail["run"]["status"] == "cancelled"
    public = [event for event in detail["events"] if event["type"] == "assistant"]
    assert public and public[-1]["data"]["status"] == "interrupted"
    assert not any(event["type"] == "done" and event["data"]["status"] == "completed" for event in detail["events"])


def test_terminal_run_detail_returns_beyond_first_thousand_events(client):
    user, conversation = setup_run(client)
    id_, stamp = store.uid(), store.now()
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (id_, user["id"], conversation["id"], "completed", store.dumps({"goal": "many events", "step_count": 1}), stamp, stamp))
        db.executemany("INSERT INTO events(run_id,type,data,created_at) VALUES (?,?,?,?)", [(id_, "assistant_delta", store.dumps({"message_id": "long", "delta": "x"}), stamp) for _ in range(1005)])
        db.execute("INSERT INTO events(run_id,type,data,created_at) VALUES (?,?,?,?)", (id_, "done", store.dumps({"status": "completed"}), stamp))
    detail = client.get(f"/api/runs/{id_}").json()
    assert len(detail["events"]) == 1006 and detail["events"][-1]["type"] == "done"
