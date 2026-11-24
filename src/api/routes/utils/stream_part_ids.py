from __future__ import annotations

import asyncio

from src.api.session_store import read_session
from src.utils.todolists import agent_namespace

_STREAM_PART_COUNTERS: dict[str, dict[str, int]] = {}
_STREAM_PART_COUNTER_LOCK = asyncio.Lock()


async def next_stream_part_id(
    user_id: str,
    conversation_id: str,
    part_type: str,
) -> str:
    key = f"{user_id}:{conversation_id}"
    counters = _STREAM_PART_COUNTERS.get(key, {})
    if part_type in counters:
        async with _STREAM_PART_COUNTER_LOCK:
            current_index = _STREAM_PART_COUNTERS.get(key, {}).get(part_type, 0)
            next_index = current_index + 1
            _STREAM_PART_COUNTERS.setdefault(key, {})[part_type] = next_index
    else:
        # First call for this part_type: read session history outside the lock
        # to avoid blocking other conversations during file I/O.
        initial = max_session_part_index(user_id, conversation_id, part_type)
        async with _STREAM_PART_COUNTER_LOCK:
            counters = _STREAM_PART_COUNTERS.setdefault(key, {})
            if part_type in counters:
                current_index = counters[part_type]
            else:
                current_index = initial
        next_index = current_index + 1
        counters[part_type] = next_index
    part_id = f"{part_type}_{next_index}"
    namespace = agent_namespace()
    return f"{part_id}_{namespace}" if namespace else part_id


async def clear_stream_part_ids(user_id: str, conversation_id: str) -> None:
    key = f"{user_id}:{conversation_id}"
    async with _STREAM_PART_COUNTER_LOCK:
        _STREAM_PART_COUNTERS.pop(key, None)


def max_session_part_index(user_id: str, conversation_id: str, part_type: str) -> int:
    session = read_session(user_id, conversation_id)
    messages = session.get("messages") if session else None
    if not isinstance(messages, list):
        return 0

    max_index = 0
    prefix = f"{part_type}_"
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant":
            part_id = message.get("id")
        else:
            assistant = message.get("assistant")
            if not isinstance(assistant, dict):
                continue
            part_id = assistant.get("id")
        if not isinstance(part_id, str) or not part_id.startswith(prefix):
            continue
        suffix = part_id[len(prefix):]
        index_text = suffix.partition("_")[0]
        if index_text.isdigit():
            max_index = max(max_index, int(index_text))
    return max_index


__all__ = ["clear_stream_part_ids", "max_session_part_index", "next_stream_part_id"]
