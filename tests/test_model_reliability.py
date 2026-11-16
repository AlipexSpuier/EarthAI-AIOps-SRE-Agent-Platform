import asyncio
import copy
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import pytest

import test_model_client as client_tests
from backend import model_client, tools
from test_model_client import (
    KEY, MESSAGES, PROVIDER, Pieces, call, completion, delta,
    json_response, metadata, notices, run, sse, stream_response,
)

install_http = client_tests.install_http
RETRY_DELAY = model_client._retry_delay


def payloads(mock):
    return [json.loads(request.content) for request in mock.requests]


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
async def test_transient_http_recovers_same_request_with_safe_metadata(install_http, status):
    mock = install_http([json_response({"error": KEY + " PRIVATE_REASONING"}, status=status), json_response(completion("ok"))])
    events = []
    assert (await run(events))["content"] == "ok"
    assert mock.requests[0].content == mock.requests[1].content
    retry = notices(events)[0]
    assert retry["code"] == "request_retry" and retry["attempt"] == 2
    assert retry["delay_ms"] == 0 and retry["reason"] == f"http_{status}"
    assert metadata(events)[-1]["request_attempt"] == 2
    assert metadata(events)[-1]["retry_reason"] == {f"http_{status}": 1}
    assert KEY not in json.dumps(events) and "PRIVATE_REASONING" not in json.dumps(events)


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
    httpx.ReadError, httpx.RemoteProtocolError, httpx.PoolTimeout])
async def test_transient_network_retries_same_message_without_leaking_error(install_http, failure):
    mock = install_http([failure(KEY), json_response(completion("ok"))])
    events = []
    assert (await run(events))["content"] == "ok"
    assert len(mock.requests) == 2 and mock.requests[0].content == mock.requests[1].content
    assert KEY not in json.dumps(events)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 501])
async def test_auth_validation_and_other_status_fail_without_retry(install_http, status):
    mock = install_http(lambda request: json_response({"error": KEY}, status=status))
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "http_error"
    assert len(mock.requests) == 1 and not notices(events)
    assert error.value.metadata["request_attempt"] == 1 and error.value.metadata["retry_reason"] == {}
    assert KEY not in str(error.value) + json.dumps(events)


@pytest.mark.parametrize("failure", [httpx.WriteTimeout, httpx.WriteError, httpx.LocalProtocolError])
async def test_other_network_failures_are_not_blindly_retried(install_http, failure):
    mock = install_http([failure(KEY)])
    events = []
    with pytest.raises(model_client.ModelResponseError):
        await run(events)
    assert len(mock.requests) == 1 and not notices(events)
    assert KEY not in json.dumps(events)


async def test_four_requests_total_for_repeated_transient_errors(install_http):
    mock = install_http(lambda request: json_response({"error": KEY}, status=503))
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert len(mock.requests) == 4 and len({request.content for request in mock.requests}) == 1
    assert [item["attempt"] for item in notices(events)] == [2, 3, 4]
    assert [item["request_attempt"] for item in metadata(events)] == [1, 2, 3, 4]
    assert error.value.metadata["retry_reason"] == {"http_503": 3}


async def test_mixed_recoveries_share_budget_and_do_not_replay_writes(install_http, monkeypatch):
    dispatched = []

    async def execute(*args, **kwargs):
        dispatched.append((args, kwargs))

    monkeypatch.setattr(tools, "execute", execute)
    previous = call(id="already_executed", name="ssh_exec", arguments='{"command":"touch /tmp/once","reason":"test"}')
    history = [*MESSAGES, {"role": "assistant", "content": None, "tool_calls": [previous]},
        {"role": "tool", "tool_call_id": "already_executed", "content": '{"exit_code":0}'}]
    snapshot = copy.deepcopy(history)
    mock = install_http([json_response({"error": "streaming is not supported"}, status=400), json_response(completion(None)),
        json_response(completion(None, tool_calls=[call(arguments="{")])), json_response({"error": KEY}, status=429)])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await model_client.complete(PROVIDER, "offline-model", history, on_event=lambda event, data: events.append((event, data)))
    assert len(mock.requests) == 4 and not dispatched and history == snapshot
    sent = payloads(mock)
    assert [item["stream"] for item in sent] == [True, False, False, False]
    assert [item["code"] for item in notices(events)] == ["stream_fallback", "empty_response_retry", "response_repair_retry"]
    assert all(item["messages"][:len(history)] == history for item in sent)
    assert len(sent[-1]["messages"]) == len(history) + 1
    assert "same request had no tool executed, return complete valid calls using schema" in sent[-1]["messages"][-1]["content"]
    assert error.value.metadata["request_attempt"] == 4
    assert error.value.metadata["retry_reason"] == {"stream_unsupported": 1, "empty_response": 1, "invalid_tool_call": 1}


