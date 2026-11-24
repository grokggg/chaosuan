from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress

from src.api.routes.utils.chat_stream import sse_message

SSE_HEARTBEAT_IDLE_SECONDS = 30.0


def _heartbeat_event(conversation_id: str, message_id: str | None = None) -> str:
    payload = {
        "type": "heartbeat",
        "conversationId": conversation_id,
    }
    if message_id:
        payload["messageId"] = message_id
    return sse_message(json.dumps(payload, ensure_ascii=False))


async def stream_with_heartbeat(
    source: AsyncIterable[str],
    conversation_id: str,
    *,
    idle_seconds: float = SSE_HEARTBEAT_IDLE_SECONDS,
    message_id: str | None = None,
) -> AsyncIterator[str]:
    if idle_seconds <= 0:
        raise ValueError("idle_seconds must be greater than zero")

    queue: asyncio.Queue[tuple[str, str | BaseException | None]] = asyncio.Queue(maxsize=1)
    consumer_closed = asyncio.Event()

    async def produce() -> None:
        iterator = aiter(source)
        outcome: tuple[str, str | BaseException | None] = ("end", None)
        try:
            async for event in iterator:
                await queue.put(("event", event))
        except asyncio.CancelledError:
            outcome = ("cancelled", None)
        except BaseException as exc:
            outcome = ("error", exc)
        finally:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                with suppress(Exception):
                    await close()

        if not consumer_closed.is_set():
            await queue.put(outcome)

    producer = asyncio.create_task(
        produce(),
        name=f"sse-source-producer-{conversation_id}",
    )
    producer_cancel_source = "sse_consumer_closed"
    try:
        while True:
            try:
                async with asyncio.timeout(idle_seconds):
                    event_kind, payload = await queue.get()
            except TimeoutError:
                yield _heartbeat_event(conversation_id, message_id)
                continue

            if event_kind == "event":
                if not isinstance(payload, str):
                    raise TypeError("SSE stream event payload must be a string")
                yield payload
                continue

            if event_kind in {"end", "cancelled"}:
                return

            if event_kind == "error":
                if isinstance(payload, BaseException):
                    raise payload
                raise RuntimeError(str(payload))

            raise RuntimeError(f"Unknown SSE stream event kind: {event_kind}")
    except asyncio.CancelledError:
        producer_cancel_source = "sse_response_task_cancelled"
        raise
    finally:
        consumer_closed.set()
        if not producer.done():
            producer.cancel(producer_cancel_source)
        with suppress(asyncio.CancelledError):
            await producer


__all__ = [
    "SSE_HEARTBEAT_IDLE_SECONDS",
    "stream_with_heartbeat",
]
