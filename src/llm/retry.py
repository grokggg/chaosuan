from __future__ import annotations

import math
from typing import Any

DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_DELAY_SECONDS = 1.0
DEFAULT_MAX_DELAY_SECONDS = 8.0
MIN_MAX_RETRIES = 0
MAX_MAX_RETRIES = 5
RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
_RETRYABLE_ERROR_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "PoolTimeout",
        "RateLimitError",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "TimeoutException",
        "TransportError",
        "WriteError",
        "WriteTimeout",
    }
)


class MissingFinishReasonError(RuntimeError):
    """Raised when a model stream ends without a terminal finish reason."""


class ModelRetryExhaustedError(RuntimeError):
    """All configured attempts for one selected model failed."""

    def __init__(
        self,
        attempts: int,
        last_error: BaseException,
        *,
        model: str = "",
    ) -> None:
        self.attempts = int(attempts)
        self.actual_attempts = self.attempts
        self.last_error = last_error
        self.last_upstream_error = last_error
        self.model = model
        super().__init__(
            f"Model retry exhausted after {self.attempts} attempt(s)"
            + (f" for {model}" if model else "")
            + f": {str(last_error).strip() or last_error.__class__.__name__}"
        )


def iter_exception_tree(exc: BaseException) -> list[BaseException]:
    items: list[BaseException] = []
    pending = [exc]
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


def error_status_code(exc: BaseException) -> int | None:
    for item in iter_exception_tree(exc):
        for value in (
            getattr(item, "status_code", None),
            getattr(getattr(item, "response", None), "status_code", None),
            getattr(item, "code", None),
        ):
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().isdigit():
                return int(value.strip())
    return None


def is_retryable_error(exc: BaseException) -> bool:
    for item in iter_exception_tree(exc):
        if error_status_code(item) in RETRYABLE_STATUS_CODES:
            return True
        module = item.__class__.__module__
        if module.startswith(("openai", "httpx", "httpcore")) and item.__class__.__name__ in _RETRYABLE_ERROR_NAMES:
            return True
    return False


def retry_delay(attempt_number: int, *, base_delay_seconds: float, max_delay_seconds: float) -> float:
    """Return exponential backoff for the retry after the given attempt number."""

    return min(max_delay_seconds, base_delay_seconds * math.pow(2, max(0, attempt_number - 1)))


def retry_error_details(exc: BaseException) -> dict[str, Any]:
    details: dict[str, Any] = {"message": str(exc).strip() or exc.__class__.__name__}
    status = error_status_code(exc)
    if status is not None:
        details["statusCode"] = status
    for item in iter_exception_tree(exc):
        for attr, key in (("code", "code"), ("request_id", "requestId")):
            value = getattr(item, attr, None)
            if value is not None and str(value).strip():
                details[key] = value
    return details


def validate_retry_config(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
) -> tuple[int, float, float]:
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not MIN_MAX_RETRIES <= max_retries <= MAX_MAX_RETRIES:
        raise ValueError(f"max_retries must be between {MIN_MAX_RETRIES} and {MAX_MAX_RETRIES}")
    base = float(base_delay_seconds)
    maximum = float(max_delay_seconds)
    if not math.isfinite(base) or not math.isfinite(maximum) or base < 0 or maximum < 0 or maximum < base:
        raise ValueError("retry delays must be non-negative and max_delay_seconds must be >= base_delay_seconds")
    return max_retries, base, maximum


__all__ = [
    "DEFAULT_BASE_DELAY_SECONDS",
    "DEFAULT_MAX_DELAY_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "MAX_MAX_RETRIES",
    "MIN_MAX_RETRIES",
    "MissingFinishReasonError",
    "ModelRetryExhaustedError",
    "RETRYABLE_STATUS_CODES",
    "error_status_code",
    "is_retryable_error",
    "iter_exception_tree",
    "retry_delay",
    "retry_error_details",
    "validate_retry_config",
]