async def test_fourth_request_can_succeed_after_mixed_recovery(install_http):
    mock = install_http([json_response({"error": KEY}, status=500),
        json_response({"error": "streaming not supported"}, status=400), json_response(completion(None)), json_response(completion("ok"))])
    events = []
    assert (await run(events))["content"] == "ok" and len(mock.requests) == 4
    assert metadata(events)[-1]["retry_reason"] == {"http_500": 1, "stream_unsupported": 1, "empty_response": 1}


@pytest.mark.parametrize("failure", [None, httpx.ReadTimeout(KEY), httpx.ReadError(KEY), httpx.RemoteProtocolError(KEY)])
async def test_post_public_interruption_resets_not_concatenates(install_http, failure):
    chunks = [sse(delta("discard this")), sse(delta(reasoning_content="HIDDEN_THOUGHT"))]
    if failure is not None:
        chunks.append(failure)
    mock = install_http([stream_response(*chunks), stream_response(sse(delta("replacement")), sse(delta(" only")), sse("[DONE]"))])
    events = []
    assert (await run(events))["content"] == "replacement only"
    assert [data for event, data in events if event == "content"] == [
        {"content": "discard this"}, {"content": "", "reset": True}, {"content": "replacement"}, {"content": "replacement only"}]
    assert len(mock.requests) == 2 and "HIDDEN_THOUGHT" not in json.dumps(events) and KEY not in json.dumps(events)


@pytest.mark.parametrize("kind", ["invalid_tool_call", "malformed_response", "response_length"])
async def test_one_repair_regenerates_full_message_without_tool_execution(install_http, monkeypatch, kind):
    dispatched = []

    async def execute(*args, **kwargs):
        dispatched.append(args)

    monkeypatch.setattr(tools, "execute", execute)
    good = call(id="first", name="ssh_exec", arguments='{"command":"echo test","reason":"offline"}')
    if kind == "invalid_tool_call":
        bad = json_response(completion(None, tool_calls=[good, call(id="bad", arguments="{")]))
    elif kind == "response_length":
        bad = json_response(completion("too long", tool_calls=[good], finish="length"))
    else:
        bad = stream_response(sse(delta("incomplete")), b"data: invalid json\n\n")
    repaired = call(id="regenerated")
    mock = install_http([bad, json_response(completion(None, tool_calls=[repaired], finish="tool_calls"))])
    events = []
    assert (await run(events))["tool_calls"] == [repaired] and not dispatched
    sent = payloads(mock)
    assert len(sent) == 2 and sent[0]["messages"] == sent[1]["messages"][:-1] == MESSAGES
    instruction = sent[1]["messages"][-1]["content"]
    assert "same request had no tool executed, return complete valid calls using schema" in instruction
    assert ("Shorten" in instruction) is (kind == "response_length")
    assert "max_tokens" not in sent[1] and "max_completion_tokens" not in sent[1]
    assert sent[0]["model"] == sent[1]["model"] == "offline-model"
    assert metadata(events)[-1]["retry_reason"] == {kind: 1}


