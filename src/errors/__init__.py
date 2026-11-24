"""Unified backend error base for the template runtime."""

from __future__ import annotations

from . import catalog
from .adapters import (
    log_fields,
    rest_error,
    sse_error_text,
    system_error_text,
    tool_error_text,
    user_message,
)
from .catalog import (
    ERROR_MESSAGES,
    RETRYABLE_ERROR_CODES,
    ErrorInfo,
    is_retryable,
    message_for,
)
from .classifiers import (
    classify_mcp_error,
    classify_model_error,
    exception_leaves,
)
from .policy import ErrorAction, OperationSafety, decide_error_action, retry_after_seconds

__all__ = [
    "ERROR_MESSAGES",
    "RETRYABLE_ERROR_CODES",
    "ErrorInfo",
    "ErrorAction",
    "OperationSafety",
    "catalog",
    "classify_mcp_error",
    "classify_model_error",
    "exception_leaves",
    "decide_error_action",
    "is_retryable",
    "log_fields",
    "message_for",
    "rest_error",
    "retry_after_seconds",
    "sse_error_text",
    "system_error_text",
    "tool_error_text",
    "user_message",
]
