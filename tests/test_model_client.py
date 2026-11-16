import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from backend import model_client, tools

PROVIDER = {"base_url": "https://offline.example/v1/", "api_key": "sealed-test-only"}
MESSAGES = [{"role": "user", "content": "offline request"}]
KEY = "sk-offline-fixture-key"
_MISSING = object()


class Pieces(httpx.AsyncByteStream):
    def __init__(self, *chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk

    async def aclose(self):
        self.closed = True


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def sse(value):
    return b"data: " + (value.encode() if isinstance(value, str) else encode(value)) + b"\n\n"


def delta(content=_MISSING, *, finish=None, **fields):
    if content is not _MISSING:
        fields["content"] = content
    return {"choices": [{"index": 0, "delta": fields, "finish_reason": finish}]}


def call(*, id="call_test", name="server_info", arguments="{}"):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": arguments}}


def completion(content=_MISSING, *, finish="stop", message=None, **fields):
    result = dict(message or {})
    result.setdefault("role", "assistant")
    if content is not _MISSING:
        result["content"] = content
    result.update(fields)
    return {"choices": [{"index": 0, "message": result, "finish_reason": finish}]}


def json_response(body, *, content_type="application/json", status=200):
    return httpx.Response(status, headers={"content-type": content_type}, stream=Pieces(encode(body)))


def stream_response(*chunks, content_type="text/event-stream", status=200):
    return httpx.Response(status, headers={"content-type": content_type}, stream=Pieces(*chunks))


def repeat_response(response, count=2):
    return [httpx.Response(response.status_code, headers=response.headers,
        stream=Pieces(*response.stream.chunks)) for _ in range(count)]


@pytest.fixture
def install_http(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(tools, "secret_values", lambda server, provider: [KEY])
    monkeypatch.setattr(model_client, "_retry_delay", lambda attempt, retry_after=None: 0)

    def install(responses):
        requests, configs = [], []
        iterator = iter(responses) if not callable(responses) else None

        async def handler(request):
            requests.append(request)
            result = responses(request) if callable(responses) else next(iterator)
            if isinstance(result, BaseException):
                raise result
            return result

        def client(**kwargs):
            configs.append(kwargs)
            return original_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(model_client.httpx, "AsyncClient", client)
        return SimpleNamespace(requests=requests, configs=configs)

    return install


async def run(events=None):
    return await model_client.complete(PROVIDER, "offline-model", MESSAGES,
        on_event=(lambda event, data: events.append((event, data))) if events is not None else None)


def notices(events):
    return [data for event, data in events if event == "notice"]


def metadata(events):
    return [data for event, data in events if event == "metadata"]


def public(events):
    return [data["content"] for event, data in events if event == "content"]


async def test_content_arrives_before_stream_ends_and_request_contract(install_http):
    arrived, release = asyncio.Event(), asyncio.Event()

    class Gated(Pieces):
        async def __aiter__(self):
            yield sse(delta("早到"))
            await release.wait()
            yield sse(delta("内容"))
            yield sse(delta(finish="stop"))
            yield sse("[DONE]")

    stream = Gated()
    mock = install_http([httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)])
    events = []

    def callback(event, data):
        events.append((event, data))
        if event == "content":
            arrived.set()

    task = asyncio.create_task(model_client.complete(PROVIDER, "offline-model", MESSAGES, on_event=callback))
    try:
        await asyncio.wait_for(arrived.wait(), 1)
        assert not task.done()
        assert public(events) == ["早到"]
    finally:
        release.set()
    assert await task == {"role": "assistant", "content": "早到内容"}
    assert public(events) == ["早到", "早到内容"]
    assert stream.closed
    request = mock.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://offline.example/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer " + KEY
    payload = json.loads(request.content)
    assert payload == {"model": "offline-model", "messages": MESSAGES, "tools": tools.TOOLS, "tool_choice": "auto", "stream": True}
    assert mock.configs[0]["trust_env"] is False
    assert mock.configs[0]["follow_redirects"] is False
    assert mock.configs[0]["timeout"].connect == 15
    assert mock.configs[0]["timeout"].read == 120
    assert metadata(events)[-1]["streamed"] is True


@pytest.mark.parametrize("split_name", [True, False])
async def test_interleaved_fragmented_calls_without_text(install_http, split_name):
    frames = [
        delta(tool_calls=[{"index": 1, "id": "call_", "type": "function", "function": {"name": "server_" if split_name else "server_info", "arguments": "{"}}]),
        delta(tool_calls=[{"index": 0, "id": "call_zero", "function": {"name": "ssh_" if split_name else "ssh_exec", "arguments": '{"command":"'}}]),
        delta(tool_calls=[{"index": 1, "id": "one", "function": {**({"name": "info"} if split_name else {}), "arguments": "}"}}]),
        delta(tool_calls=[{"index": 0, "function": {**({"name": "exec"} if split_name else {}), "arguments": 'uname -a"}'}}]),
        delta(finish="tool_calls"),
    ]
    install_http([stream_response(*(sse(frame) for frame in frames), sse("[DONE]"))])
    events = []
    result = await run(events)
    assert result == {"role": "assistant", "content": None, "tool_calls": [
        call(id="call_zero", name="ssh_exec", arguments='{"command":"uname -a"}'),
        call(id="call_one"),
    ]}
    assert not public(events)
    assert metadata(events)[-1]["tool_count"] == 2


async def test_valid_arguments_prefix_is_not_returned_before_final_validation(install_http):
    mock = install_http(repeat_response(stream_response(
        sse(delta(tool_calls=[{"index": 0, **call()}])),
        sse(delta(tool_calls=[{"index": 0, "function": {"arguments": "BROKEN"}}])),
        sse(delta(finish="tool_calls")), sse("[DONE]"),
    )))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "invalid_tool_call"
    assert len(mock.requests) == 2


async def test_multiline_crlf_utf8_split_comments_role_and_usage(install_http):
    frame = encode(delta("多字节中文"))
    pretty = json.dumps(delta("多字节中文"), ensure_ascii=False, indent=2)
    text = b": comment\r\n\r\n" + sse(delta(role="assistant"))
    text += b"event: heartbeat\r\ndata: not-json-heartbeat\r\n\r\n"
    text += b"".join(b"data: " + line.encode() + b"\r\n" for line in pretty.splitlines()) + b"\r\n"
    text += sse(delta(finish="stop"))
    text += sse({"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}})
    text += b"data: [DONE]\r\n\r\n"
    assert "多字节" in frame.decode()
    install_http([stream_response(*(text[index:index + 1] for index in range(len(text))))])
    events = []
    assert await run(events) == {"role": "assistant", "content": "多字节中文"}
    assert public(events) == ["多字节中文"]
    assert metadata(events)[-1]["usage"] == {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}


@pytest.mark.parametrize("content_type", ["application/json", "text/plain", "", "text/event-stream"])
async def test_json_returned_to_stream_request_is_not_fake_streamed(install_http, content_type):
    mock = install_http([json_response(completion("完整公开回答"), content_type=content_type)])
    events = []
    assert await run(events) == {"role": "assistant", "content": "完整公开回答"}
    assert public(events) == ["完整公开回答"]
    assert metadata(events)[-1]["streamed"] is False
    assert len(mock.requests) == 1
    assert [notice["code"] for notice in notices(events)] == ["provider_buffered_response"]


@pytest.mark.parametrize("content_type", ["text/plain", "application/json", ""])
async def test_sse_with_missing_or_wrong_content_type_is_incremental(install_http, content_type):
    install_http([stream_response(sse(delta("一")), sse(delta("二")), sse("[DONE]"), content_type=content_type)])
    events = []
    assert (await run(events))["content"] == "一二"
    assert public(events) == ["一", "一二"]
    assert metadata(events)[-1]["streamed"] is True


async def test_explicit_text_blocks_only_and_hidden_blocks_never_become_text(install_http):
    blocks = [{"type": "text", "text": "公开"}, {"type": "output_text", "text": "文本"},
        {"type": "thinking", "thinking": "hidden_thinking"}, {"type": "image", "text": "not_public"}]
    install_http([json_response(completion(blocks))])
    events = []
    assert await run(events) == {"role": "assistant", "content": "公开文本"}
    assert public(events) == ["公开文本"]
    assert metadata(events)[-1]["reasoning_present"] is True
    assert metadata(events)[-1]["reasoning_length"] == len("hidden_thinking")


async def test_stream_text_blocks_and_hidden_reasoning(install_http):
    install_http([stream_response(sse(delta(reasoning_content="secret reasoning")),
        sse(delta([{"type": "text", "text": "公开"}, {"type": "output_text", "text": "答案"}])), sse("[DONE]"))])
    events = []
    assert (await run(events))["content"] == "公开答案"
    assert public(events) == ["公开答案"]
    assert metadata(events)[-1]["reasoning_length"] == len("secret reasoning")


@pytest.mark.parametrize("body", [
    completion(None), completion(""), completion([]), completion([{"type": "text", "text": ""}]),
    completion([{"type": "image", "text": "must not be public"}]), {"choices": []}, {"usage": {"total_tokens": 2}}, {},
    completion(None, reasoning_content="hidden reasoning"), completion(None, thinking="hidden thought"), completion(None, reasoning="hidden reasoning"),
])
async def test_empty_response_recovers_exactly_once_with_same_request(install_http, body):
    mock = install_http([json_response(body), json_response(completion("恢复成功"))])
    events = []
    assert (await run(events))["content"] == "恢复成功"
    assert len(mock.requests) == 2
    assert mock.requests[0].content == mock.requests[1].content
    assert [notice["code"] for notice in notices(events)] == ["empty_response_retry", "provider_buffered_response"]
    assert public(events) == ["恢复成功"]


@pytest.mark.parametrize("reasoning", [False, True])
async def test_second_empty_is_neutral_error_with_finish_and_reason(install_http, reasoning):
    body = completion(None, **({"reasoning_content": "NEVER SHOW THIS"} if reasoning else {}))
    mock = install_http([json_response(body), json_response(body)])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "empty_response"
    assert "finish_reason=stop" in str(error.value)
    assert ("reasoning_only" if reasoning else "empty_content") in str(error.value)
    assert "不支持工具" not in str(error.value)
    assert len(mock.requests) == 2 and len(notices(events)) == 1
    assert not public(events)
    assert "NEVER SHOW THIS" not in json.dumps(events) + str(error.value)


async def test_empty_stream_with_done_retries_once(install_http):
    mock = install_http([stream_response(sse(delta(role="assistant")), sse("[DONE]")), json_response(completion("恢复"))])
    events = []
    assert (await run(events))["content"] == "恢复"
    assert len(mock.requests) == 2
    assert [notice["code"] for notice in notices(events)] == ["empty_response_retry", "provider_buffered_response"]


@pytest.mark.parametrize("body", [
    completion("", finish="content_filter"), completion(None, refusal="private refusal reason"),
    completion([{"type": "refusal", "refusal": "private refusal reason"}]),
    completion(None, finish="content_filter", tool_calls=[call()]),
])
async def test_refusal_does_not_retry_or_release_calls(install_http, body):
    mock = install_http([json_response(body)])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "model_refusal"
    assert not public(events)
    assert len(mock.requests) == 1 and not notices(events)
    assert "private refusal reason" not in str(error.value) + json.dumps(events)


@pytest.mark.parametrize("finish,code", [("length", "response_length"), ("content_filter", "model_refusal")])
async def test_stream_finish_errors_never_release_calls_and_only_length_repairs(install_http, finish, code):
    count = 2 if finish == "length" else 1
    mock = install_http(repeat_response(stream_response(sse(delta("部分公开文字")), sse(delta(tool_calls=[{"index": 0, **call()}])),
        sse(delta(finish=finish)), sse("[DONE]")), count))
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == code
    assert public(events) == (["部分公开文字", "", "部分公开文字"] if count == 2 else ["部分公开文字"])
    assert len(mock.requests) == count
    assert len(notices(events)) == count - 1


@pytest.mark.parametrize("chunks,code", [
    ([sse(delta("partial")), b"data: invalid-json\n\n"], "malformed_response"),
    ([sse(delta("partial"))], "stream_truncated"),
    ([sse(delta(tool_calls=[{"index": 0, **call()}]))], "stream_truncated"),
    ([sse(delta("partial")), httpx.ReadError("contains-secret")], "stream_interrupted"),
    ([sse(delta(tool_calls=[{"index": 0, **call()}])), httpx.RemoteProtocolError("contains-secret")], "stream_interrupted"),
    ([sse(delta("partial")), httpx.ReadTimeout("contains-secret")], "request_timeout"),
    ([sse({"choices": [], "usage": {"total_tokens": 8}})], "stream_truncated"),
    ([b"data: {\"choices\": [\n\n"], "malformed_response"),
])
async def test_malformed_and_interrupted_streams_retry_with_bounded_requests(install_http, chunks, code):
    count = 2 if code == "malformed_response" else 4
    mock = install_http(repeat_response(stream_response(*chunks), count))
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == code
    assert len(mock.requests) == count and len(notices(events)) == count - 1
    assert error.value.metadata["request_attempt"] == count
    assert "contains-secret" not in str(error.value) + json.dumps(events)


@pytest.mark.parametrize("terminal", [sse("[DONE]"), sse(delta(finish="stop")), b"data: [DONE]"])
async def test_done_without_finish_or_finish_without_done_is_valid(install_http, terminal):
    install_http([stream_response(sse(delta("valid")), terminal)])
    assert await run() == {"role": "assistant", "content": "valid"}


async def test_finish_then_usage_without_done_is_valid(install_http):
    install_http([stream_response(sse(delta(tool_calls=[{"index": 0, **call()}])), sse(delta(finish="tool_calls")),
        sse({"choices": [], "usage": {"total_tokens": 9}}))])
    assert (await run())["tool_calls"] == [call()]


async def test_trailing_data_after_done_is_not_read(install_http):
    install_http([stream_response(sse(delta("done")), sse("[DONE]"), httpx.ReadError("must not read"))])
    assert (await run())["content"] == "done"


@pytest.mark.parametrize("status", [301, 307, 400, 401, 403, 422])
async def test_http_errors_are_not_retried_and_no_body_is_exposed(install_http, status):
    response = json_response({"error": {"message": "key=" + KEY + " thinking=PRIVATE"}}, status=status)
    response.headers["location"] = "https://must-not-follow.example"
    mock = install_http([response])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "http_error"
    assert error.value.metadata["http_status"] == status
    assert f"HTTP {status}" in str(error.value)
    assert len(mock.requests) == 1 and not notices(events)
    assert KEY not in str(error.value) + json.dumps(events)
    assert "PRIVATE" not in str(error.value) + json.dumps(events)


@pytest.mark.parametrize("status", [400, 422])
@pytest.mark.parametrize("error_body", [
    {"error": {"message": "Streaming is not supported by this model"}},
    {"error": {"message": "This model does not support streaming"}},
    {"error": {"message": "Unsupported parameter: 'stream'"}},
    {"error": {"message": "不支持流式输出"}},
    {"error": {"param": "stream", "code": "unsupported_parameter"}},
])
async def test_only_explicit_stream_unsupported_falls_back_once(install_http, status, error_body):
    mock = install_http([json_response(error_body, status=status), json_response(completion("非流式成功"))])
    events = []
    assert (await run(events))["content"] == "非流式成功"
    payloads = [json.loads(request.content) for request in mock.requests]
    assert [payload.pop("stream") for payload in payloads] == [True, False]
    assert payloads[0] == payloads[1]
    assert [notice["code"] for notice in notices(events)] == ["stream_fallback", "provider_buffered_response"]
    assert public(events) == ["非流式成功"]


@pytest.mark.parametrize("status,error_body", [
    (400, {"error": {"message": "tools are not supported"}}),
    (422, {"error": {"message": "invalid stream value"}}),
    (400, {"error": {"message": "stream processing failed"}}),
    (400, {"error": {"message": "stream is enabled but tools not supported"}}),
    (400, {"message": "streaming not supported"}),
    (401, {"error": {"message": "streaming not supported"}}),
    (200, {"error": {"message": "streaming not supported"}}),
])
async def test_unrelated_errors_never_disable_streaming(install_http, status, error_body):
    mock = install_http([json_response(error_body, status=status)])
    events = []
    with pytest.raises(model_client.ModelResponseError):
        await run(events)
    assert len(mock.requests) == 1 and not notices(events)


async def test_stream_false_is_not_retried_again_when_it_also_rejects_stream(install_http):
    unsupported = {"error": {"message": "stream is not supported"}}
    mock = install_http([json_response(unsupported, status=400), json_response(unsupported, status=400)])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "http_error"
    assert len(mock.requests) == 2 and len(notices(events)) == 1


async def test_fallback_and_empty_retry_have_independent_bounded_budgets(install_http):
    mock = install_http([json_response({"error": "streaming not supported"}, status=400),
        json_response(completion(None)), json_response(completion(None))])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "empty_response"
    assert [json.loads(request.content)["stream"] for request in mock.requests] == [True, False, False]
    assert [notice["code"] for notice in notices(events)] == ["stream_fallback", "empty_response_retry"]


@pytest.mark.parametrize("body", [
    {"candidates": [{"content": {"parts": [{"functionCall": {"name": "ssh_exec", "args": {}}}]}}]},
    {"output": [{"type": "function_call", "name": "ssh_exec", "arguments": "{}"}]},
])
async def test_native_gemini_and_responses_are_not_interpreted_as_tools(install_http, body):
    mock = install_http([json_response(body)])
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "incompatible_endpoint"
    assert "chat/completions" in str(error.value)
    assert len(mock.requests) == 1


@pytest.mark.parametrize("body", [
    [], "opaque", {"opaque_sensitive_key": "SECRET"}, {"choices": "SECRET"}, {"choices": [None]},
    {"choices": [{"message": "SECRET"}]}, {"choices": [{"message": {"content": 5}}]},
    completion(message={"role": "tool", "content": "SECRET"}), completion({"text": "SECRET"}),
    completion([{"type": "text", "text": {"value": "SECRET"}}]), completion(["SECRET"]),
    completion("SECRET", finish="secret_unknown_reason"),
])
async def test_opaque_or_invalid_json_shapes_are_safe_errors(install_http, body):
    mock = install_http(repeat_response(json_response(body)))
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "malformed_response"
    assert len(mock.requests) == 2 and not public(events)
    assert [notice["code"] for notice in notices(events)] == ["response_repair_retry"]
    assert "SECRET" not in str(error.value) + json.dumps(events)
    assert "opaque_sensitive_key" not in json.dumps(error.value.metadata)
    assert "secret_unknown_reason" not in json.dumps(error.value.metadata)


@pytest.mark.parametrize("arguments", ["", "{", "[]", "null", '"string"', "1", '{"x":NaN}', '{"x":Infinity}', '{"a":1}garbage'])
async def test_tool_arguments_must_be_complete_json_objects(install_http, arguments):
    mock = install_http(repeat_response(json_response(completion(None, tool_calls=[call(arguments=arguments)]))))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "invalid_tool_call"
    assert len(mock.requests) == 2


@pytest.mark.parametrize("name", ["", "invalid name", "module.tool", "../ssh_exec", "9invalid", "名字", "x" * 65])
async def test_tool_name_must_be_identifier(install_http, name):
    install_http(repeat_response(json_response(completion(None, tool_calls=[call(name=name)]))))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "invalid_tool_call"


@pytest.mark.parametrize("calls", [
    [call(), call()], [call(name=None)],
    [{"id": "x", "type": "custom", "function": {"name": "server_info", "arguments": "{}"}}],
    [{"id": "x", "function": {"name": "server_info"}}], ["wrong"], "wrong",
    [call(), *[call(id=f"call_{index}") for index in range(12)]],
])
async def test_invalid_or_excessive_tool_calls_are_atomic_errors(install_http, calls):
    install_http(repeat_response(json_response(completion("must not release JSON content", tool_calls=calls))))
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "invalid_tool_call"
    assert not public(events)


async def test_exactly_twelve_tools_and_text_are_valid(install_http):
    calls = [call(id=f"call_{index}") for index in range(12)]
    install_http([json_response(completion("准备执行", finish="tool_calls", tool_calls=calls))])
    result = await run()
    assert result == {"role": "assistant", "content": "准备执行", "tool_calls": calls}


@pytest.mark.parametrize("fragment", [
    {"index": 12, **call()}, {"index": -1, **call()}, {"index": True, **call()},
    {"index": "0", **call()}, {"index": 1, **call()},
    {"index": 0, "id": "call", "function": "not-object"},
])
async def test_invalid_stream_indices_and_fragments(install_http, fragment):
    install_http(repeat_response(stream_response(sse(delta(tool_calls=[fragment])), sse("[DONE]"))))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "invalid_tool_call"


@pytest.mark.parametrize("streamed", [False, True])
async def test_legacy_function_call_normalizes_to_modern(install_http, streamed):
    if streamed:
        response = stream_response(sse(delta(function_call={"name": "server_", "arguments": "{"})),
            sse(delta(function_call={"name": "info", "arguments": "}"})), sse(delta(finish="function_call")), sse("[DONE]"))
    else:
        response = json_response(completion(None, finish="function_call", function_call={"name": "server_info", "arguments": "{}"}))
    install_http([response])
    result = await run()
    assert set(result) == {"role", "content", "tool_calls"}
    assert result["content"] is None
    tool = result["tool_calls"][0]
    assert tool["id"].startswith("call_")
    assert tool["type"] == "function"
    assert tool["function"] == {"name": "server_info", "arguments": "{}"}


async def test_mixed_legacy_and_modern_tools_are_rejected(install_http):
    install_http(repeat_response(json_response(completion(None, tool_calls=[call()], function_call={"name": "server_info", "arguments": "{}"}))))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "invalid_tool_call"


@pytest.mark.parametrize("streamed", [False, True])
async def test_content_limit(install_http, streamed):
    if streamed:
        response = stream_response(sse(delta("x" * 60_000)), sse(delta("x" * 40_001)), sse("[DONE]"))
    else:
        response = json_response(completion("x" * 100_001))
    mock = install_http([response])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "response_limit"
    assert len(mock.requests) == 1
    assert all(len(text) <= 100_000 for text in public(events))


async def test_content_exactly_at_limit_is_not_redact_truncated(install_http):
    install_http([json_response(completion("x" * 100_000))])
    assert len((await run())["content"]) == 100_000


@pytest.mark.parametrize("total", [False, True])
async def test_argument_byte_limits_per_call_and_total(install_http, total):
    if total:
        calls = [call(id=f"call_{index}", arguments=json.dumps({"x": "a" * 65_000})) for index in range(9)]
    else:
        calls = [call(arguments=json.dumps({"x": "中" * 22_000}, ensure_ascii=False))]
    install_http([json_response(completion(None, tool_calls=calls))])
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "response_limit"


async def test_split_arguments_enforce_cumulative_limit(install_http):
    install_http([stream_response(sse(delta(tool_calls=[{"index": 0, **call(arguments='{"x":"' + "a" * 40_000)}])),
        sse(delta(tool_calls=[{"index": 0, "function": {"arguments": "a" * 30_000 + '"}'}}])), sse("[DONE]"))])
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "response_limit"


async def test_metadata_allowlist_excludes_secrets_hidden_text_dynamic_keys_and_values(install_http):
    body = completion("public answer", reasoning_content="PRIVATE_REASONING_" + KEY, thinking={"private_key_name": "HIDDEN_THINKING"})
    body["sensitive_dynamic_name_" + KEY] = "RAW_BODY"
    body["id"] = KEY
    body["model"] = "RAW_MODEL"
    body["choices"][0]["message"]["sensitive_key"] = "PRIVATE_MESSAGE"
    body["usage"] = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "api_key": KEY,
        "unknown_usage_key": 88, "input_tokens": "PRIVATE_USAGE", "output_tokens": True,
        "completion_tokens_details": {"reasoning_tokens": 7, "reasoning_text": "PRIVATE_DETAIL", KEY: 99}}
    install_http([json_response(body)])
    events = []
    assert (await run(events))["content"] == "public answer"
    safe = metadata(events)[-1]
    assert safe["usage"] == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3,
        "completion_tokens_details": {"reasoning_tokens": 7}}
    assert safe["reasoning_present"] is True
    assert safe["reasoning_length"] == len("PRIVATE_REASONING_" + KEY) + len("HIDDEN_THINKING")
    assert safe["message_keys"] == ["content", "reasoning_content", "role", "thinking"]
    diagnostic = json.dumps(safe)
    for secret in (KEY, "PRIVATE", "RAW_BODY", "RAW_MODEL", "HIDDEN_THINKING", "sensitive", "unknown_usage_key", "public answer"):
        assert secret not in diagnostic


async def test_in_band_sse_error_is_not_fallback_and_does_not_leak(install_http):
    mock = install_http([stream_response(sse(delta("partial")), sse({"error": {"message": KEY}}))])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "provider_error"
    assert len(mock.requests) == 1 and not notices(events)
    assert KEY not in str(error.value) + json.dumps(metadata(events))


@pytest.mark.parametrize("failure", [RuntimeError("callback sentinel"), httpx.ReadError("callback sentinel"), TimeoutError("callback sentinel")])
async def test_content_callback_exceptions_propagate_without_retry(install_http, failure):
    mock = install_http([stream_response(sse(delta("public")), sse("[DONE]"))])

    def callback(event, data):
        raise failure

    with pytest.raises(type(failure)) as error:
        await model_client.complete(PROVIDER, "offline-model", MESSAGES, on_event=callback)
    assert error.value is failure
    assert len(mock.requests) == 1


async def test_notice_callback_exception_does_not_send_retry(install_http):
    mock = install_http([json_response(completion(None))])
    failure = ValueError("notice callback sentinel")

    def callback(event, data):
        if event == "notice":
            raise failure

    with pytest.raises(ValueError) as error:
        await model_client.complete(PROVIDER, "offline-model", MESSAGES, on_event=callback)
    assert error.value is failure
    assert len(mock.requests) == 1


async def test_cancellation_closes_stream_and_is_not_wrapped(install_http):
    started, waiting = asyncio.Event(), asyncio.Event()

    class Blocking(Pieces):
        async def __aiter__(self):
            yield sse(delta("already visible"))
            started.set()
            await waiting.wait()

    stream = Blocking()
    mock = install_http([httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)])
    task = asyncio.create_task(run())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed
    assert len(mock.requests) == 1