async def test_valid_write_call_prefix_is_not_returned_before_final_validation(install_http):
    prefix_sent, release = asyncio.Event(), asyncio.Event()

    class Gated(Pieces):
        async def __aiter__(self):
            yield sse(delta(tool_calls=[{"index": 0, **call(name="ssh_exec", arguments='{"command":"touch /tmp/offline","reason":"test"}') }]))
            prefix_sent.set()
            await release.wait()
            yield sse(delta(tool_calls=[{"index": 0, "function": {"arguments": "BROKEN"}}]))
            yield sse("[DONE]")

    broken = Gated()
    mock = install_http([httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=broken), json_response(completion("safe"))])
    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(prefix_sent.wait(), 1)
        assert not task.done() and len(mock.requests) == 1
    finally:
        release.set()
    assert await task == {"role": "assistant", "content": "safe"}
    assert len(mock.requests) == 2 and broken.closed


@pytest.mark.parametrize("kind", ["invalid_tool_call", "malformed_response", "response_length"])
async def test_second_invalid_response_is_terminal_even_with_budget_remaining(install_http, kind):
    def invalid(request):
        if kind == "invalid_tool_call":
            return json_response(completion(None, tool_calls=[call(arguments="{")]))
        if kind == "response_length":
            return json_response(completion(None, tool_calls=[call()], finish="length"))
        return json_response({"choices": "INVALID"})

    mock = install_http(invalid)
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == kind and len(mock.requests) == 2
    assert [item["code"] for item in notices(events)] == ["response_repair_retry"]


@pytest.mark.parametrize("arguments,reason", [({}, "object_arguments"), ({"x": [1, "中"]}, "object_arguments"),
    ('```json\n{"x":1}\n```', "fenced_json"), ('```\n{"x":1}\n```', "fenced_json"), (json.dumps('{"x":1}'), "double_encoded_json")])
async def test_complete_json_wrappers_normalize_with_notice(install_http, arguments, reason):
    mock = install_http([json_response(completion(None, tool_calls=[call(arguments=arguments)]))])
    events = []
    normalized = (await run(events))["tool_calls"][0]["function"]["arguments"]
    assert json.loads(normalized) == (arguments if isinstance(arguments, dict) else {"x": 1})
    assert len(mock.requests) == 1
    assert any(item["code"] == "tool_arguments_normalized" and item["reason"] == reason for item in notices(events))


@pytest.mark.parametrize("arguments", ["{'x':1}", '<tool_call>{"x":1}', '```json\n{"x":1}\n',
    json.dumps(json.dumps('{"x":1}')), '```json\n{}\n``` trailing', '{"x":NaN}', '[]'])
async def test_partial_xml_python_literals_and_incomplete_wrappers_never_execute(install_http, arguments):
    mock = install_http(lambda request: json_response(completion(None, tool_calls=[call(arguments=arguments)])))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "invalid_tool_call" and len(mock.requests) == 2


async def test_repeated_identity_and_full_argument_snapshots_do_not_concatenate(install_http):
    frames = [delta(tool_calls=[{"index": 0, **call(arguments='{"x":')}]),
        delta(tool_calls=[{"index": 0, **call(arguments='{"x":1')}]),
        delta(tool_calls=[{"index": 0, **call(arguments='{"x":1}')}]),
        delta(tool_calls=[{"index": 0, **call(arguments='{"x":1}')}]), delta(finish="tool_calls")]
    mock = install_http([stream_response(*(sse(frame) for frame in frames), sse("[DONE]"))])
    assert (await run())["tool_calls"] == [call(arguments='{"x":1}')] and len(mock.requests) == 1


async def test_normal_argument_and_identity_deltas_still_append(install_http):
    mock = install_http([stream_response(sse(delta(tool_calls=[{"index": 0, **call(id="call_", name="server_", arguments='{"x":"a')} ])),
        sse(delta(tool_calls=[{"index": 0, "id": "one", "function": {"name": "info", "arguments": "a"}}])),
        sse(delta(tool_calls=[{"index": 0, "function": {"arguments": '"}'}}])), sse("[DONE]"))])
    assert (await run())["tool_calls"] == [call(id="call_one", arguments='{"x":"aa"}')] and len(mock.requests) == 1


