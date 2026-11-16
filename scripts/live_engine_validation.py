import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import engine, store, tools
from live_readonly_benchmark import configuration


async def main():
    owner, provider, server, _ = configuration()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/live-engine-validation.json")
    parser.add_argument("--models", default="gemini-3.1-pro-preview-all,claude-opus-4-8")
    args = parser.parse_args()
    records = []
    for model in args.models.split(","):
        conversation = store.save_entity(
            owner,
            "conversations",
            {
                "title": "只读可靠性验收 · " + model,
                "server_id": server["id"],
                "provider_id": provider["id"],
                "model": model,
                "control_level": "observe",
                "agent_id": None,
                "project_id": None,
            },
        )
        run = engine.create_run(
            owner,
            conversation,
            "请实际检查这台已选服务器的运行时间与负载。先确认目标，只执行 uptime 这一条只读命令，依据真实结果做简短总结。不要修改服务器或创建文件。",
        )
        task = engine.TASKS[run["id"]]
        try:
            await asyncio.wait_for(asyncio.shield(task), 180)
        except TimeoutError:
            engine.cancel_run(owner, run["id"])
            await asyncio.gather(task, return_exceptions=True)
        result = store.get_run(owner, run["id"])
        events = store.events(run["id"])
        tools_executed = [event for event in events if event["type"] == "tool_result"]
        record = {
            "model": model,
            "run_id": run["id"],
            "conversation_id": conversation["id"],
            "status": result["status"],
            "step_count": result["step_count"],
            "error": tools.redact(result.get("error", ""), tools.secret_values(server, provider)),
            "tools": [
                {
                    "name": event["data"].get("name"),
                    "ok": event["data"].get("ok"),
                    "executed": event["data"].get("executed"),
                    "outcome": event["data"].get("outcome"),
                    "exit_code": event["data"].get("output", {}).get("exit_code")
                    if isinstance(event["data"].get("output"), dict)
                    else None,
                }
                for event in tools_executed
            ],
            "notices": [event["data"].get("code") for event in events if event["type"] == "notice"],
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
        Path(args.output).write_text(
            json.dumps(
                {
                    "at": store.now(),
                    "scope": "full engine, user authorized paid model and configured host, observe level, uptime only",
                    "results": records,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


asyncio.run(main())
