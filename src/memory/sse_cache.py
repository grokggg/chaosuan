from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from src.utils.config import load_agent_config

SSE_CACHE_IDLE_TTL_SECONDS = 60 * 60
SSE_CACHE_CLEANUP_INTERVAL_SECONDS = 1800
SSE_CACHE_MODE_CONFIG_KEY = "sseCacheMode"
SSE_CACHE_MODE_BLOCK = "block"
SSE_CACHE_MODE_EVENT = "event"
logger = logging.getLogger(__name__)


def _resolve_sse_cache_mode() -> str:
    try:
        config = load_agent_config()
    except Exception:
        logger.exception("Failed to load agent config for SSE cache mode, fallback to %s", SSE_CACHE_MODE_BLOCK)
        return SSE_CACHE_MODE_BLOCK

    mode = str(config.get(SSE_CACHE_MODE_CONFIG_KEY) or SSE_CACHE_MODE_BLOCK).strip().lower()
    if mode in {SSE_CACHE_MODE_BLOCK, SSE_CACHE_MODE_EVENT}:
        return mode
    logger.warning(
        "Invalid agent.json field %s=%s, fallback to %s",
        SSE_CACHE_MODE_CONFIG_KEY,
        mode,
        SSE_CACHE_MODE_BLOCK,
    )
    return SSE_CACHE_MODE_BLOCK


@dataclass
class SseCacheBlock:
    type: str
    events: list[str] = field(default_factory=list)
    closed: bool = False


@dataclass
class SseCacheEntry:
    conversation_id: str
    message_id: str | None = None
    mode: str = field(default_factory=_resolve_sse_cache_mode)
    events: list[str] = field(default_factory=list)
    blocks: list[SseCacheBlock] = field(default_factory=list)
    active_blocks: dict[tuple[str, str], int] = field(default_factory=dict)
    closed: bool = False
    last_accessed: float = field(default_factory=time.monotonic)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)


_SSE_CACHES: dict[str, SseCacheEntry] = {}
_cleanup_task: asyncio.Task[None] | None = None


def _touch(entry: SseCacheEntry) -> None:
    entry.last_accessed = time.monotonic()


def _is_expired(entry: SseCacheEntry, now: float) -> bool:
    return now - entry.last_accessed >= SSE_CACHE_IDLE_TTL_SECONDS


async def _close_entry(entry: SseCacheEntry) -> None:
    async with entry.condition:
        entry.closed = True
        for block in entry.blocks:
            block.closed = True
        entry.active_blocks.clear()
        entry.condition.notify_all()


async def _cleanup_expired_once() -> None:
    now = time.monotonic()
    expired_entries = [
        (conversation_id, entry)
        for conversation_id, entry in list(_SSE_CACHES.items())
        if _is_expired(entry, now)
    ]
    for conversation_id, entry in expired_entries:
        await _close_entry(entry)
        if _SSE_CACHES.get(conversation_id) is entry:
            _SSE_CACHES.pop(conversation_id, None)
            logger.info("Expired idle SSE cache conversation_id=%s", conversation_id)


async def _cleanup_expired_loop() -> None:
    while True:
        await asyncio.sleep(SSE_CACHE_CLEANUP_INTERVAL_SECONDS)
        try:
            await _cleanup_expired_once()
        except Exception:
            logger.exception("Failed to cleanup expired SSE cache")


def _ensure_cleanup_task() -> None:
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_cleanup_expired_loop())


def _payload_from_sse(event: str) -> str | None:
    for line in event.splitlines():
        if line.startswith("data:"):
            return line[len("data:") :].strip()
    return None


def _event_payload(event: str) -> dict[str, object] | str | None:
    payload = _payload_from_sse(event)
    if payload is None:
        return None
    if payload == "[DONE]":
        return payload
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _event_identity(event: str) -> tuple[str, str, str]:
    payload = _event_payload(event)
    if payload == "[DONE]":
        return "done", "", "done"
    if not isinstance(payload, dict):
        return "sse", "", "single"

    event_type = str(payload.get("type") or "sse")
    if event_type in {"text-start", "text-delta", "text-end"}:
        return "text", str(payload.get("id") or ""), event_type.rsplit("-", 1)[-1]
    if event_type in {"reasoning-start", "reasoning-delta", "reasoning-end"}:
        return "reasoning", str(payload.get("id") or ""), event_type.rsplit("-", 1)[-1]
    if event_type in {"tool-input-start", "tool-input-delta", "tool-input-available"}:
        action = "end" if event_type == "tool-input-available" else event_type.rsplit("-", 1)[-1]
        return "tool-input", str(payload.get("toolCallId") or ""), action
    if event_type == "finish":
        return "finish", "", "start"
    return event_type, "", "single"