@pytest.mark.parametrize("field,value", [("id", "call_new"), ("name", "other_tool")])
async def test_different_identity_is_not_treated_as_duplicate(install_http, field, value):
    fragment = {"index": 0, "id": value} if field == "id" else {"index": 0, "function": {"name": value}}
    install_http([stream_response(sse(delta(tool_calls=[{"index": 0, **call(arguments="{")}])),
        sse(delta(tool_calls=[fragment])), sse(delta(tool_calls=[{"index": 0, "function": {"arguments": "}"}}])), sse("[DONE]"))])
    returned = (await run())["tool_calls"][0]
    actual = returned["id"] if field == "id" else returned["function"]["name"]
    assert actual == ("call_test" if field == "id" else "server_info") + value


@pytest.mark.parametrize("streamed", [False, True])
async def test_missing_ids_get_local_uuid_only_after_validation(install_http, streamed):
    calls = [call(id="", arguments='{"n":0}'), call(id="", arguments='{"n":1}')]
    for item in calls:
        del item["id"]
    reply = (stream_response(sse(delta(tool_calls=[{"index": index, **item} for index, item in enumerate(calls)])), sse("[DONE]"))
        if streamed else json_response(completion(None, tool_calls=calls)))
    mock = install_http([reply])
    events = []
    ids = [item["id"] for item in (await run(events))["tool_calls"]]
    assert len(set(ids)) == 2 and all(re.fullmatch(r"call_local_[0-9a-f]{32}", value) for value in ids)
    assert len(mock.requests) == 1 and any(item["code"] == "tool_call_id_generated" for item in notices(events))


async def test_invalid_calls_never_generate_local_ids(install_http, monkeypatch):
    generated = []

    def uuid():
        generated.append(True)
        raise AssertionError("IDs must wait until all calls validate")

    monkeypatch.setattr(model_client, "uuid4", uuid)
    mock = install_http(lambda request: json_response(completion(None, tool_calls=[call(id=""), call(id="second", arguments="{")])))
    with pytest.raises(model_client.ModelResponseError):
        await run()
    assert len(mock.requests) == 2 and not generated


async def test_missing_index_is_only_normalized_for_unique_single_call(install_http):
    mock = install_http([stream_response(sse(delta(tool_calls=[call(arguments="{")])),
        sse(delta(tool_calls=[{"function": {"arguments": "}"}}])), sse(delta(finish="tool_calls")), sse("[DONE]"))])
    events = []
    assert (await run(events))["tool_calls"] == [call()] and len(mock.requests) == 1
    assert any(item["code"] == "tool_call_index_normalized" for item in notices(events))


@pytest.mark.parametrize("frames", [
    [delta(tool_calls=[call(id="a"), call(id="b")])],
    [delta(tool_calls=[call(id="a", arguments="{")]), delta(tool_calls=[call(id="b", arguments="}")])],
    [delta(tool_calls=[call(id="a", arguments="{")]), delta(tool_calls=[{"index": 1, **call(id="b")}])],
    [delta(tool_calls=[{"index": 1, **call(id="a")}]), delta(tool_calls=[call(id="b")])],
    [delta(tool_calls=[{"index": None, **call()}])],
])
async def test_missing_indices_never_guess_multiple_or_invalid_calls(install_http, frames):
    mock = install_http(lambda request: stream_response(*(sse(frame) for frame in frames), sse("[DONE]")))
    with pytest.raises(model_client.ModelResponseError) as error:
        await run()
    assert error.value.code == "invalid_tool_call" and len(mock.requests) == 2


