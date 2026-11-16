from __future__ import annotations

import asyncio
import codecs
import json
import math
import random
import re
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from . import tools

MAX_CONTENT = 100_000
MAX_ARGUMENTS = 64 * 1024
MAX_TOTAL_ARGUMENTS = 512 * 1024
MAX_CALLS = 12
MAX_FRAME = 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
MAX_WIRE = 8 * 1024 * 1024
REQUEST_TIMEOUT = 180
MAX_REQUESTS = 4
MAX_RETRY_DELAY = 20

# Options are task-local; callers must set/reset their token rather than mutate the default.
REQUEST_OPTIONS: ContextVar[dict] = ContextVar("model_request_options", default={})

_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}
_REPAIRABLE = {"invalid_tool_call", "malformed_response", "response_length"}
_FINISH_REASONS = {"stop", "length", "tool_calls", "function_call", "content_filter", "refusal"}
_RESPONSE_KEYS = {"choices", "usage", "error", "candidates", "output", "id", "object", "model", "created", "type"}
_MESSAGE_KEYS = {"role", "content", "tool_calls", "function_call", "reasoning_content", "reasoning", "thinking", "refusal"}
_TOKEN_KEYS = {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"}
_DETAIL_KEYS = {"cached_tokens", "reasoning_tokens", "audio_tokens", "text_tokens", "accepted_prediction_tokens", "rejected_prediction_tokens"}
_DETAIL_GROUPS = {"prompt_tokens_details", "completion_tokens_details", "input_tokens_details", "output_tokens_details"}
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}\Z")


class ModelResponseError(tools.ToolError):
    def __init__(self, message: str, *, code: str, metadata: dict, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.metadata = metadata
        self.retryable = retryable


class _EmptyResponse(ModelResponseError):
    def __init__(self, reason: str, metadata: dict):
        self.reason = reason
        super().__init__(
            f"模型返回空响应（原因：{reason}；finish_reason={metadata.get('finish_reason')}）。",
            code="empty_response", metadata=metadata,
        )


class _StreamUnsupported(ModelResponseError):
    pass


class _ToolChoiceUnsupported(ModelResponseError):
    pass


class _CallbackFailure(Exception):
    def __init__(self, error: Exception):
        self.error = error


def _emit(callback: Callable[[str, dict], None] | None, event: str, data: dict):
    if callback is not None:
        try:
            callback(event, data)
        except Exception as exc:
            raise _CallbackFailure(exc) from None


def _strict_json(text: str):
    def invalid_constant(_):
        raise ValueError("非 JSON 数值")
    return json.loads(text, parse_constant=invalid_constant)


def _safe_usage(value) -> dict:
    if not isinstance(value, dict):
        return {}
    result = {key: item for key, item in value.items()
        if key in _TOKEN_KEYS and type(item) is int and 0 <= item <= 10**12}
    for group in _DETAIL_GROUPS:
        detail = value.get(group)
        if isinstance(detail, dict):
            safe = {key: item for key, item in detail.items()
                if key in _DETAIL_KEYS and type(item) is int and 0 <= item <= 10**12}
            if safe:
                result[group] = safe
    return result


def _hidden_length(value) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_hidden_length(item) for item in value)
    if isinstance(value, dict):
        return sum(_hidden_length(item) for item in value.values())
    return 0


