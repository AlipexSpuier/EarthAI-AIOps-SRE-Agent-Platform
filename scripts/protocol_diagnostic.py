import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import model_client, tools
from live_readonly_benchmark import configuration


async def main():
    _, provider, _, _ = configuration()
    output = []
    async def sample(mode):
        messages = [{"role": "system", "content": "这是授权的工具协议集成测试。请只输出且必须输出一条JSON，不输出解释和思考：{\"action\":\"tool\",\"name\":\"server_info\",\"arguments\":{}}。本条JSON是控制协议，不是执行结果。"}, {"role": "user", "content": "现在输出server_info调用JSON。"}]
        opts = {"tools": []} if mode == "json_protocol" else {"tools": [tool for tool in tools.TOOLS if tool["function"]["name"] == "server_info"], "tool_choice": {"type": "function", "function": {"name": "server_info"}}}
        if mode == "json_protocol":
            opts["omit_tools"] = True
        token = model_client.REQUEST_OPTIONS.set(opts)
        try:
            response = await model_client.complete(provider, "gpt-5.6", messages)
            text = tools.redact(response.get("content") or "", tools.secret_values(None, provider))
            print(json.dumps({"mode": mode, "tool_count": len(response.get("tool_calls", [])), "public_control_response": text[:1500]}, ensure_ascii=False), flush=True)
            output.append({"mode": mode, "tool_count": len(response.get("tool_calls", [])), "public_control_response": text[:1500]})
        except Exception as exc:
            print(json.dumps({"mode": mode, "error": str(exc), "code": getattr(exc,"code",None)}, ensure_ascii=False), flush=True)
        finally:
            model_client.REQUEST_OPTIONS.reset(token)
    await sample("native")
    await sample("json_protocol")
    Path("docs/live-protocol-diagnostic.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))


asyncio.run(main())