async def test_context_options_send_exact_step_schema_and_required_choice(install_http):
    schema = [tools.tool("step_read", "offline", {"path": {"type": "string"}}, ["path"])]
    options = {"tools": schema, "tool_choice": "required"}
    token = model_client.REQUEST_OPTIONS.set(options)
    mock = install_http([json_response(completion(None, tool_calls=[call(name="step_read", arguments='{"path":"test"}')]))])
    try:
        assert (await run())["tool_calls"][0]["function"]["name"] == "step_read"
    finally:
        model_client.REQUEST_OPTIONS.reset(token)
    sent = payloads(mock)[0]
    assert sent["tools"] == schema and sent["tool_choice"] == "required" and "parallel_tool_calls" not in sent
    assert options == {"tools": schema, "tool_choice": "required"}


async def test_request_options_are_task_local_and_defaults_unchanged(install_http):
    mock = install_http(lambda request: json_response(completion("ok")))
    schemas = [[tools.tool("read_one", "one", {})], [tools.tool("read_two", "two", {})]]

    async def configured(schema):
        token = model_client.REQUEST_OPTIONS.set({"tools": schema, "tool_choice": "required"})
        try:
            await asyncio.sleep(0)
            await run()
        finally:
            model_client.REQUEST_OPTIONS.reset(token)

    await asyncio.gather(*(configured(schema) for schema in schemas))
    await run()
    sent = payloads(mock)
    assert {item["tools"][0]["function"]["name"] for item in sent[:2]} == {"read_one", "read_two"}
    assert sent[-1]["tools"] == tools.TOOLS and sent[-1]["tool_choice"] == "auto"
    assert model_client.REQUEST_OPTIONS.get() == {}


async def test_named_choice_and_nonempty_schema_are_forwarded(install_http):
    choice = {"type": "function", "function": {"name": "server_info"}}
    schema = [tools.tool("server_info", "read only", {})]
    token = model_client.REQUEST_OPTIONS.set({"tools": schema, "tool_choice": choice})
    mock = install_http([json_response(completion("ok"))])
    try:
        await run()
    finally:
        model_client.REQUEST_OPTIONS.reset(token)
    assert payloads(mock)[0]["tools"] == schema and payloads(mock)[0]["tool_choice"] == choice


@pytest.mark.parametrize("provider_error", [{"param": "tool_choice", "code": "unsupported_parameter"},
    {"param": "tool_choice", "message": "tool_choice is not supported"}])
async def test_explicit_400_tool_choice_fallback_keeps_tools(install_http, provider_error):
    schema = [tools.tool("server_info", "read only", {})]
    options = {"tools": schema, "tool_choice": "required"}
    token = model_client.REQUEST_OPTIONS.set(options)
    mock = install_http([json_response({"error": provider_error}, status=400), json_response(completion(None, tool_calls=[call()]))])
    events = []
    try:
        assert (await run(events))["tool_calls"] == [call()]
    finally:
        model_client.REQUEST_OPTIONS.reset(token)
    sent = payloads(mock)
    assert sent[0]["tools"] == sent[1]["tools"] == schema
    assert sent[0]["tool_choice"] == "required" and "tool_choice" not in sent[1]
    assert sent[0]["stream"] is sent[1]["stream"] is True
    assert [item["code"] for item in notices(events)] == ["tool_choice_fallback", "provider_buffered_response"]
    assert metadata(events)[-1]["retry_reason"] == {"tool_choice_unsupported": 1}
    assert options == {"tools": schema, "tool_choice": "required"}


@pytest.mark.parametrize("status,provider_error", [
    (422, {"param": "tool_choice", "code": "unsupported_parameter"}),
    (401, {"param": "tool_choice", "code": "unsupported_parameter"}),
    (400, {"message": "tool_choice not supported"}),
    (400, {"param": "tool_choice", "message": "invalid choice value"}),
    (400, {"param": "tools", "message": "tools are not supported"}),
    (400, {"param": "tools", "message": "tools and streaming are not supported"}),
    (400, {"message": "Streaming is not supported; this model does not support tools"}),
    (400, {"param": "stream", "code": "unsupported_parameter", "message": "This model does not support tools"}),
])
async def test_unsupported_tools_or_ambiguous_parameter_never_retry(install_http, status, provider_error):
    mock = install_http(lambda request: json_response({"error": provider_error}, status=status))
    events = []
    with pytest.raises(model_client.ModelResponseError):
        await run(events)
    assert len(mock.requests) == 1 and not notices(events)


