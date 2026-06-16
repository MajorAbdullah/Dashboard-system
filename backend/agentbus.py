"""Per-job step bus feeding the SSE stream of live agent reasoning.

A job_id is created by the frontend; it opens an EventSource on /api/agent/stream
with that id, then POSTs /api/generate with the same id. The pipeline publishes
steps here; the SSE endpoint drains them. A poll fallback reads the same buffer.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

_queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
_history: dict[str, list[dict]] = defaultdict(list)
_done: dict[str, bool] = defaultdict(bool)


async def publish(job_id: str | None, text: str, status: str = "run") -> None:
    if not job_id:
        return
    evt = {"t": text, "status": status}
    _history[job_id].append(evt)
    await _queues[job_id].put(evt)


async def finish(job_id: str | None, count: int = 0) -> None:
    if not job_id:
        return
    _done[job_id] = True
    await _queues[job_id].put({"event": "done", "count": count})


def make_emit(job_id: str | None):
    """Return an async emit(text, status='run') bound to this job."""
    async def emit(text: str, status: str = "run") -> None:
        await publish(job_id, text, status)
    return emit


async def stream(job_id: str):
    """Async generator of SSE-ready dicts for sse_starlette EventSourceResponse."""
    q = _queues[job_id]
    # replay anything already buffered (race: POST may have started first)
    for evt in list(_history[job_id]):
        yield _format(evt)
    while True:
        evt = await asyncio.wait_for(q.get(), timeout=120)
        yield _format(evt)
        if evt.get("event") == "done":
            break
    _cleanup(job_id)


def _format(evt: dict) -> dict:
    if evt.get("event") == "done":
        return {"event": "done", "data": str(evt.get("count", 0))}
    import json
    return {"event": "step", "data": json.dumps(evt)}


def poll(job_id: str, since: int) -> dict:
    steps = _history.get(job_id, [])
    return {"steps": steps[since:], "next": len(steps), "done": _done.get(job_id, False)}


def _cleanup(job_id: str) -> None:
    _queues.pop(job_id, None)
    _history.pop(job_id, None)
    _done.pop(job_id, None)
