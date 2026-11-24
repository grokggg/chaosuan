"""Deterministic runtime decisions for classified backend failures."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum

from .catalog import SOURCE_MCP, SOURCE_MODEL, SOURCE_SKILL, ErrorInfo


class ErrorAction(StrEnum):
    RETRY = "retry"
    RETURN_TO_AGENT = "return_to_agent"
    TERMINATE = "terminate"


class OperationSafety(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    UNKNOWN = "unknown"


_MCP_LIFECYCLE_STAGES = frozenset(
    {
        "connect",
        "discovery",
        "get_tools",
        "initialize",
        "list_tools",
        "load_tools",
    }
)
_MCP_TOOL_STAGES = frozenset({"tool", "tool_execute"})


def decide_error_action(
    error: ErrorInfo,
    *,
    agent_can_continue: bool,
    operation_safety: OperationSafety = OperationSafety.UNKNOWN,
) -> ErrorAction:
    """Choose handling from classified facts, never from model output."""

    if error.source == SOURCE_MODEL:
        return ErrorAction.RETRY if error.retryable else ErrorAction.TERMINATE

    if error.source == SOURCE_MCP:
        if error.retryable and error.stage in _MCP_LIFECYCLE_STAGES:
            return ErrorAction.RETRY
        if (
            error.retryable
            and error.stage in _MCP_TOOL_STAGES
            and operation_safety is OperationSafety.READ_ONLY
        ):
            return ErrorAction.RETRY
        return ErrorAction.RETURN_TO_AGENT if agent_can_continue else ErrorAction.TERMINATE

    if error.source == SOURCE_SKILL and agent_can_continue:
        return ErrorAction.RETURN_TO_AGENT

    return ErrorAction.TERMINATE


def _exception_tree(exc: BaseException) -> list[BaseException]:
    pending = [exc]
    result: list[BaseException] = []
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        result.append(current)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return result


def _retry_after_header(exc: BaseException) -> str | None:
    for item in _exception_tree(exc):
        response = getattr(item, "response", None)
        headers = getattr(response, "headers", None)
        if not isinstance(headers, Mapping):
            continue
        for name, value in headers.items():
            if str(name).lower() == "retry-after":
                text = str(value).strip()
                return text or None
    return None


def retry_after_seconds(
    exc: BaseException,
    *,
    now: datetime | None = None,
) -> float | None:
    """Read a Retry-After delta or HTTP date from an exception response."""

    value = _retry_after_header(exc)
    if value is None:
        return None

    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return max(0.0, (retry_at - current).total_seconds())

    return max(0.0, seconds)


__all__ = [
    "ErrorAction",
    "OperationSafety",
    "decide_error_action",
    "retry_after_seconds",
]