async def test_tool_choice_fallback_cannot_repeat(install_http):
    mock = install_http(lambda request: json_response({"error": {"param": "tool_choice", "code": "unsupported_parameter"}}, status=400))
    events = []
    with pytest.raises(model_client.ModelResponseError):
        await run(events)
    assert len(mock.requests) == 2 and len(notices(events)) == 1


async def test_required_choice_does_not_fabricate_calls(install_http):
    token = model_client.REQUEST_OPTIONS.set({"tool_choice": "required"})
    mock = install_http([json_response(completion("no tools selected"))])
    try:
        assert await run() == {"role": "assistant", "content": "no tools selected"}
    finally:
        model_client.REQUEST_OPTIONS.reset(token)
    assert len(mock.requests) == 1


async def test_unknown_tool_name_is_not_guessed_or_repaired(install_http):
    unknown = call(name="not_authorized_tool")
    mock = install_http([json_response(completion(None, tool_calls=[unknown]))])
    assert (await run())["tool_calls"] == [unknown] and len(mock.requests) == 1


async def test_uppercase_stop_is_explicitly_normalized(install_http):
    mock = install_http([json_response(completion("valid", finish="STOP"))])
    events = []
    assert (await run(events))["content"] == "valid" and len(mock.requests) == 1
    assert metadata(events)[-1]["finish_reason"] == "stop"
    assert any(item["code"] == "finish_reason_normalized" for item in notices(events))


@pytest.mark.parametrize("finish", ["FINISH_REASON_UNSPECIFIED", "UNKNOWN", "secret_status", True, "completed"])
async def test_unknown_finish_never_releases_valid_calls(install_http, finish):
    mock = install_http(lambda request: json_response(completion(None, tool_calls=[call()], finish=finish)))
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "malformed_response" and len(mock.requests) == 2
    assert metadata(events)[-1]["finish_reason"] == "other" and "secret_status" not in json.dumps(events)


@pytest.mark.parametrize("value,expected", [("7", 7), ("99", 20), ("-3", 0), ("1.5", 1.5),
    ("NaN", None), ("Infinity", None), ("not a date", None), ("", None), (None, None)])
def test_retry_after_seconds_are_safe_and_capped(value, expected):
    assert model_client._retry_after_seconds(value) == expected


def test_retry_after_dates_are_parsed_capped_and_past_dates_zero():
    now = datetime.now(timezone.utc)
    parsed = model_client._retry_after_seconds(format_datetime(now + timedelta(seconds=8), usegmt=True))
    assert 6 <= parsed <= 8
    assert model_client._retry_after_seconds(format_datetime(now + timedelta(days=1), usegmt=True)) == 20
    assert model_client._retry_after_seconds(format_datetime(now - timedelta(days=1), usegmt=True)) == 0


def test_exponential_backoff_jitter_and_retry_after_cap(monkeypatch):
    seen = []

    def jitter(low, high):
        seen.append((low, high))
        return high

    monkeypatch.setattr(model_client.random, "uniform", jitter)
    assert [RETRY_DELAY(attempt) for attempt in range(1, 4)] == [0.625, 1.25, 2.5]
    assert seen == [(0, 0.125), (0, 0.25), (0, 0.5)]
    assert RETRY_DELAY(1, 10) == 10 and RETRY_DELAY(3, 999) == RETRY_DELAY(10) == 20


async def test_retry_after_reaches_notice_without_real_sleep(install_http, monkeypatch):
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(model_client, "asyncio", SimpleNamespace(timeout=asyncio.timeout, sleep=sleep))
    unavailable = json_response({"error": KEY}, status=429)
    unavailable.headers["retry-after"] = "999"
    mock = install_http([unavailable, json_response(completion("ok"))])
    monkeypatch.setattr(model_client, "_retry_delay", RETRY_DELAY)
    events = []
    await run(events)
    assert sleeps == [20] and notices(events)[0]["delay_ms"] == 20_000
    assert len(mock.requests) == 2 and KEY not in json.dumps(events)