async def test_total_asyncio_timeout_closes_stream_and_retries_with_reset(install_http, monkeypatch):
    monkeypatch.setattr(model_client, "REQUEST_TIMEOUT", 0.02)

    class Blocking(Pieces):
        async def __aiter__(self):
            yield sse(delta("partial"))
            await asyncio.Event().wait()

    streams = [Blocking() for _ in range(4)]
    mock = install_http([httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream) for stream in streams])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "request_timeout"
    assert len(mock.requests) == 4 and all(stream.closed for stream in streams)
    assert public(events) == ["partial", "", "partial", "", "partial", "", "partial"]


@pytest.mark.parametrize("base_url", ["ftp://offline.example", "https://user:password@offline.example/v1", "https://offline.example/v1?key=SECRET",
    "https://offline.example/v1#SECRET", "http://169.254.169.254", "http://metadata.google.internal", "not a URL"])
async def test_invalid_provider_urls_are_safe_local_errors(install_http, base_url):
    mock = install_http([])
    with pytest.raises(model_client.ModelResponseError) as error:
        await model_client.complete({**PROVIDER, "base_url": base_url}, "offline-model", MESSAGES)
    assert error.value.code == "provider_configuration"
    assert not mock.requests
    assert "SECRET" not in str(error.value)


