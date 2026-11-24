from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

try:
    from langgraph.config import get_stream_writer
except ImportError:  # pragma: no cover - only for isolated utility use
    get_stream_writer = None


@dataclass(slots=True)
class AttemptHandle:
    attempt_id: str
    attempt_number: int
    max_attempts: int
    model: str
    lc_source: str | None = None
    delivery_failed: bool = False


def attempt_stream_available() -> bool:
    if get_stream_writer is None:
        return False
    try:
        writer = get_stream_writer()
    except Exception:
        return False
    return callable(writer)


def _write(payload: dict[str, Any]) -> bool:
    if get_stream_writer is None:
        return False
    try:
        writer = get_stream_writer()
        if not callable(writer):
            return False
        writer(payload)
    except Exception:
        return False
    return True


def begin_attempt(
    attempt_number: int,
    max_attempts: int,
    model: str,
    *,
    lc_source: str | None = None,
) -> AttemptHandle:
    handle = AttemptHandle(uuid4().hex, attempt_number, max_attempts, model, lc_source)
    if not _write(
        {
            "type": "model-attempt-start",
            "attemptId": handle.attempt_id,
            "attemptNumber": attempt_number,
            "maxAttempts": max_attempts,
            "model": model,
            "lcSource": lc_source,
        }
    ):
        handle.delivery_failed = True
    return handle


def emit_attempt_delta(handle: AttemptHandle, *, text_delta: str = "", reasoning_delta: str = "") -> None:
    if not text_delta and not reasoning_delta:
        return
    if not _write(
        {
            "type": "model-attempt-delta",
            "attemptId": handle.attempt_id,
            "textDelta": text_delta,
            "reasoningDelta": reasoning_delta,
            "lcSource": handle.lc_source,
        }
    ):
        handle.delivery_failed = True


def reset_attempt(handle: AttemptHandle, error: BaseException, *, retrying: bool = True) -> None:
    if not _write(
        {
            "type": "model-attempt-reset",
            "attemptId": handle.attempt_id,
            "retrying": retrying,
            "lcSource": handle.lc_source,
        }
    ):
        handle.delivery_failed = True


def commit_attempt(handle: AttemptHandle, finish_reason: str) -> bool:
    if handle.delivery_failed:
        reset_attempt(
            handle,
            RuntimeError("attempt stream delivery failed"),
            retrying=False,
        )
        return False
    if not _write(
        {
            "type": "model-attempt-commit",
            "attemptId": handle.attempt_id,
            "finishReason": finish_reason,
            "lcSource": handle.lc_source,
        }
    ):
        handle.delivery_failed = True
        reset_attempt(
            handle,
            RuntimeError("attempt stream delivery failed"),
            retrying=False,
        )
        return False
    return True


__all__ = [
    "AttemptHandle",
    "attempt_stream_available",
    "begin_attempt",
    "commit_attempt",
    "emit_attempt_delta",
    "reset_attempt",
]
