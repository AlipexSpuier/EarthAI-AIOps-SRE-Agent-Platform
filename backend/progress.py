from __future__ import annotations

import re
import time
from contextvars import ContextVar
from typing import Callable

from . import tools

MODEL_EVENTS: ContextVar[Callable[[str, dict], None] | None] = ContextVar("earthai_model_events", default=None)
TOOL_EVENTS = tools.TOOL_EVENTS


class RedactedText:
    def __init__(self, secrets: list[str], limit: int = 100000):
        self.secrets = [value for value in secrets if value and len(value) >= 4]
        self.limit = limit
        self.public = ""

    def render(self, text: str, final: bool = False):
        text = text[:self.limit]
        if not final:
            boundary = len(text)
            # A token may cross arbitrary provider or SSH chunks, so never release its matching prefix.
            for secret in self.secrets:
                for length in range(min(len(secret) - 1, len(text)), 0, -1):
                    if text.endswith(secret[:length]):
                        boundary = min(boundary, len(text) - length)
                        break
            text = text[:boundary]
            match = re.search(r"(?i)(?:bearer\s*|[\"']?(?:api[_-]?key|password|token|private[_-]?key)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'}]*$", text)
            if match:
                text = text[:match.start()]
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9_.+/=-]+", r"\1[REDACTED]", text)
        text = re.sub(r"(?i)([\"']?(?:api[_-]?key|password|token|private[_-]?key)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'}]+", r"\1[REDACTED]", text)
        return text

    def update(self, text: str, final: bool = False):
        safe = self.render(text, final)
        if safe == self.public:
            return None
        previous, self.public = self.public, safe
        if safe.startswith(previous):
            return {"delta": safe[len(previous):]}
        return {"delta": safe, "reset": True}


class ModelProgress:
    def __init__(self, run_id, message_id, turn, secrets):
        self.run_id, self.message_id, self.turn = run_id, message_id, turn
        self.redactor = RedactedText(secrets)
        self.raw = ""
        self.metadata = {}
        self.last_emit = 0.0

    def __call__(self, event_type, data):
        from . import store
        if event_type == "content":
            self.raw = data["content"]
            if data.get("reset"):
                self.redactor.public = ""
                store.emit(self.run_id, "assistant_delta", {"message_id": self.message_id, "turn": self.turn, "delta": "", "reset": True})
                self.last_emit = 0.0
            stamp = time.monotonic()
            if (not self.redactor.public or stamp - self.last_emit >= 0.05 or len(self.raw) - len(self.redactor.public) >= 240):
                self.flush()
        elif event_type == "metadata":
            self.metadata.update(data)
        elif event_type == "notice":
            store.emit(self.run_id, "notice", {"message_id": self.message_id, "turn": self.turn, **data})

    def flush(self, final=False):
        from . import store
        change = self.redactor.update(self.raw, final)
        if change:
            store.emit(self.run_id, "assistant_delta", {"message_id": self.message_id, "turn": self.turn, **change})
            self.last_emit = time.monotonic()
        return self.redactor.public


class ToolProgress:
    def __init__(self, run_id, tool_call_id, name, step_index, turn, secrets):
        self.run_id = run_id
        self.fields = {"tool_call_id": tool_call_id, "name": name, "step_index": step_index, "turn": turn}
        self.streams = {key: RedactedText(secrets, tools.MAX_OUTPUT) for key in ("stdout", "stderr", "progress")}
        self.raw = {key: "" for key in self.streams}
        self.last_emit = {key: 0.0 for key in self.streams}
        self.closed = False

    def __call__(self, stream, data):
        from . import store
        if self.closed or (tools.CANCELLATION.get() and tools.CANCELLATION.get().event.is_set()):
            return
        if stream == "progress":
            store.emit(self.run_id, "tool_output", {**self.fields, "stream": "progress", "content": self.streams["progress"].render(str(data["content"]), final=True)})
            return
        if stream not in self.streams:
            return
        self.raw[stream] = data["content"][:tools.MAX_OUTPUT]
        stamp = time.monotonic()
        if not self.streams[stream].public or stamp - self.last_emit[stream] >= 0.08:
            self.flush_stream(stream)

    def flush_stream(self, stream, final=False):
        from . import store
        change = self.streams[stream].update(self.raw[stream], final)
        if change:
            store.emit(self.run_id, "tool_output", {**self.fields, "stream": stream, "content": change.pop("delta"), **change})
            self.last_emit[stream] = time.monotonic()

    def finish(self):
        if self.closed:
            return
        for key in ("stdout", "stderr"):
            self.flush_stream(key, final=True)
        self.closed = True
