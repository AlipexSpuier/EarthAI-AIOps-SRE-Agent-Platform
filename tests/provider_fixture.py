import asyncio
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()


@app.get("/v1/models")
async def models():
    return {"data": [{"id": name, "object": "model"} for name in ["earthai-e2e-tool-model", "earthai-empty-once", "earthai-tool-only", "earthai-truncated"]]}


def response_message(messages):
    tool_results = [message for message in messages if message["role"] == "tool"]
    if not tool_results:
        return {"role": "assistant", "content": "正在进行端到端测试，我会检查个人空间并生成报告。", "tool_calls": [{"id": "e2e-plan", "type": "function", "function": {"name": "plan", "arguments": '{"steps":["读取个人文件列表","写入验收报告","验证已完成结果"]}'}}]}
    if len(tool_results) == 1:
        return {"role": "assistant", "content": None, "tool_calls": [{"id": "e2e-files", "type": "function", "function": {"name": "list_files", "arguments": "{}"}}]}
    if len(tool_results) == 2:
        return {"role": "assistant", "content": None, "tool_calls": [{"id": "e2e-report", "type": "function", "function": {"name": "write_report", "arguments": '{"name":"E2E验收报告.md","content":"# EarthAI 端到端验收\\n后台真实工具已生成此文件，切页期间任务保持执行。"}'}}]}
    return {"role": "assistant", "content": "端到端验收已完成：已查询个人空间，并通过真实文件工具写入 E2E验收报告.md。页面切换未中止任务。本回复来自本地测试供应商，不是生产模型。"}


empty_seen = set()


@app.post("/v1/chat/completions")
async def completion(request: Request):
    body = await request.json()
    messages = body["messages"]
    message = response_message(messages)
    if body["model"] == "earthai-empty-once":
        user_text = next((message.get("content", "") for message in reversed(messages) if message["role"] == "user"), "")
        key = (user_text, len(messages))
        if key not in empty_seen:
            empty_seen.add(key)
            message = {"role": "assistant", "content": None}
    if body["model"] == "earthai-tool-only" and message.get("tool_calls"):
        message["content"] = None
    finish = "tool_calls" if message.get("tool_calls") else "stop"
    if not body.get("stream"):
        return {"id": "e2e-completion", "object": "chat.completion", "choices": [{"index": 0, "finish_reason": finish, "message": message}]}

    async def stream():
        def frame(delta=None, finish_reason=None):
            return "data: " + json.dumps({"id": "e2e-completion", "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish_reason}]}, ensure_ascii=False) + "\n\n"
        yield ": local streaming fixture\n\n"
        yield frame({"role": "assistant"})
        for offset in range(0, len(message.get("content") or ""), 6):
            await asyncio.sleep(0.12)
            yield frame({"content": message["content"][offset:offset + 6]})
        for index, call in enumerate(message.get("tool_calls", [])):
            yield frame({"tool_calls": [{"index": index, "id": call["id"], "type": "function", "function": {"name": call["function"]["name"], "arguments": ""}}]})
            for offset in range(0, len(call["function"]["arguments"]), 12):
                await asyncio.sleep(0.05)
                yield frame({"tool_calls": [{"index": index, "function": {"arguments": call["function"]["arguments"][offset:offset + 12]}}]})
        if body["model"] == "earthai-truncated":
            return
        await asyncio.sleep(0.15)
        yield frame(finish_reason=finish)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("EARTHAI_FIXTURE_PORT", "9909")))
