from __future__ import annotations

from threading import RLock
from typing import Any

_RECOVERY_EVENTS: dict[str, list[dict[str, Any]]] = {}
_RECOVERY_EVENTS_LOCK = RLock()


def enqueue_recovery_events(
    conversation_id: str,
    message_id: str,
    events: list[dict[str, Any]],
) -> None:
    """Queue display-only terminal events for the next stream subscriber."""
    if not events:
        return
    enriched = [
        {
            **event,
            "conversationId": conversation_id,
            "messageId": message_id,
        }
        for event in events
    ]
    with _RECOVERY_EVENTS_LOCK:
        _RECOVERY_EVENTS.setdefault(conversation_id, []).extend(enriched)


def drain_recovery_events(conversation_id: str) -> list[dict[str, Any]]:
    """Remove and return display-only terminal events queued for a conversation."""
    with _RECOVERY_EVENTS_LOCK:
        return _RECOVERY_EVENTS.pop(conversation_id, [])


def discard_recovery_events(conversation_id: str) -> None:
    with _RECOVERY_EVENTS_LOCK:
        _RECOVERY_EVENTS.pop(conversation_id, None)


__all__ = ["discard_recovery_events", "drain_recovery_events", "enqueue_recovery_events"]
