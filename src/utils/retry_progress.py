from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

try:
    from langgraph.config import get_stream_writer
except ImportError:  # pragma: no cover - LangGraph is a runtime dependency
    get_stream_writer = None

CUSTOM_RETRY_PROGRESS = "retry-progress"
_RETRY_PROGRESS_SINK: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "retry_progress_sink",
    default=None,
)
_OPERATION_DONE = object()


def build_retry_event(
    *,
    event_id: str,
    retry_id: str | None,
    retry_count: int | None = None,
    max_retries: int | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "model-retry",
        "id": event_id,
        "retryId": retry_id,
    }
    if retry_count is not None and max_retries is not None:
        event.update(
            {
                "retryCount": retry_count,
                "maxRetries": max_retries,
            }
        )
    return event


@dataclass(frozen=True)
class RetryProgressReporter:
    operation_id: str = field(default_factory=lambda: uuid4().hex)

    def emit(self, retry_count: int, max_retries: int) -> bool:
        event = {
            "type": CUSTOM_RETRY_PROGRESS,
            "operationId": self.operation_id,
            "retryCount": retry_count,
            "maxRetries": max_retries,
        }
        if get_stream_writer is not None:
            try:
                writer = get_stream_writer()
                if callable(writer):
                    writer(event)
                    return True
            except Exception:
                pass
        sink = _RETRY_PROGRESS_SINK.get()
        if sink is None:
            return False
        try:
            sink(event)
        except Exception:
            return False
        return True


@dataclass(frozen=True)
class RetryProgressResult[T]:
    value: T


async def iter_with_retry_progress[T](
    operation: Awaitable[T],
) -> AsyncIterator[dict[str, Any] | RetryProgressResult[T]]:
    queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()
    token = _RETRY_PROGRESS_SINK.set(queue.put_nowait)
    try:
        task = asyncio.create_task(operation)
    finally:
        _RETRY_PROGRESS_SINK.reset(token)
    task.add_done_callback(lambda _task: queue.put_nowait(_OPERATION_DONE))

    try:
        while True:
            event = await queue.get()
            if event is _OPERATION_DONE:
                break
            if isinstance(event, dict):
                yield event
        yield RetryProgressResult(await task)
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


__all__ = [
    "CUSTOM_RETRY_PROGRESS",
    "RetryProgressReporter",
    "RetryProgressResult",
    "build_retry_event",
    "iter_with_retry_progress",
]
