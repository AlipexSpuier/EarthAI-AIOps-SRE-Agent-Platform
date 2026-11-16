from __future__ import annotations

import asyncio
import threading
_WAITERS = {}
_LOCK = threading.Lock()


def listen(run_id):
    loop = asyncio.get_running_loop()
    event = asyncio.Event()
    with _LOCK:
        _WAITERS.setdefault(run_id, set()).add((loop, event))
    return loop, event


def unlisten(run_id, listener):
    with _LOCK:
        items = _WAITERS.get(run_id)
        if items is not None:
            items.discard(listener)
            if not items:
                _WAITERS.pop(run_id, None)


def notify(run_id):
    with _LOCK:
        listeners = tuple(_WAITERS.get(run_id, ()))
    for loop, event in listeners:
        if not loop.is_closed():
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                if not loop.is_closed():
                    raise
