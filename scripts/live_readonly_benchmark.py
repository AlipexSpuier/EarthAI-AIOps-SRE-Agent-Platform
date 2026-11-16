from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import model_client, reliability, store, text_tools, tools

SAFE_COMMANDS = {"uptime", "uname -a", "free -m", "df -h"}


def configuration():
    with store.connect() as db:
        provider_row = db.execute("SELECT * FROM entities WHERE kind='providers' ORDER BY updated_at DESC LIMIT 1").fetchone()
    if not provider_row:
        raise RuntimeError("没有可测试的供应商")
    provider = store.entity(provider_row)
    owner = provider_row["owner"]
    servers = store.list_entities(owner, "servers")
    server = next((item for item in servers if item.get("kind") == "ssh"), None)
    if not server:
        raise RuntimeError("没有 SSH 测试目标")
    models = [name for name in [provider.get("default_model"), "gpt-5.6", "claude-opus-4-8"] if name and name in provider.get("models", [])]
    return owner, provider, server, list(dict.fromkeys(models))


async def episode(owner, provider, server, model, number, enhanced=False):
    record = {"model": model, "episode": number, "requests": 0, "tools": [], "notices": [], "success": False, "protocol": "json" if enhanced else "native"}
    started = time.monotonic()
    messages = [{"role": "system", "content": "你是EarthAI只读集成测试Agent。用户已通过平台选择并授权以下目标，工具由本后端真实执行，你只需发出协议调用，不要误认为没有执行环境。目标：" + json.dumps({key: server.get(key) for key in ("name", "kind", "host", "port", "username")}, ensure_ascii=False) + "。本次必须真实调用工具，不要只写计划。先调用server_info确认目标，然后调用ssh_exec执行uptime，最后根据真实工具输出用一句话报告是否拿到系统负载。禁止任何写操作。所有工具参数必须是完整JSON对象，ssh_exec必须有command和reason。不要读取密钥。"},
                {"role": "user", "content": f"只读验收编号{number}。请检查已选择服务器的系统运行时间，只允许server_info及ssh_exec(command=uptime)。必须使用真实工具结果，不能虚构已执行。"}]
    try:
        async with asyncio.timeout(160):
            for turn in range(5):
                record["requests"] += 1
                metadata = {}
                def on_event(event, data):
                    if event == "notice":
                        record["notices"].append({key: data[key] for key in ("code", "attempt", "delay_ms") if key in data})
                    elif event == "metadata":
                        metadata.update(data)
                if enhanced:
                    verified = any(item.get("name") == "ssh_exec" and item.get("exit_code") == 0 for item in record["tools"])
                    request_tools = [item for item in tools.TOOLS if item["function"]["name"] in ({"server_info", "ssh_exec"} if not verified else set())]
                    opts = {"tools": request_tools, "tool_choice": {"type": "function", "function": {"name": "ssh_exec"}} if not verified else "none"}
                    token = model_client.REQUEST_OPTIONS.set(opts)
                    try:
                        message = await text_tools.complete(provider, model, messages, [item for item in tools.TOOLS if item["function"]["name"] in {"server_info", "ssh_exec"}], on_event, not verified)
                    finally:
                        model_client.REQUEST_OPTIONS.reset(token)
                else:
                    message = await model_client.complete(provider, model, messages, on_event=on_event)
                record.setdefault("responses", []).append({key: metadata[key] for key in ("http_status", "finish_reason", "content_length", "tool_count", "reasoning_present", "request_attempt") if key in metadata})
                messages.append(message)
                calls = message.get("tool_calls", [])
                if not calls:
                    record["success"] = any(item.get("exit_code") == 0 and item["name"] == "ssh_exec" for item in record["tools"]) and bool(message.get("content"))
                    if not record["success"]:
                        record["error_code"] = "no_verified_command"
                        record["test_final_excerpt"] = tools.redact(message.get("content") or "", tools.secret_values(server, provider))[:600]
                    break
                for call in calls:
                    name = call["function"]["name"]
                    args = reliability.normalize_parameters(name, json.loads(call["function"]["arguments"])) if enhanced else json.loads(call["function"]["arguments"])
                    if name not in {"server_info", "ssh_exec"} or (name == "ssh_exec" and args.get("command") != "uptime"):
                        result = {"error": "本验收仅允许server_info或ssh_exec执行uptime，请修正调用。"}
                        record["tools"].append({"name": name, "blocked_by_test_scope": True})
                    else:
                        result = await tools.execute(owner, server, name, args)
                        record["tools"].append({"name": name, "exit_code": result.get("exit_code"), "selected": result.get("selected"), "output_chars": sum(len(result.get(key, "")) for key in ("stdout", "stderr"))})
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": store.dumps(result)})
            else:
                record["error_code"] = "episode_step_budget"
    except Exception as exc:
        record["error_code"] = getattr(exc, "code", type(exc).__name__)
        record["diagnostics"] = getattr(exc, "metadata", {})
        record["error"] = tools.redact(str(exc), tools.secret_values(server, provider))[:1200]
        if getattr(exc, "public_response", ""):
            record["test_protocol_reply"] = tools.redact(exc.public_response, tools.secret_values(server, provider))[:1500]
    record["duration_seconds"] = round(time.monotonic() - started, 2)
    if enhanced and record["success"]:
        reliability.remember_protocol(owner, provider["id"], model, "json")
    return record


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--models", default="")
    parser.add_argument("--label", default="live-readonly")
    parser.add_argument("--enhanced", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 4:
        raise ValueError("有限验收仅允许每模型1–4次")
    owner, provider, server, models = configuration()
    if args.models:
        requested = args.models.split(",")
        models = [model for model in requested if model in provider.get("models", [])]
    if not models or len(models) > 3:
        raise ValueError("验收最多3个已配置模型")
    report = {"label": args.label, "started_at": store.now(), "scope": "Paid configured models; configured SSH host; ONLY server_info and uptime; no infrastructure writes", "results": []}
    for model in models:
        for number in range(1, args.repeats + 1):
            print(f"START {args.label} model={model} episode={number}", flush=True)
            result = await episode(owner, provider, server, model, number, args.enhanced)
            report["results"].append(result)
            print(json.dumps({key: result[key] for key in ("model", "episode", "success", "requests", "error_code", "duration_seconds") if key in result}, ensure_ascii=False), flush=True)
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    report["finished_at"] = store.now()
    report["summary"] = {"episodes": len(report["results"]), "succeeded": sum(bool(item["success"]) for item in report["results"]), "model_requests": sum(item["requests"] for item in report["results"]), "verified_ssh_commands": sum(step.get("name") == "ssh_exec" and step.get("exit_code") == 0 for item in report["results"] for step in item["tools"])}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