async def test_secret_decryption_failure_is_safe_and_local(install_http, monkeypatch):
    mock = install_http([])

    def fail(*args):
        raise ValueError("PRIVATE_KEY" + KEY)

    monkeypatch.setattr(tools, "secret_values", fail)
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "provider_configuration"
    assert KEY not in str(error.value)
    assert not mock.requests


async def test_invalid_utf8_repairs_once_then_is_a_safe_error(install_http):
    mock = install_http(repeat_response(stream_response(sse(delta("partial")), b"data: \xff\n\n")))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "malformed_response" and len(mock.requests) == 2


@pytest.mark.parametrize("chunks", [[b'{"choices":'], [b"html provider error"], [b"data: []\n\n"]])
async def test_non_json_and_truncated_json_repair_only_once(install_http, chunks):
    mock = install_http(repeat_response(stream_response(*chunks)))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "malformed_response" and len(mock.requests) == 2


async def test_payload_after_finish_is_rejected(install_http):
    install_http(repeat_response(stream_response(sse(delta("public", finish="stop")), sse(delta(tool_calls=[{"index": 0, **call()}])), sse("[DONE]"))))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "malformed_response"


@pytest.mark.parametrize("finish", ["length", "content_filter", "tool_calls"])
async def test_conflicting_finish_cannot_downgrade_an_incomplete_response(install_http, finish):
    count = 1 if finish == "content_filter" else 2
    mock = install_http(repeat_response(stream_response(sse(delta(tool_calls=[{"index": 0, **call()}])),
        sse(delta(finish=finish)), sse(delta(finish="stop")), sse("[DONE]")), count))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == ("model_refusal" if finish == "content_filter" else "malformed_response")
    assert error.value.metadata["finish_reason"] == finish
    assert len(mock.requests) == count


async def test_whitespace_only_response_retries_once_and_resets_public_fragments(install_http):
    mock = install_http(repeat_response(stream_response(sse(delta("  \n")), sse("[DONE]"))))
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "empty_response"
    assert len(mock.requests) == 2
    assert public(events) == ["  \n", "", "  \n"]
    assert [data for event, data in events if event == "content" and data.get("reset")] == [{"content": "", "reset": True}]


async def test_empty_data_heartbeat_is_ignored(install_http):
    install_http([stream_response(b"data:\n\n: heartbeat\n\n", sse(delta("public")), b"data:  \n\n", sse("[DONE]"))])
    assert (await run())["content"] == "public"