class _State:
    def __init__(self, callback, streamed: bool, request_attempt: int = 1, retry_reason: dict | None = None):
        self.callback = callback
        self.streamed = streamed
        self.request_attempt = request_attempt
        self.retry_reason = dict(retry_reason or {})
        self.retry_after = None
        self.normalizations = set()
        self.missing_index = False
        self.public_emitted = False
        self.http_status = None
        self.finish_reason = None
        self.usage = {}
        self.response_keys = set()
        self.message_keys = set()
        self.content = ""
        self.calls = {}
        self.call_mode = None
        self.argument_bytes = 0
        self.reasoning_present = False
        self.reasoning_length = 0
        self.refusal_present = False
        self.saw_choice = False
        self.done = False

    def metadata(self) -> dict:
        return {
            "http_status": self.http_status, "finish_reason": self.finish_reason,
            "streamed": self.streamed, "usage": {key: value.copy() if isinstance(value, dict) else value
                for key, value in self.usage.items()},
            "response_keys": sorted(self.response_keys), "message_keys": sorted(self.message_keys),
            "content_length": len(self.content), "tool_count": len(self.calls),
            "reasoning_present": self.reasoning_present, "reasoning_length": self.reasoning_length,
            "refusal_present": self.refusal_present, "done": self.done,
            "request_attempt": self.request_attempt, "retry_reason": self.retry_reason.copy(),
        }

    def error(self, code: str, message: str, *, retryable: bool = False) -> ModelResponseError:
        return ModelResponseError(message, code=code, metadata=self.metadata(), retryable=retryable)

    def normalize_notice(self, code: str, reason: str, message: str):
        if reason not in self.normalizations:
            self.normalizations.add(reason)
            _emit(self.callback, "notice", {"code": code, "reason": reason, "message": message,
                "attempt": self.request_attempt})

    def hidden(self, message: dict):
        for key in ("reasoning_content", "reasoning", "thinking"):
            if key in message:
                self.reasoning_present = True
                self.reasoning_length += _hidden_length(message[key])

    def append_content(self, value):
        if value is None:
            return
        if isinstance(value, str):
            text = value
        elif isinstance(value, list):
            parts = []
            for block in value:
                if not isinstance(block, dict):
                    raise self.error("malformed_response", "模型 content 内容块格式无效。")
                kind = block.get("type")
                if kind in ("text", "output_text"):
                    text = block.get("text", "")
                    if not isinstance(text, str):
                        raise self.error("malformed_response", "模型文本内容块必须包含字符串。")
                    parts.append(text)
                elif kind in ("thinking", "reasoning", "reasoning_content"):
                    self.reasoning_present = True
                    self.reasoning_length += _hidden_length({key: block[key] for key in ("text", "thinking", "reasoning", "summary")
                        if key in block})
                elif kind == "refusal":
                    self.refusal_present = True
            text = "".join(parts)
        else:
            raise self.error("malformed_response", "模型 content 必须是文本或明确标记的文本内容块。")
        if len(self.content) + len(text) > MAX_CONTENT:
            raise self.error("response_limit", "模型公开正文超过 100,000 字符安全上限。")
        if text:
            self.content += text
            if self.streamed:
                self.public_emitted = True
                _emit(self.callback, "content", {"content": self.content})

    def call_fragment(self, fragment: dict, index: int, *, legacy=False):
        if type(index) is not int or not 0 <= index < MAX_CALLS:
            raise self.error("invalid_tool_call", "工具调用 index 无效或单次调用超过 12 项。")
        mode = "legacy" if legacy else "modern"
        if self.call_mode not in (None, mode):
            raise self.error("invalid_tool_call", "模型混用了 function_call 与 tool_calls。")
        self.call_mode = mode
        call = self.calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
        if fragment.get("type", "function") != "function":
            raise self.error("invalid_tool_call", "模型返回了非 function 工具调用。")
        if not legacy and "id" in fragment:
            value = fragment["id"]
            if not isinstance(value, str):
                raise self.error("invalid_tool_call", "工具调用 ID 格式无效。")
            if value != call["id"]:
                if len(call["id"]) + len(value) > 256:
                    raise self.error("invalid_tool_call", "工具调用 ID 格式无效。")
                call["id"] += value
        function = fragment if legacy else fragment.get("function", {})
        if not isinstance(function, dict):
            raise self.error("invalid_tool_call", "工具调用 function 必须是对象。")
        for key in ("name", "arguments"):
            if key not in function:
                continue
            value = function[key]
            if key == "arguments" and isinstance(value, dict):
                try:
                    value = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                except (ValueError, TypeError, RecursionError):
                    raise self.error("invalid_tool_call", "工具参数对象不能规范化为 JSON。") from None
                self.normalize_notice("tool_arguments_normalized", "object_arguments", "供应商返回对象类型工具参数，已规范化为 JSON 字符串。")
            if not isinstance(value, str):
                raise self.error("invalid_tool_call", "工具名称和参数分片必须是字符串或明确的参数对象。")
            if key == "name":
                if value == call[key]:
                    continue
                if len(call[key]) + len(value) > 64:
                    raise self.error("invalid_tool_call", "工具名称超过 64 字符上限。")
                call[key] += value
            else:
                previous = call[key]
                merged = value if previous and value.startswith(previous) else previous + value
                size = len(merged.encode("utf-8"))
                total = self.argument_bytes - len(previous.encode("utf-8")) + size
                if size > MAX_ARGUMENTS or total > MAX_TOTAL_ARGUMENTS:
                    raise self.error("response_limit", "工具参数超过每项 64 KiB 或合计 512 KiB 安全上限。")
                self.argument_bytes = total
                call[key] = merged

    def ingest(self, body, *, stream: bool):
        if not isinstance(body, dict):
            raise self.error("malformed_response", "模型响应必须是 Chat Completions JSON 对象。")
        self.response_keys.update(_RESPONSE_KEYS.intersection(body))
        self.hidden(body)
        self.usage.update(_safe_usage(body.get("usage")))
        if "error" in body:
            raise self.error("provider_error", "模型供应商在响应中报告错误；未返回可执行工具调用。")
        if "choices" not in body and ("candidates" in body or "output" in body):
            raise self.error("incompatible_endpoint", "收到 Gemini 原生或 Responses 格式；此 URL 应提供 OpenAI chat/completions 兼容接口。")
        choices = body.get("choices")
        if choices is None:
            if not body or set(body).issubset(_RESPONSE_KEYS - {"error", "candidates", "output"}):
                if "type" in body and body["type"] not in ("ping", "heartbeat", "keep-alive"):
                    raise self.error("malformed_response", "模型响应缺少 Chat Completions choices。")
                return
            raise self.error("malformed_response", "模型响应缺少 Chat Completions choices；未解析其他协议中的工具。")
        if not isinstance(choices, list):
            raise self.error("malformed_response", "模型 choices 必须是数组。")
        if not choices:
            return
        choice = choices[0]
        if not isinstance(choice, dict) or type(choice.get("index", 0)) is not int or choice.get("index", 0) != 0:
            raise self.error("malformed_response", "模型首个 choice 格式或 index 无效。")
        message = choice.get("delta") if stream and "delta" in choice else choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if message.get("refusal") or (isinstance(content, list) and any(
                isinstance(block, dict) and block.get("type") == "refusal" for block in content
            )):
                self.refusal_present = True
        if choice.get("finish_reason") in ("content_filter", "refusal"):
            self.refusal_present = True
        if self.refusal_present:
            finish = choice.get("finish_reason")
            if finish in ("content_filter", "refusal"):
                self.finish_reason = finish
            raise self.error("model_refusal", "模型拒绝回答或触发内容过滤；未返回可执行工具调用。")
        self.saw_choice = True
        self.hidden(choice)
        finished_before = self.finish_reason is not None
        finish = choice.get("finish_reason")
        if finish is not None:
            if finish == "STOP":
                finish = "stop"
                self.normalize_notice("finish_reason_normalized", "uppercase_stop", "供应商的 STOP 结束标记已明确规范化为 stop。")
            safe_finish = finish if isinstance(finish, str) and finish in _FINISH_REASONS else "other"
            if finished_before and safe_finish != self.finish_reason:
                raise self.error("malformed_response", "模型重复发送了相互冲突的 finish_reason；未返回可执行工具调用。")
            self.finish_reason = safe_finish
            if self.finish_reason == "other":
                raise self.error("malformed_response", "模型返回了未知 finish_reason；未返回可执行工具调用。")
        message = choice.get("delta") if stream and "delta" in choice else choice.get("message")
        if message is None and stream and finish is not None:
            message = {}
        if not isinstance(message, dict):
            raise self.error("malformed_response", "模型 choice 缺少有效的 assistant message/delta 对象。")
        self.message_keys.update(_MESSAGE_KEYS.intersection(message))
        self.hidden(message)
        if message.get("role") not in (None, "assistant", ""):
            raise self.error("malformed_response", "模型返回的 message role 不是 assistant。")
        if message.get("refusal"):
            self.refusal_present = True
        if finished_before and any(message.get(key) for key in ("content", "tool_calls", "function_call")):
            raise self.error("malformed_response", "模型在 finish_reason 之后继续发送正文或工具分片。")
        self.append_content(message.get("content"))
        calls = message.get("tool_calls")
        if calls is not None:
            if not isinstance(calls, list) or len(calls) > MAX_CALLS:
                raise self.error("invalid_tool_call", "模型 tool_calls 必须是数组且最多 12 项。")
            for position, fragment in enumerate(calls):
                if not isinstance(fragment, dict):
                    raise self.error("invalid_tool_call", "工具调用分片必须是对象。")
                index = fragment.get("index") if stream and "delta" in choice else position
                if "index" not in fragment and stream and "delta" in choice:
                    if len(calls) != 1 or any(existing != 0 for existing in self.calls):
                        raise self.error("invalid_tool_call", "多个工具调用缺少唯一 index，不能推测调用归属。")
                    index = 0
                    self.missing_index = True
                if self.missing_index and (len(calls) != 1 or index != 0):
                    raise self.error("invalid_tool_call", "缺少 index 的工具调用与其他调用混合，不能推测调用归属。")
                if self.missing_index and 0 in self.calls:
                    previous = self.calls[0]
                    function = fragment.get("function")
                    if (fragment.get("id") and previous["id"] and fragment["id"] != previous["id"]) or (
                        isinstance(function, dict) and function.get("name") and previous["name"]
                        and function["name"] != previous["name"]
                    ):
                        raise self.error("invalid_tool_call", "缺少 index 的分片包含不同调用身份，不能推测为同一工具。")
                self.call_fragment(fragment, index)
        legacy = message.get("function_call")
        if legacy is not None:
            if not isinstance(legacy, dict):
                raise self.error("invalid_tool_call", "模型 function_call 必须是对象。")
            self.call_fragment(legacy, 0, legacy=True)

    def result(self) -> dict:
        if self.refusal_present or self.finish_reason in ("content_filter", "refusal"):
            raise self.error("model_refusal", "模型拒绝回答或触发内容过滤；未返回可执行工具调用。")
        if self.finish_reason == "length":
            raise self.error("response_length", "模型因输出长度限制而停止，回答或工具参数可能残缺；未返回可执行工具调用。")
        if self.streamed and not self.done and self.finish_reason is None:
            raise self.error("stream_truncated", "模型流在 [DONE] 或 finish_reason 之前结束；未返回可执行工具调用。")
        if self.finish_reason in ("tool_calls", "function_call") and not self.calls:
            raise self.error("invalid_tool_call", "模型报告工具调用结束，但没有完整工具调用。")
        calls = []
        seen_ids = set()
        if sorted(self.calls) != list(range(len(self.calls))):
            raise self.error("invalid_tool_call", "工具调用 index 不连续，可能缺少分片。")
        for index in sorted(self.calls):
            call = self.calls[index]
            if call["id"] and (call["id"] in seen_ids or any(char.isspace() or ord(char) < 32 for char in call["id"])):
                raise self.error("invalid_tool_call", "工具调用 ID 必须有效且唯一。")
            if not _NAME.fullmatch(call["name"]):
                raise self.error("invalid_tool_call", "工具名称必须是长度不超过 64 的标识符。")
            argument_text = call["arguments"]
            fenced = re.fullmatch(r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", argument_text, flags=re.DOTALL | re.IGNORECASE)
            if fenced:
                argument_text = fenced.group(1)
            try:
                arguments = _strict_json(argument_text)
                double_encoded = isinstance(arguments, str)
                if double_encoded:
                    arguments = _strict_json(arguments)
            except (ValueError, RecursionError):
                raise self.error("invalid_tool_call", "工具参数不是完整合法的 JSON 对象；未返回任何工具调用。") from None
            if not isinstance(arguments, dict):
                raise self.error("invalid_tool_call", "工具参数 JSON 必须是对象；未返回任何工具调用。")
            if fenced or double_encoded:
                argument_text = json.dumps(arguments, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                reason = "fenced_json" if fenced else "double_encoded_json"
                self.normalize_notice("tool_arguments_normalized", reason, "工具参数中的完整 JSON 对象已去除封装并规范化；未推测或执行残缺参数。")
            if call["id"]:
                seen_ids.add(call["id"])
            calls.append({"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": argument_text}})
        for call in calls:
            if not call["id"]:
                call["id"] = "call_local_" + uuid4().hex
                self.normalize_notice("tool_call_id_generated", "missing_call_id", "完整工具调用缺少 ID，已生成本地命名空间 UUID；工具尚未执行。")
        if self.missing_index:
            self.normalize_notice("tool_call_index_normalized", "single_call_missing_index", "唯一工具调用缺少 index，已在全量验证后归为 0。")
        if not self.content.strip() and not calls:
            reason = "reasoning_only" if self.reasoning_present else "empty_content" if self.saw_choice else "no_choices"
            raise _EmptyResponse(reason, self.metadata())
        result = {"role": "assistant", "content": self.content or None}
        if calls:
            result["tool_calls"] = calls
        return result


async def _lines(response: httpx.Response, state: _State):
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_WIRE:
            raise state.error("response_limit", "模型响应超过传输大小安全上限。")
        buffer += decoder.decode(chunk)
        while (match := re.search(r"[\r\n]", buffer)) is not None:
            start = match.start()
            if buffer[start] == "\r" and start + 1 == len(buffer):
                break
            end = start + (2 if buffer[start:start + 2] == "\r\n" else 1)
            if start > MAX_FRAME:
                raise state.error("response_limit", "模型单行响应超过安全上限。")
            line, buffer = buffer[:start], buffer[end:]
            yield line
        if len(buffer) > MAX_FRAME:
            raise state.error("response_limit", "模型单行响应超过安全上限。")
    buffer += decoder.decode(b"", final=True)
    if buffer.endswith("\r"):
        buffer = buffer[:-1]
        yield buffer
    elif buffer:
        yield buffer


def _sse_frame(data: list[str], event: str, state: _State):
    text = "\n".join(data)
    if text.strip() == "[DONE]":
        state.done = True
        return
    if not text.strip() or event in ("ping", "heartbeat", "keep-alive"):
        return
    try:
        body = _strict_json(text)
    except (ValueError, RecursionError):
        raise state.error("malformed_response", "模型 SSE data 不是完整合法的 JSON；未返回可执行工具调用。") from None
    state.ingest(body, stream=True)


async def _consume(response: httpx.Response, state: _State) -> dict:
    kind = None
    json_lines = []
    json_size = 0
    data = []
    frame_size = 0
    event = ""
    async for line in _lines(response, state):
        if kind is None:
            line = line.lstrip("\ufeff")
            if not line.strip():
                continue
            first = line.lstrip()
            if first.startswith(("{", "[")):
                kind = "json"
                state.streamed = False
            elif line.startswith(("data:", ":", "event:", "id:", "retry:")):
                kind = "sse"
                state.streamed = True
            else:
                raise state.error("malformed_response", "模型响应不是 Chat Completions JSON 或 SSE。")
        if kind == "json":
            json_size += len(line.encode("utf-8")) + 1
            if json_size > MAX_JSON:
                raise state.error("response_limit", "模型 JSON 响应超过安全上限。")
            json_lines.append(line)
            continue
        if not line:
            if data:
                _sse_frame(data, event, state)
                if state.done:
                    return state.result()
            data, event, frame_size = [], "", 0
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "data":
                frame_size += len(value) + 1
                if frame_size > MAX_FRAME:
                    raise state.error("response_limit", "模型 SSE 帧超过安全上限。")
                data.append(value)
            elif field == "event":
                event = value
    if kind is None:
        raise _EmptyResponse("empty_body", state.metadata())
    if kind == "json":
        try:
            body = _strict_json("\n".join(json_lines))
        except (ValueError, RecursionError):
            raise state.error("malformed_response", "模型返回了不完整或无效的 JSON。") from None
        state.ingest(body, stream=False)
    elif data:
        _sse_frame(data, event, state)
    return state.result()


def _explicit_stream_unsupported(body) -> bool:
    if not isinstance(body, dict):
        return False
    error = body.get("error")
    if isinstance(error, str):
        message, param, code = error, None, None
    elif isinstance(error, dict):
        message, param, code = error.get("message", ""), error.get("param"), error.get("code")
    else:
        return False
    if param not in (None, "stream"):
        return False
    explicit_code = param == "stream" and code in ("unsupported_parameter", "stream_unsupported", "unsupported_stream")
    if not isinstance(message, str):
        return explicit_code
    message = re.sub(r"['\"`]", "", message.lower())
    if re.search(
        r"\btools?(?:\s+calling)?\b.{0,40}\b(?:not supported|unsupported)\b"
        r"|\b(?:unsupported|does not support|do not support|cannot support|doesnt support|cant support)\b.{0,30}\btools?\b"
        r"|不支持.*工具|工具.*不支持", message,
    ):
        return False
    if explicit_code:
        return True
    patterns = (
        r"\bstream(?:ing)?(?:\s+(?:mode|parameter|option))?\s+(?:(?:is|are)\s+)?(?:not\s+supported|unsupported|not\s+available|not\s+implemented)\b",
        r"\b(?:does\s+not|do\s+not|doesnt|cannot|cant)\s+support\s+(?:the\s+)?stream(?:ing)?\b",
        r"\bunsupported\s+(?:(?:parameter|option)\s*[:=]?\s*)?stream(?:ing)?\b",
        r"不支持流式|流式(?:输出|响应|模式)?不支持",
    )
    return any(re.search(pattern, message) for pattern in patterns) or (
        param == "stream" and bool(re.search(r"\b(?:unsupported|not supported)\b", message))
    )


def _explicit_tool_choice_unsupported(body) -> bool:
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return False
    error = body["error"]
    if error.get("param") != "tool_choice":
        return False
    if error.get("code") in ("unsupported_parameter", "unknown_parameter", "unrecognized_parameter"):
        return True
    message = error.get("message")
    return isinstance(message, str) and bool(re.search(
        r"\b(?:unsupported|not supported|unknown parameter|unrecognized (?:parameter|argument))\b|不支持",
        message, flags=re.IGNORECASE,
    ))


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return min(MAX_RETRY_DELAY, max(0.0, seconds)) if math.isfinite(seconds) else None


def _retry_delay(attempt: int, retry_after: float | None = None) -> float:
    backoff = 0.5 * 2 ** (attempt - 1)
    delay = backoff + random.uniform(0, backoff * 0.25)
    return min(MAX_RETRY_DELAY, max(delay, retry_after or 0))


async def _request(client: httpx.AsyncClient, url: str, headers: dict, payload: dict, state: _State) -> dict:
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                state.http_status = response.status_code
                state.streamed = response.headers.get("content-type", "").split(";")[0].strip().lower() == "text/event-stream"
                if not response.is_success:
                    state.retry_after = _retry_after_seconds(response.headers.get("retry-after"))
                    if response.status_code in (400, 422):
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(raw) + len(chunk) > 64 * 1024:
                                break
                            raw.extend(chunk)
                        try:
                            body = _strict_json(raw.decode("utf-8"))
                        except (UnicodeError, ValueError, RecursionError):
                            body = None
                        if isinstance(body, dict):
                            state.response_keys.update(_RESPONSE_KEYS.intersection(body))
                        if payload["stream"] and _explicit_stream_unsupported(body):
                            raise _StreamUnsupported("供应商明确不支持 stream。", code="stream_unsupported", metadata=state.metadata())
                        if response.status_code == 400 and "tool_choice" in payload and _explicit_tool_choice_unsupported(body):
                            raise _ToolChoiceUnsupported("供应商明确不支持 tool_choice 参数。", code="tool_choice_unsupported", metadata=state.metadata())
                    raise state.error("http_error", f"模型供应商返回 HTTP {response.status_code}；请检查鉴权、配额及 API 配置。",
                        retryable=response.status_code in _TRANSIENT_STATUS)
                message = await _consume(response, state)
                if not state.streamed:
                    _emit(state.callback, "notice", {"code": "provider_buffered_response", "message": "供应商返回了完整 JSON 响应，未按请求逐字推送；此段回复按实际完整结果展示。"})
                    if message["content"]:
                        state.public_emitted = True
                        _emit(state.callback, "content", {"content": message["content"]})
                return message
    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout):
        raise state.error("request_timeout", "模型请求连接或读取超时；未返回可执行工具调用。", retryable=True) from None
    except httpx.TimeoutException:
        raise state.error("request_timeout", "模型请求发送超时；未返回可执行工具调用。") from None
    except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError):
        raise state.error("stream_interrupted", "模型连接或响应传输中断；未返回可执行工具调用。", retryable=True) from None
    except httpx.HTTPError:
        raise state.error("stream_interrupted", "模型连接或响应传输中断；未返回可执行工具调用。") from None
    except TimeoutError:
        raise state.error("request_timeout", "模型单次请求超过总时限；未返回可执行工具调用。", retryable=True) from None
    except (UnicodeError, RecursionError):
        raise state.error("malformed_response", "模型响应编码或嵌套结构无效；未返回可执行工具调用。") from None


