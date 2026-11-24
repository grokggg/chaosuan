"""Outward-facing adapters for the template runtime.

Kept aligned with ``sag-maker-vcagent/src/errors/adapters.py``.
"""

from __future__ import annotations

from typing import Any

from .catalog import SYSTEM_INTERNAL_ERROR, ErrorInfo, message_for


def user_message(error: ErrorInfo | str) -> str:
    if isinstance(error, ErrorInfo):
        return error.message
    return message_for(error)


def rest_error(error: ErrorInfo | str, *, code: int = 1, data: Any = None) -> dict[str, Any]:
    return {"code": code, "msg": user_message(error), "data": data}


def sse_error_text(error: ErrorInfo | str) -> str:
    return user_message(error)


def tool_error_text(error: ErrorInfo | str) -> str:
    return user_message(error)


def log_fields(error: ErrorInfo) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "event": "backend_error",
        "error_code": error.error_code,
        "source": error.source,
        "stage": error.stage,
        "retryable": error.retryable,
    }
    for key, value in (error.context or {}).items():
        if value:
            fields[key] = value
    return fields


def system_error_text() -> str:
    return message_for(SYSTEM_INTERNAL_ERROR)