async def begin_sse_cache(conversation_id: str, *, message_id: str | None = None) -> None:
    _ensure_cleanup_task()
    old_entry = _SSE_CACHES.get(conversation_id)
    if old_entry is not None:
        await _close_entry(old_entry)
    _SSE_CACHES[conversation_id] = SseCacheEntry(
        conversation_id=conversation_id,
        message_id=message_id,
    )


def has_sse_cache(conversation_id: str) -> bool:
    return conversation_id in _SSE_CACHES


def get_sse_cache_message_id(conversation_id: str) -> str | None:
    entry = _SSE_CACHES.get(conversation_id)
    return entry.message_id if entry is not None else None


def is_sse_cache_active(conversation_id: str) -> bool:
    entry = _SSE_CACHES.get(conversation_id)
    return entry is not None and not entry.closed


async def append_sse_cache_event(conversation_id: str, event: str) -> None:
    _ensure_cleanup_task()
    entry = _SSE_CACHES.get(conversation_id)
    if entry is None:
        return

    async with entry.condition:
        _touch(entry)
        if entry.mode == SSE_CACHE_MODE_EVENT:
            entry.events.append(event)
            if _event_payload(event) == "[DONE]":
                entry.closed = True
            entry.condition.notify_all()
            return

        block_type, block_id, action = _event_identity(event)
        if block_type == "done":
            finish_key = ("finish", "")
            finish_index = entry.active_blocks.pop(finish_key, None)
            if finish_index is None:
                entry.blocks.append(SseCacheBlock(type="done", events=[event], closed=True))
            else:
                block = entry.blocks[finish_index]
                block.events.append(event)
                block.closed = True
            entry.closed = True
            entry.condition.notify_all()
            return

        if action == "single":
            entry.blocks.append(SseCacheBlock(type=block_type, events=[event], closed=True))
            entry.condition.notify_all()
            return

        key = (block_type, block_id)
        block_index = entry.active_blocks.get(key)
        if block_index is None:
            block = SseCacheBlock(type=block_type, events=[event], closed=False)
            entry.blocks.append(block)
            block_index = len(entry.blocks) - 1
            entry.active_blocks[key] = block_index
        else:
            block = entry.blocks[block_index]
            block.events.append(event)

        if action == "end":
            block.closed = True
            entry.active_blocks.pop(key, None)

        entry.condition.notify_all()


async def close_sse_cache(conversation_id: str) -> None:
    entry = _SSE_CACHES.get(conversation_id)
    if entry is None:
        return
    _touch(entry)
    await _close_entry(entry)


async def stream_sse_cache(conversation_id: str) -> AsyncIterator[str]:
    _ensure_cleanup_task()
    entry = _SSE_CACHES.get(conversation_id)
    if entry is None:
        return

    if entry.mode == SSE_CACHE_MODE_EVENT:
        event_index = 0
        while True:
            async with entry.condition:
                _touch(entry)
                while True:
                    if event_index < len(entry.events):
                        event = entry.events[event_index]
                        event_index += 1
                        break
                    if entry.closed:
                        return
                    await entry.condition.wait()
                    _touch(entry)
            yield event
        return

    block_index = 0
    event_index = 0
    while True:
        async with entry.condition:
            _touch(entry)
            while True:
                if block_index < len(entry.blocks):
                    block = entry.blocks[block_index]
                    if event_index < len(block.events):
                        event = block.events[event_index]
                        event_index += 1
                        if event_index >= len(block.events) and block.closed:
                            block_index += 1
                            event_index = 0
                        break
                    if block.closed:
                        block_index += 1
                        event_index = 0
                        continue
                elif entry.closed:
                    return
                await entry.condition.wait()
                _touch(entry)
        yield event


__all__ = [
    "append_sse_cache_event",
    "begin_sse_cache",
    "close_sse_cache",
    "get_sse_cache_message_id",
    "has_sse_cache",
    "is_sse_cache_active",
    "stream_sse_cache",
]
