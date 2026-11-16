from __future__ import annotations

import copy
import json
import re
from collections import Counter
from uuid import NAMESPACE_URL, uuid5

from . import store, tools

SCHEMAS = {item["function"]["name"]: item["function"]["parameters"] for item in tools.TOOLS}
RESOURCE_ALIASES = {"pod": "pods", "po": "pods", "deployment": "deployments", "deploy": "deployments", "statefulset": "statefulsets", "sts": "statefulsets", "daemonset": "daemonsets", "ds": "daemonsets", "service": "services", "svc": "services", "node": "nodes", "no": "nodes", "namespace": "namespaces", "ns": "namespaces", "event": "events", "ev": "events", "configmap": "configmaps", "cm": "configmaps", "job": "jobs", "cronjob": "cronjobs", "ingress": "ingresses", "ing": "ingresses", "replicaset": "replicasets", "rs": "replicasets", "pvc": "persistentvolumeclaims"}


class ParameterError(tools.ToolError):
    code = "invalid_tool_parameters"


def preferred_protocol(owner, provider_id, model):
    id_ = str(uuid5(NAMESPACE_URL, f"earthai.protocol:{owner}:{provider_id}:{model}"))
    profile = store.get_entity(owner, "model_profiles", id_)
    return (profile or {}).get("tool_protocol", "native")


def remember_protocol(owner, provider_id, model, protocol):
    id_ = str(uuid5(NAMESPACE_URL, f"earthai.protocol:{owner}:{provider_id}:{model}"))
    previous = store.get_entity(owner, "model_profiles", id_)
    if previous and previous.get("tool_protocol") == protocol:
        return
    values = {"provider_id": provider_id, "model": model, "tool_protocol": protocol, "verified_at": store.now()}
    if previous:
        store.save_entity(owner, "model_profiles", values, id_)
    else:
        timestamp = store.now()
        with store.connect() as db:
            db.execute("INSERT OR IGNORE INTO entities VALUES (?,?,?,?,?,?)", (id_, owner, "model_profiles", store.dumps(values), timestamp, timestamp))


def action_requested(goal, server):
    if server is None or re.search(r"(?:不要|无需|不必|不需要|不允许).{0,8}(?:执行|工具|连接)|只(?:讲解|说明|解释|给出|提供)|如何|怎么做|what is|how (?:to|does)", goal, re.I):
        return False
    return bool(re.search(r"检查|巡检|诊断|排查|执行|运行|查看|读取|列出|查询|部署|重启|扩容|缩容|修复|check|inspect|diagnos|execut|run\b|list\b|get\b", goal, re.I))


def available_tools(server):
    allowed = {item["function"]["name"] for item in tools.TOOLS}
    if server is None:
        allowed -= {"ssh_exec", "kubernetes"}
    elif server["kind"] == "ssh":
        allowed.discard("kubernetes")
    else:
        allowed.discard("ssh_exec")
    return [copy.deepcopy(item) for item in tools.TOOLS if item["function"]["name"] in allowed]


def _validate(value, schema, path):
    kind = schema.get("type")
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool), "number": isinstance(value, (int, float)) and not isinstance(value, bool), "boolean": isinstance(value, bool)}
    if kind and not matches.get(kind, False):
        raise ParameterError(f"{path} 应为 {kind}，请按工具 schema 修正参数")
    if "enum" in schema and value not in schema["enum"]:
        raise ParameterError(f"{path} 应为以下值之一：{', '.join(map(str, schema['enum']))}")
    if kind == "object":
        required = [key for key in schema.get("required", []) if key not in value]
        if required:
            raise ParameterError(f"{path} 缺少必填字段：{', '.join(required)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - properties.keys()
            if extra:
                raise ParameterError(f"{path} 包含未定义字段；允许字段为 {', '.join(properties)}")
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], path + "." + key)
    elif kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 1000):
            raise ParameterError(f"{path} 数组长度不符合要求")
        for index, item in enumerate(value):
            _validate(item, schema.get("items", {}), f"{path}[{index}]")
    elif kind == "string":
        if len(value) > schema.get("maxLength", 200000) or len(value) < schema.get("minLength", 0):
            raise ParameterError(f"{path} 文本长度不符合要求")
    elif kind in {"integer", "number"}:
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            raise ParameterError(f"{path} 数值超出允许范围")


