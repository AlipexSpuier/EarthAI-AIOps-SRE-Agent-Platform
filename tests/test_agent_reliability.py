import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from backend import engine, model_client, store, text_tools, tools
from backend.main import app, login_attempts


def call(name, args, id_):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture
def client():
    login_attempts.clear()
    with TestClient(app) as client:
        user = client.post("/api/auth/register", json={"email": store.uid() + "@agent.example", "password": "Agent-Test-2026!"}).json()
        provider = client.post(
            "/api/providers",
            json={"name": "fixture", "base_url": "https://fixture.example/v1", "api_key": "local", "default_model": "fixture-model"},
        ).json()
        server = client.post("/api/servers", json={"name": "ssh", "host": "192.0.2.1", "password": "test-only"}).json()
        conversation = client.post(
            "/api/conversations", json={"server_id": server["id"], "provider_id": provider["id"], "control_level": "observe"}
        ).json()
        yield client, user, conversation


def run_sync(client, conversation, goal):
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": goal}).json()
    task = engine.TASKS.get(run["id"])
    if task:

        async def join():
            await task

        client.portal.call(join)
    return client.get(f"/api/runs/{run['id']}").json()


def test_invalid_parameters_are_feedback_and_model_can_correct(client, monkeypatch):
    http, user, conversation = client
    count = 0
    executed = []

    async def completion(*args):
        nonlocal count
        count += 1
        if count == 1:
            return {"role": "assistant", "content": None, "tool_calls": [call("ssh_exec", {"command": "uptime"}, "bad")]}
        if count == 2:
            assert json.loads(args[2][-1]["content"])["error_code"] == "invalid_tool_parameters"
            return {"role": "assistant", "content": None, "tool_calls": [call("ssh_exec", {"command": "uptime", "reason": "load"}, "good")]}
        return {"role": "assistant", "content": "运行时间已验证"}

    async def execute(*args):
        executed.append(args)
        return {"exit_code": 0, "stdout": "up 4 days", "stderr": ""}

    monkeypatch.setattr(engine, "model_completion", completion)
    monkeypatch.setattr(tools, "execute", execute)
    result = run_sync(http, conversation, "检查运行时间")
    assert result["run"]["status"] == "completed"
    assert len(executed) == 1
    assert [e["data"]["executed"] for e in result["events"] if e["type"] == "tool_result"] == [False, True]


def test_unknown_tool_is_feedback_not_task_crash(client, monkeypatch):
    http, _, conversation = client
    count = 0

    async def completion(*args):
        nonlocal count
        count += 1
        if count == 1:
            return {"role": "assistant", "content": None, "tool_calls": [call("not_offered", {}, "bad")]}
        if count == 2:
            return {"role": "assistant", "content": None, "tool_calls": [call("ssh_exec", {"command": "uptime", "reason": "load"}, "good")]}
        return {"role": "assistant", "content": "ok"}

    async def execute(*args):
        return {"exit_code": 0, "stdout": "up", "stderr": ""}

    monkeypatch.setattr(engine, "model_completion", completion)
    monkeypatch.setattr(tools, "execute", execute)
    result = run_sync(http, conversation, "检查运行时间")
    assert result["run"]["status"] == "completed"


def test_native_ignored_switches_to_explicit_protocol_with_same_execution_gates(client, monkeypatch):
    http, _, conversation = client

    async def completion(*args):
        return {"role": "assistant", "content": "我准备执行检查"}

    count = 0
    executed = []

    async def compatible(*args):
        nonlocal count
        count += 1
        if count == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [call("ssh_exec", {"command": "uptime", "reason": "load"}, "json-call")],
            }
        return {"role": "assistant", "content": "已读取"}

    async def execute(*args):
        executed.append(args)
        return {"exit_code": 0, "stdout": "up", "stderr": ""}

    monkeypatch.setattr(engine, "model_completion", completion)
    monkeypatch.setattr(text_tools, "complete", compatible)
    monkeypatch.setattr(tools, "execute", execute)
    result = run_sync(http, conversation, "检查运行时间")
    assert result["run"]["status"] == "completed" and len(executed) == 1
    assert any(e["type"] == "notice" and e["data"]["code"] == "action_requires_evidence" for e in result["events"])


def test_model_request_failure_does_not_reexecute_previous_command(client, monkeypatch):
    http, _, conversation = client
    count = 0
    executed = []

    async def completion(*args):
        nonlocal count
        count += 1
        if count == 1:
            return {"role": "assistant", "content": None, "tool_calls": [call("ssh_exec", {"command": "uptime", "reason": "load"}, "once")]}
        raise model_client.ModelResponseError("temporary", code="http_error", metadata={"http_status": 500})

    async def compatible(*args):
        return {"role": "assistant", "content": "已有真实结果，续答恢复"}

    async def execute(*args):
        executed.append(args)
        return {"exit_code": 0, "stdout": "up", "stderr": ""}

    monkeypatch.setattr(engine, "model_completion", completion)
    monkeypatch.setattr(text_tools, "complete", compatible)
    monkeypatch.setattr(tools, "execute", execute)
    result = run_sync(http, conversation, "检查运行时间")
    assert result["run"]["status"] == "completed" and len(executed) == 1


def test_logout_does_not_cancel_background_task(client, monkeypatch):
    http, user, conversation = client

    async def completion(*args):
        await asyncio.sleep(0.15)
        return {"role": "assistant", "content": "完成，不需要服务器工具"}

    monkeypatch.setattr(engine, "model_completion", completion)
    run = http.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "只解释，不要执行"}).json()
    task = engine.TASKS[run["id"]]
    http.post("/api/auth/logout")
    assert http.get(f"/api/runs/{run['id']}").status_code == 401
    http.portal.call(lambda: task)
    assert store.get_run(user["id"], run["id"])["status"] == "completed"
