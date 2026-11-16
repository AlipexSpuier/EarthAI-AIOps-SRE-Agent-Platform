import json

import pytest

from backend import reliability


def test_only_connection_tools_are_offered():
    def names(server):
        return {tool["function"]["name"] for tool in reliability.available_tools(server)}
    assert "kubernetes" not in names({"kind": "ssh"})
    assert "ssh_exec" not in names({"kind": "kubernetes"})
    assert not ({"ssh_exec", "kubernetes"} & names(None))


def test_parameter_normalization_is_safe_and_schema_bound():
    args = reliability.normalize_parameters("kubernetes", {"action": "scale", "resource": "deploy", "name": "api", "replicas": "3"})
    assert args["replicas"] == 3 and args["resource"] == "deployments"
    for arguments in [{"command": "uptime"}, {"command": "uptime", "reason": "x", "sudo": True}, {"command": 5, "reason": "x"}, {"command": "uptime", "reason": "x", "timeout": -5}]:
        with pytest.raises(reliability.ParameterError):
            reliability.normalize_parameters("ssh_exec", arguments)
    with pytest.raises(reliability.ParameterError):
        reliability.normalize_parameters("invented_tool", {})
    with pytest.raises(reliability.ParameterError):
        reliability.normalize_parameters("kubernetes", {"action": "delete", "resource": "pods"})


def test_compaction_keeps_tool_output_valid_json():
    result = {"items": [{"metadata": {"name": f"pod-{index}"}, "logs": "x" * 3000} for index in range(20)], "metadata": {"continue": "next-page"}}
    compacted = json.loads(reliability.compact_result(result, 5000))
    assert compacted["metadata"]["continue"] == "next-page"
    assert compacted["_earthai_truncated"]["included_items"] < 20
    value = json.loads(reliability.compact_result({"stdout": 'x"' * 20000, "exit_code": 1, "stderr": "error"}))
    assert value["exit_code"] == 1 and value["_earthai_truncated"] is True


def test_repeat_failures_not_successful_polling_are_circuit_broken():
    budget = reliability.FailureBudget()
    args = {"command": "uptime", "reason": "test"}
    for _ in range(5):
        budget.record("ssh_exec", args, True)
    assert not budget.blocked_repeat("ssh_exec", args)
    budget.record("ssh_exec", args, False)
    assert not budget.blocked_repeat("ssh_exec", args)
    budget.record("ssh_exec", args, False)
    assert budget.blocked_repeat("ssh_exec", args)
    assert not budget.blocked_repeat("ssh_exec", {**args, "command": "uname -a"})


def test_context_compaction_preserves_tool_call_result_pairs():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "goal"}]
    for index in range(10):
        messages.extend([{"role": "assistant", "content": None, "tool_calls": [{"id": str(index), "function": {"name": "read_file", "arguments": "{}"}}]}, {"role": "tool", "tool_call_id": str(index), "content": "x" * 3000}])
    selected = reliability.context_window(messages, 10000)
    assert selected[0]["role"] == "system"
    tool_ids = {message["tool_call_id"] for message in selected if message["role"] == "tool"}
    call_ids = {call["id"] for message in selected for call in message.get("tool_calls", [])}
    assert call_ids == tool_ids


def test_action_requirement_is_not_inferred_for_explanations():
    assert reliability.action_requested("请检查服务器运行时间", {"kind": "ssh"})
    assert not reliability.action_requested("如何检查服务器运行时间，只解释不要执行", {"kind": "ssh"})
    assert not reliability.action_requested("请检查服务器", None)
