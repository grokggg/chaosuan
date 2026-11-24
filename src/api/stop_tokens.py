from __future__ import annotations

from threading import RLock

_STOP_REQUESTED_CONVERSATIONS: set[str] = set()
_LOCK = RLock()


def request_graph_stop(conversation_id: str) -> None:
    normalized_id = str(conversation_id or "").strip()
    if not normalized_id:
        return
    with _LOCK:
        _STOP_REQUESTED_CONVERSATIONS.add(normalized_id)


def clear_graph_stop(conversation_id: str) -> None:
    normalized_id = str(conversation_id or "").strip()
    if not normalized_id:
        return
    with _LOCK:
        _STOP_REQUESTED_CONVERSATIONS.discard(normalized_id)


def consume_graph_stop(conversation_id: str) -> bool:
    normalized_id = str(conversation_id or "").strip()
    if not normalized_id:
        return False
    with _LOCK:
        if normalized_id not in _STOP_REQUESTED_CONVERSATIONS:
            return False
        _STOP_REQUESTED_CONVERSATIONS.remove(normalized_id)
        return True


__all__ = ["clear_graph_stop", "consume_graph_stop", "request_graph_stop"]
