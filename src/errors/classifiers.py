"""Domain error classifiers for the template runtime.

Kept aligned with ``sag-maker-vcagent/src/errors/classifiers.py``: same-named
codes must classify the same way. Classifiers recursively expand
``BaseExceptionGroup`` and ``__cause__`` / ``__context__`` and never use the
outermost wrapper as the classification basis or user text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .catalog import (
    MCP_CLIENT_LIFECYCLE_ERROR,
    MCP_CONNECT_FAILED,
    MCP_TIMEOUT,
    MODEL_AUTH_FAILED,
    RETRYABLE_ERROR_CODES,
    SOURCE_MCP,
    SOURCE_MODEL,
    SYSTEM_INTERNAL_ERROR,
    ErrorInfo,
)

_HTTP_STATUS_PATTERN = re.compile(
    r"(?i)\b(?:http(?:/\d(?:\.\d)?)?\s+|status(?:_code|\s+code)?\s*[:=]?\s*)([45]\d{2})\b"
)


def exception_leaves(exc: BaseException) -> Iterable[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            yield from exception_leaves(child)
        return
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        yield from exception_leaves(cause)
        return
    yield exc


def _http_status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    for candidate in (getattr(exc, "status_code", None), getattr(response, "status_code", None)):
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            continue
    match = _HTTP_STATUS_PATTERN.search(str(exc))
    if match is not None:
        return int(match.group(1))
    return None


def _classify_mcp_leaf(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    status_code = _http_status_code(exc)
    if status_code in {408, 429} or (status_code is not None and 500 <= status_code <= 599):
        return MCP_CONNECT_FAILED
    if status_code is not None and 400 <= status_code <= 499:
        return MCP_CLIENT_LIFECYCLE_ERROR
    if isinstance(exc, TimeoutError) or "timeout" in name or "timed out" in message:
        return MCP_TIMEOUT
    if (
        "connecterror" in name
        or "connectionerror" in name
        or "connectionreset" in name
        or "connectionrefused" in name
        or "brokenpipe" in name
        or "connection aborted" in message
        or "connection reset" in message
        or "tls handshake" in message
        or "ssl eof" in message
        or "connect error" in message
    ):
        return MCP_CONNECT_FAILED
    if (
        "no running event loop" in message
        or "brokenresource" in name
        or "event loop is closed" in message
        or "cross-thread" in message
    ):
        return MCP_CLIENT_LIFECYCLE_ERROR
    return MCP_CLIENT_LIFECYCLE_ERROR


def classify_mcp_error(
    exc: BaseException,
    *,
    stage: str,
    server_name: str | None = None,
    tool_name: str | None = None,
) -> ErrorInfo:
    leaves = list(exception_leaves(exc)) or [exc]
    codes = [_classify_mcp_leaf(leaf) for leaf in leaves]
    code = next((item for item in codes if item in RETRYABLE_ERROR_CODES), codes[0])
    return ErrorInfo.of(
        code,
        source=SOURCE_MCP,
        stage=stage,
        context={"server_name": server_name} if server_name else {},
    )


def _classify_model_leaf(exc: BaseException) -> str:
    name = exc.__class__.__name__.lower()
    status_code = _http_status_code(exc)

    if status_code in {401, 403}:
        return MODEL_AUTH_FAILED

    if name in {"authenticationerror", "permissiondeniederror", "badrequesterror"}:
        return MODEL_AUTH_FAILED

    return SYSTEM_INTERNAL_ERROR


def classify_model_error(
    exc: BaseException,
    *,
    stage: str,
    model_name: str | None = None,
) -> ErrorInfo:
    leaves = list(exception_leaves(exc)) or [exc]
    codes = [_classify_model_leaf(leaf) for leaf in leaves]
    code = next((item for item in codes if item in RETRYABLE_ERROR_CODES), codes[0])
    return ErrorInfo.of(
        code,
        source=SOURCE_MODEL,
        stage=stage,
        context={"model_name": model_name} if model_name else {},
    )