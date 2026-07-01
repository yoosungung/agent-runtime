"""SSE streaming bridge for Hermes AIAgent.run_conversation."""

from __future__ import annotations

import asyncio
import json
import queue
from collections.abc import AsyncIterator, Callable
from typing import Any

_DONE = object()


def _sse_payload(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _on_delta_factory(thread_q: queue.Queue[Any]) -> Callable[[str | None], None]:
    """Return stream_callback that ignores None (tool-call sentinel)."""

    def on_delta(delta: str | None) -> None:
        if delta is not None:
            thread_q.put(delta)

    return on_delta


async def stream_run_conversation(
    run_fn: Callable[[Callable[[str | None], None]], dict],
    *,
    timeout: float,
) -> AsyncIterator[str]:
    """Run *run_fn(on_delta)* in a worker thread and yield SSE chunks.

    *run_fn* must invoke ``run_conversation(..., stream_callback=on_delta)``.
    """
    thread_q: queue.Queue[Any] = queue.Queue()
    on_delta = _on_delta_factory(thread_q)
    emitted_text = False

    async def _worker() -> dict:
        def _run() -> dict:
            return run_fn(on_delta)

        return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)

    task = asyncio.create_task(_worker())

    try:
        while True:
            if task.done() and thread_q.empty():
                break
            try:
                item = await asyncio.to_thread(thread_q.get, True, 0.2)
            except queue.Empty:
                if task.done():
                    break
                continue

            if isinstance(item, str):
                emitted_text = True
                yield _sse_payload({"text": item})

        result = await task
        final = result.get("final_response") if isinstance(result, dict) else str(result)
        if not emitted_text and final:
            yield _sse_payload({"output": final})
    except TimeoutError:
        task.cancel()
        yield _sse_payload({"error": "invoke timeout"})
        return
    except Exception as exc:
        yield _sse_payload({"error": str(exc)})
        return

    yield "data: [DONE]\n\n"