def normalize_parameters(name, args):
    if name not in SCHEMAS:
        raise ParameterError("未知工具。请仅使用当前 tools 列表中的准确名称")
    if not isinstance(args, dict):
        raise ParameterError("工具参数必须是 JSON 对象")
    result = copy.deepcopy(args)
    if name == "kubernetes" and isinstance(result.get("resource"), str):
        result["resource"] = RESOURCE_ALIASES.get(result["resource"].lower(), result["resource"].lower())
    for field, schema in SCHEMAS[name].get("properties", {}).items():
        value = result.get(field)
        if schema.get("type") == "integer" and isinstance(value, str) and re.fullmatch(r"\d+", value):
            result[field] = int(value)
    _validate(result, SCHEMAS[name], name)
    if name == "ssh_exec" and not result["command"].strip():
        raise ParameterError("ssh_exec.command 不能为空")
    if name == "kubernetes":
        action, resource = result["action"], result["resource"]
        if action in {"get", "logs", "scale", "restart", "delete"} and not result.get("name"):
            raise ParameterError(f"kubernetes.{action} 必须提供 name")
        if action == "scale" and "replicas" not in result:
            raise ParameterError("scale 必须提供 replicas")
        if action == "apply" and not isinstance(result.get("manifest"), dict):
            raise ParameterError("apply 必须提供完整 manifest 对象")
        if action == "logs" and resource != "pods":
            raise ParameterError("logs 的 resource 必须为 pods")
    return result


def feedback(error, *, executed, code="tool_error"):
    return {"error": str(error), "error_code": code, "executed": executed,
            "guidance": "根据错误修正参数或选择其他只读检查；不要重复相同失败操作。" if not executed else "操作可能已执行；先检查实际状态，不要盲目重发有副作用的命令。"}


def compact_result(value, limit=14000):
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded) <= limit:
        return encoded
    if isinstance(value, dict):
        if isinstance(value.get("items"), list):
            result = {key: item for key, item in value.items() if key != "items"}
            result["items"] = []
            for item in value["items"]:
                candidate = {**result, "items": [*result["items"], item]}
                if len(json.dumps(candidate, ensure_ascii=False)) > limit - 300:
                    break
                result["items"].append(item)
            result["_earthai_truncated"] = {"total_items": len(value["items"]), "included_items": len(result["items"]), "guidance": "缩小 namespace 或用 get 读取具体对象，不能把截断结果当完整资源清单"}
            return json.dumps(result, ensure_ascii=False)
        result = dict(value)
        for field in ("stdout", "stderr", "logs", "content"):
            if isinstance(result.get(field), str):
                result[field] = result[field][:max(1500, limit // 3)]
        result["_earthai_truncated"] = True
        if len(json.dumps(result, ensure_ascii=False)) <= limit:
            return json.dumps(result, ensure_ascii=False)
    return json.dumps({"_earthai_truncated": True, "preview": encoded[:limit - 250], "guidance": "结果过长，请缩小查询范围"}, ensure_ascii=False)


class FailureBudget:
    def __init__(self):
        self.failures = Counter()
        self.successful_writes = {}
        self.attempted_writes = set()
        self.consecutive_errors = 0

    @staticmethod
    def key(name, args):
        semantic = {key: value for key, value in args.items() if key != "reason"}
        return name + ":" + json.dumps(semantic, ensure_ascii=False, sort_keys=True)

    def blocked_repeat(self, name, args):
        return self.failures[self.key(name, args)] >= 2

    def record(self, name, args, ok):
        self.consecutive_errors = 0 if ok else self.consecutive_errors + 1
        if not ok:
            self.failures[self.key(name, args)] += 1
        if self.consecutive_errors >= 6:
            raise tools.ToolError("已连续六次未取得有效工具进展，停止自动尝试以避免费用和错误扩散；已有执行记录保留。")


def context_window(messages, budget=100000):
    if len(json.dumps(messages, ensure_ascii=False)) <= budget:
        return messages
    system = messages[0]
    groups = []
    current = []
    for message in messages[1:]:
        if message["role"] == "assistant" and current:
            groups.append(current)
            current = []
        current.append(message)
    if current:
        groups.append(current)
    selected, size = [], len(json.dumps(system, ensure_ascii=False))
    for group in reversed(groups):
        length = len(json.dumps(group, ensure_ascii=False))
        if selected and size + length > budget:
            break
        selected.insert(0, group)
        size += length
    return [system, *[message for group in selected for message in group]]