@pytest.mark.parametrize("event_to_fail", ["notice", "metadata", "reset"])
async def test_retry_callback_errors_never_send_another_request(install_http, event_to_fail):
    mock = install_http([stream_response(sse(delta("already visible")), httpx.ReadError(KEY)), json_response(completion("must not request"))])
    failure = httpx.ReadTimeout("callback sentinel")

    def callback(event, data):
        if event == event_to_fail or (event_to_fail == "reset" and event == "content" and data.get("reset")):
            raise failure

    with pytest.raises(httpx.ReadTimeout) as error:
        await model_client.complete(PROVIDER, "offline-model", MESSAGES, on_event=callback)
    assert error.value is failure and len(mock.requests) == 1


async def test_cancellation_during_backoff_is_not_swallowed(install_http, monkeypatch):
    waiting = asyncio.Event()

    async def sleep(seconds):
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(model_client, "asyncio", SimpleNamespace(timeout=asyncio.timeout, sleep=sleep))
    mock = install_http([json_response({"error": KEY}, status=503), json_response(completion("must not request"))])
    monkeypatch.setattr(model_client, "_retry_delay", lambda *args: 1)
    task = asyncio.create_task(run())
    await asyncio.wait_for(waiting.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(mock.requests) == 1


@pytest.mark.parametrize("body", [
    completion("PRIVATE_TEXT", finish="secret_unknown", refusal="PRIVATE_REFUSAL", tool_calls=[call(arguments="{")]),
    completion("PRIVATE_TEXT", finish="content_filter", tool_calls="invalid"),
    completion([{"type": "text", "text": 9}, {"type": "refusal", "refusal": "PRIVATE_REFUSAL"}], tool_calls=[call(arguments="{")]),
])
async def test_refusal_takes_priority_over_malformed_content_and_never_repairs(install_http, body):
    mock = install_http([json_response(body)])
    events = []
    with pytest.raises(model_client.ModelResponseError) as error:
        await run(events)
    assert error.value.code == "model_refusal" and error.value.metadata["refusal_present"] is True
    assert len(mock.requests) == 1 and not notices(events)
    assert not [item for event, item in events if event == "content"]
    assert "PRIVATE" not in json.dumps(events) + str(error.value)


async def test_all_parameter_fallbacks_share_total_request_budget(install_http):
    mock = install_http([json_response({"error": "stream is not supported"}, status=400),
        json_response({"error": {"param": "tool_choice", "code": "unsupported_parameter"}}, status=400),
        json_response(completion(None)), json_response(completion("ok"))])
    events = []
    assert (await run(events))["content"] == "ok" and len(mock.requests) == 4
    sent = payloads(mock)
    assert [item["stream"] for item in sent] == [True, False, False, False]
    assert ["tool_choice" in item for item in sent] == [True, True, False, False]
    assert all(item["tools"] == tools.TOOLS for item in sent)
    assert metadata(events)[-1]["retry_reason"] == {"stream_unsupported": 1, "tool_choice_unsupported": 1, "empty_response": 1}


async def test_transient_retry_after_repair_keeps_repair_instruction_and_schema(install_http):
    schema = [tools.tool("step_read", "offline", {})]
    token = model_client.REQUEST_OPTIONS.set({"tools": schema, "tool_choice": "required"})
    mock = install_http([json_response(completion(None, tool_calls=[call(arguments="{")])),
        json_response({"error": KEY}, status=503), json_response(completion(None, tool_calls=[call(name="step_read")]))])
    events = []
    try:
        assert (await run(events))["tool_calls"] == [call(name="step_read")]
    finally:
        model_client.REQUEST_OPTIONS.reset(token)
    sent = payloads(mock)
    assert sent[1] == sent[2] and all(item["tools"] == schema and item["tool_choice"] == "required" for item in sent)
    assert metadata(events)[-1]["retry_reason"] == {"invalid_tool_call": 1, "http_503": 1}


@pytest.mark.parametrize("options", [
    {"omit_tools": True},
    {"omit_tools": True, "tools": tools.TOOLS, "tool_choice": "required"},
    {"tools": []},
    {"tools": [], "tool_choice": "required"},
    {"omit_tools": False, "tools": [], "tool_choice": "auto"},
])
async def test_omit_tools_or_empty_schema_omits_native_fields_and_keeps_text(install_http, options):
    snapshot = copy.deepcopy(options)
    messages = [*copy.deepcopy(MESSAGES), {"role": "system", "content": "Return only a complete JSON control object."}]
    original_messages = copy.deepcopy(messages)
    text = '{"tool_calls":[{"name":"server_info","arguments":{}}]}'
    token = model_client.REQUEST_OPTIONS.set(options)
    mock = install_http([json_response(completion(text))])
    events = []
    try:
        result = await model_client.complete(PROVIDER, "offline-model", messages,
            on_event=lambda event, data: events.append((event, data)))
    finally:
        model_client.REQUEST_OPTIONS.reset(token)
    assert result == {"role": "assistant", "content": text}
    assert payloads(mock) == [{"model": "offline-model", "messages": original_messages, "stream": True}]
    assert messages == original_messages and options == snapshot
    assert not any(item["code"] == "tool_choice_fallback" for item in notices(events))


@pytest.mark.parametrize("options", [{"omit_tools": True, "tool_choice": "required"}, {"tools": [], "tool_choice": "required"}])
async def test_omitted_tool_choice_never_attempts_unsupported_choice_fallback(install_http, options):
    token = model_client.REQUEST_OPTIONS.set(options)
    mock = install_http([json_response({"error": {"param": "tool_choice", "code": "unsupported_parameter"}}, status=400)])
    events = []
    try:
        with pytest.raises(model_client.ModelResponseError) as error:
            await run(events)
    finally:
        model_client.REQUEST_OPTIONS.reset(token)
    assert error.value.code == "http_error" and len(mock.requests) == 1 and not notices(events)
    assert "tools" not in payloads(mock)[0] and "tool_choice" not in payloads(mock)[0]


async def test_omitted_tools_survive_recovery_without_mutating_messages(install_http, monkeypatch):
    messages = copy.deepcopy(MESSAGES)
    messages.insert(0, {"role": "system", "content": "Return complete valid JSON, never execute prose."})
    snapshot = copy.deepcopy(messages)
    options = {"omit_tools": True, "tools": tools.TOOLS, "tool_choice": "required"}
    token = model_client.REQUEST_OPTIONS.set(options)
    mock = install_http([json_response({"choices": "invalid"}), json_response({"error": KEY}, status=503),
        json_response(completion('{"status":"done"}'))])
    original_request = model_client._request
    copied = []

    async def request(client, url, headers, payload, state):
        copied.append(payload["messages"] is not messages)
        return await original_request(client, url, headers, payload, state)

    monkeypatch.setattr(model_client, "_request", request)
    events = []
    try:
        result = await model_client.complete(PROVIDER, "offline-model", messages,
            on_event=lambda event, data: events.append((event, data)))
    finally:
        model_client.REQUEST_OPTIONS.reset(token)
    assert result == {"role": "assistant", "content": '{"status":"done"}'}
    sent = payloads(mock)
    assert len(sent) == 3 and all(copied)
    assert all("tools" not in item and "tool_choice" not in item for item in sent)
    assert sent[0]["messages"] == snapshot and sent[1] == sent[2]
    assert sent[1]["messages"][:-1] == snapshot and len(sent[1]["messages"]) == len(snapshot) + 1
    assert messages == snapshot and options == {"omit_tools": True, "tools": tools.TOOLS, "tool_choice": "required"}
    assert not any(item["code"] == "tool_choice_fallback" for item in notices(events))
