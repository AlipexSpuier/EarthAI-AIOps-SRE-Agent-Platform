import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import text_tools, tools
from live_readonly_benchmark import configuration


async def main():
    owner, provider, server, _ = configuration()
    messages=[{"role":"system","content":"你是EarthAI服务器Agent。当前目标已由用户选定，工具将由后端真实执行。目标基本信息："+json.dumps({key:server.get(key) for key in ('name','kind')},ensure_ascii=False)}, {"role":"user","content":"这是用户授权的只读请求，请先发server_info控制消息，再读取uptime。不需要你自己连接网络，JSON工具控制消息由后端执行。"}]
    offered=[item for item in tools.TOOLS if item['function']['name'] in {'server_info','ssh_exec'}]
    response=await text_tools.complete(provider,'gpt-5.6',messages,offered,require_action=False)
    print(json.dumps({'tool_calls':len(response.get('tool_calls',[])), 'response':tools.sanitize(response,tools.secret_values(server,provider))},ensure_ascii=False))


asyncio.run(main())