def _provider_url(provider: dict) -> str:
    value = provider.get("base_url")
    try:
        parsed = urlparse(value) if isinstance(value, str) else None
        valid = parsed and parsed.scheme in ("http", "https") and parsed.hostname and not (
            parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.hostname in {"169.254.169.254", "metadata.google.internal", "100.100.100.200"}
        )
    except ValueError:
        valid = False
    if not valid:
        raise ModelResponseError("请填写有效的 HTTP(S) API Base URL，不能包含凭据、查询参数或云元数据地址。",
            code="provider_configuration", metadata={})
    return value.rstrip("/") + "/chat/completions"


async def complete(
    provider: dict, model: str, messages: list[dict], *, on_event: Callable[[str, dict], None] | None = None,
) -> dict:
    url = _provider_url(provider)
    try:
        secrets = tools.secret_values(None, provider)
    except Exception:
        raise ModelResponseError("无法解密供应商 API Key，请重新保存供应商配置。", code="provider_configuration", metadata={}) from None
    headers = {"Authorization": "Bearer " + (secrets[0] if secrets else ""), "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json"}
    options = REQUEST_OPTIONS.get()
    payload = {"model": model, "messages": list(messages), "stream": True}
    request_tools = options.get("tools", tools.TOOLS)
    if not options.get("omit_tools", False) and request_tools:
        payload.update({"tools": request_tools, "tool_choice": options.get("tool_choice", "auto")})
    retried_empty = False
    repaired = False
    fell_back = False
    removed_tool_choice = False
    retry_reasons = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), follow_redirects=False, trust_env=False) as client:
            for attempt in range(1, MAX_REQUESTS + 1):
                state = _State(on_event, payload["stream"], attempt, retry_reasons)
                try:
                    message = await _request(client, url, headers, payload, state)
                except ModelResponseError as exc:
                    _emit(on_event, "metadata", exc.metadata)
                    if attempt == MAX_REQUESTS or state.refusal_present or state.finish_reason in ("content_filter", "refusal"):
                        raise
                    delay = 0.0
                    if isinstance(exc, _StreamUnsupported) and not fell_back:
                        fell_back = True
                        payload["stream"] = False
                        code, reason = "stream_fallback", "stream_unsupported"
                        notice = "供应商明确拒绝流式参数，改用同一模型的非流式请求；工具尚未执行。"
                    elif isinstance(exc, _ToolChoiceUnsupported) and not removed_tool_choice:
                        removed_tool_choice = True
                        payload.pop("tool_choice", None)
                        code, reason = "tool_choice_fallback", "tool_choice_unsupported"
                        notice = "供应商明确拒绝 tool_choice 参数，保留工具 schema 并仅移除此参数重试。"
                    elif isinstance(exc, _EmptyResponse) and not retried_empty:
                        retried_empty = True
                        code, reason = "empty_response_retry", "empty_response"
                        notice = "模型未返回公开正文或工具调用，正在以相同模型及消息重试一次。"
                    elif exc.code in _REPAIRABLE and not repaired:
                        repaired = True
                        code, reason = "response_repair_retry", exc.code
                        instruction = ("The same request had no tool executed, return complete valid calls using schema. "
                            "Regenerate the entire response using only the provided tool names and JSON object arguments; "
                            "do not repeat previously completed actions from the conversation.")
                        if exc.code == "response_length":
                            instruction += " Shorten the output and tool arguments to fit the existing output limit."
                        payload["messages"] = [*messages, {"role": "user", "content": instruction}]
                        notice = "本次请求尚未执行任何工具；要求同一模型完整重生成合法响应，最多修复一次。"
                    elif exc.retryable or exc.code == "stream_truncated":
                        code = "request_retry"
                        reason = f"http_{state.http_status}" if exc.code == "http_error" else exc.code
                        delay = _retry_delay(attempt, state.retry_after)
                        notice = "模型请求遇到临时传输或供应商错误；本次请求尚未执行工具，将重试当前消息。"
                    else:
                        raise
                    _emit(on_event, "notice", {"code": code, "attempt": attempt + 1, "delay_ms": round(delay * 1000),
                        "reason": reason, "message": notice})
                    if state.public_emitted:
                        _emit(on_event, "content", {"content": "", "reset": True})
                    retry_reasons[reason] = retry_reasons.get(reason, 0) + 1
                    if delay:
                        await asyncio.sleep(delay)
                else:
                    _emit(on_event, "metadata", state.metadata())
                    return message
    except _CallbackFailure as exc:
        raise exc.error from None
