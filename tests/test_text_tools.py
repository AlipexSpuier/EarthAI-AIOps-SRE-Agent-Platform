import asyncio
import json

import pytest

from backend import model_client, text_tools


@pytest.mark.parametrize("text", [ 'echo hacked', '{"action":"tool","name":"ssh_exec","arguments":"uptime"}', '{"action":"tool","name":"ssh_exec","arguments":{},"extra":true}', '{"action":"final","content":""}', '[]', '{"action":"tool","name":"ssh_exec","arguments":{"timeout":NaN}}'])
def test_text_protocol_never_executes_unstructured_or_partial_response(text):
    with pytest.raises(text_tools.TextToolProtocolError):
        text_tools.parse_control(text)


def test_text_protocol_accepts_only_explicit_structured_calls():
    result = text_tools.parse_control('```json\n{"action":"tool","name":"ssh_exec","arguments":{"command":"uptime","reason":"read"}}\n```')
    call = result["tool_calls"][0]
    assert call["function"]["name"] == "ssh_exec"
    assert json.loads(call["function"]["arguments"])["command"] == "uptime"
    assert text_tools.parse_control('{"action":"final","content":"已验证"}')["content"] == "已验证"


def test_projection_replaces_native_tool_roles_but_preserves_evidence():
    messages = [{"role":"system","content":"safe"},{"role":"assistant","tool_calls":[{"id":"1","function":{"name":"ssh_exec","arguments":"{}"}}]}, {"role":"tool","tool_call_id":"1","content":'{"exit_code":0}'}]
    projected = text_tools.projected_messages(messages)
    assert all(item["role"] != "tool" and not item.get("tool_calls") for item in projected)
    assert "actual_tool_result" in projected[-1]["content"] and "exit_code" in projected[-1]["content"]
    assert messages[-1]["role"] == "tool"


@pytest.mark.asyncio
async def test_json_protocol_repairs_once_and_omits_raw_control_from_public_stream(monkeypatch):
    requests = []
    async def complete(provider, model, messages, on_event=None):
        requests.append(messages)
        assert model_client.REQUEST_OPTIONS.get().get("omit_tools") is True
        on_event("content", {"content":"must not stream raw control"})
        return {"role":"assistant","content":'not-json' if len(requests)==1 else '{"action":"tool","name":"server_info","arguments":{}}'}
    monkeypatch.setattr(model_client,"complete",complete)
    events=[]
    response=await text_tools.complete({},"test",[{"role":"system","content":"safe"},{"role":"user","content":"goal"}], [{"function":{"name":"server_info","description":"target","parameters":{"type":"object"}}}],lambda name,data:events.append((name,data)))
    assert len(requests)==2 and response["tool_calls"]
    assert not any(name=="content" for name,_ in events)
    assert any(name=="notice" for name,_ in events)


@pytest.mark.asyncio
async def test_json_protocol_cancellation_propagates(monkeypatch):
    async def complete(*args,**kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(model_client,"complete",complete)
    with pytest.raises(asyncio.CancelledError):
        await text_tools.complete({},"test",[{"role":"system","content":"safe"}],[])
