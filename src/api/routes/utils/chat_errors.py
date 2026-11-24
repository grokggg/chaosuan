from __future__ import annotations

import json
from typing import Any

from src.errors import classify_mcp_error, classify_model_error, user_message
from src.errors.catalog import SYSTEM_INTERNAL_ERROR


def is_connection_error(exc: BaseException) -> bool:
    for item in iter_exception_tree(exc):
        module = item.__class__.__module__
        name = item.__class__.__name__
        if module.startswith("openai") and name == "APIConnectionError":
            return True
        if module.startswith("httpx") and name in {
            "ConnectError",
            "ReadError",
            "ReadTimeout",
            "RemoteProtocolError",
            "TimeoutException",
            "TransportError",
        }:
            return True
        if module.startswith("httpcore") and name in {
            "ConnectError",
            "ReadError",
            "ReadTimeout",
            "RemoteProtocolError",
            "TimeoutException",
        }:
            return True
    return False


def is_model_request_error(exc: BaseException) -> bool:
    for item in iter_exception_tree(exc):
        module = item.__class__.__module__
        name = item.__class__.__name__
        if module.startswith("openai"):
            return True
        if module.startswith(("httpx", "httpcore")):
            if _is_model_request_url(_exception_request_url(item)):
                return True
        if name in {
            "APIError",
            "APIStatusError",
            "APITimeoutError",
            "BadRequestError",
            "AuthenticationError",
            "PermissionDeniedError",
            "RateLimitError",
            "ContextOverflowError",
        }:
            return True
    return False


def is_rate_limit_error(exc: BaseException) -> bool:
    for item in iter_exception_tree(exc):
        if item.__class__.__name__ == "RateLimitError":
            return True
        status_code = getattr(item, "status_code", None)
        if status_code == 429:
            return True
        response = getattr(item, "response", None)
        if getattr(response, "status_code", None) == 429:
            return True
        code = getattr(item, "code", None)
        if isinstance(code, str) and code.lower() in {"429", "rate_limit", "rate_limit_exceeded"}:
            return True
    return False


def _exception_request_url(exc: BaseException) -> str:
    request = getattr(exc, "request", None)
    url = getattr(request, "url", None)
    return str(url) if url is not None else ""


def _is_model_request_url(url: str) -> bool:
    normalized = url.lower()
    return any(
        marker in normalized
        for marker in (
            "/chat/completions",
            "/responses",
            "/embeddings",
            "/audio/",
            "/images/",
        )
    )


def exception_chain_summary(exc: BaseException) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        item: dict[str, Any] = {
            "type": f"{current.__class__.__module__}.{current.__class__.__name__}",
            "message": str(current),
        }
        for attr in ("status_code", "code", "request_id"):
            value = getattr(current, attr, None)
            if value is not None:
                item[attr] = value
        response = getattr(current, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            if status_code is not None:
                item["response_status_code"] = status_code
            text = getattr(response, "text", None)
            if isinstance(text, str) and text.strip():
                item["response_text"] = text[:2000]
        body = getattr(current, "body", None)
        if body is not None:
            item["body"] = body
        details.append(item)
        current = current.__cause__ or current.__context__
    return details


def iter_exception_tree(exc: BaseException) -> list[BaseException]:
    items: list[BaseException] = []
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        items.append(current)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return items


def is_mcp_tool_error(exc: BaseException) -> bool:
    for item in iter_exception_tree(exc):
        module = item.__class__.__module__
        if module.startswith(("mcp.", "langchain_mcp_adapters.")):
            return True
        if module.startswith("httpx") and item.__class__.__name__ in {
            "HTTPStatusError",
            "ConnectError",
            "ReadTimeout",
            "TimeoutException",
            "TransportError",
        }:
            if not _is_model_request_url(_exception_request_url(item)):
                return True
    return False


def http_status_error_text(exc: BaseException) -> str | None:
    for item in iter_exception_tree(exc):
        if item.__class__.__name__ != "HTTPStatusError":
            continue
        response = getattr(item, "response", None)
        request = getattr(item, "request", None)
        status_code = getattr(response, "status_code", None)
        reason = getattr(response, "reason_phrase", None)
        url = getattr(request, "url", None)
        status = f"HTTP {status_code}" if status_code is not None else "HTTP request failed"
        if reason:
            status = f"{status} {reason}"
        return f"{status} for {url}" if url is not None else status
    return None


def tool_error_output(exc: BaseException, *, tool_name: str | None = None) -> str:
    if is_mcp_tool_error(exc):
        return user_message(classify_mcp_error(exc, stage="tool_execute"))
    return user_message(classify_model_error(exc, stage="tool_execute"))


def stream_error_text(exc: BaseException) -> str:
    if is_model_request_error(exc):
        return user_message(classify_model_error(exc, stage="chat_stream"))
    if is_mcp_tool_error(exc):
        return user_message(classify_mcp_error(exc, stage="chat_stream"))
    return user_message(SYSTEM_INTERNAL_ERROR)


def connection_error_text(exc: BaseException) -> str:
    return user_message(classify_model_error(exc, stage="connect"))


def log_model_request_error(
    logger: Any,
    exc: BaseException,
    *,
    conversation_id: str,
    model_name: str,
) -> None:
    if not is_model_request_error(exc):
        return
    logger.error(
        "Model request failed conversation_id=%s model=%s error_chain=%s",
        conversation_id,
        model_name,
        json.dumps(exception_chain_summary(exc), ensure_ascii=False, default=str),
        exc_info=exc,
    )


__all__ = [
    "connection_error_text",
    "exception_chain_summary",
    "http_status_error_text",
    "is_connection_error",
    "is_mcp_tool_error",
    "is_model_request_error",
    "is_rate_limit_error",
    "log_model_request_error",
    "stream_error_text",
    "tool_error_output",
]
