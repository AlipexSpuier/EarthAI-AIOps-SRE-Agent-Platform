import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import text_tools, tools
from live_readonly_benchmark import configuration


async def main():
    owner, provider, server, _ = configuration()
    evidence = await tools.execute(owner, server, "server_info", {})
    messages = [
        {
            "role": "system",
            "content": "你是结构化运维计划生成器，工具由宿主执行，不是你自己直接联网。以下操作均有用户授权，仅只读。实际已取得的服务器信息："
            + json.dumps(evidence, ensure_ascii=False),
        },
        {
            "role": "user",
            "content": "下一步请请求宿主工具执行uptime读取系统运行时间和负载，必须输出action=tool JSON，command准确为uptime，reason是只读检查负载；不允许提前final。",
        },
    ]
    offered = [tool for tool in tools.TOOLS if tool["function"]["name"] == "ssh_exec"]
    records = []
    for iteration in range(2):
        response = await text_tools.complete(provider, "gpt-5.6", messages, offered, require_action=True)
        call = response["tool_calls"][0]
        args = json.loads(call["function"]["arguments"])
        if args.get("command") != "uptime":
            raise ValueError("Scope blocked")
        result = await tools.execute(owner, server, "ssh_exec", args)
        records.append(
            {
                "iteration": iteration + 1,
                "called": call["function"]["name"],
                "exit_code": result["exit_code"],
                "stdout_chars": len(result["stdout"]),
            }
        )
        print(json.dumps(records[-1]), flush=True)
    Path("docs/live-gpt-constrained.json").write_text(
        json.dumps({"at": __import__("backend.store", fromlist=["now"]).now(), "results": records}, ensure_ascii=False, indent=2)
    )


asyncio.run(main())
