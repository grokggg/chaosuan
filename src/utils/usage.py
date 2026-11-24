from __future__ import annotations

from typing import Any


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def first_int(*values: Any) -> int | None:
    for value in values:
        number = int_or_none(value)
        if number is not None:
            return number
    return None


def normalize_usage(raw_usage: Any) -> dict[str, int] | None:
    if not isinstance(raw_usage, dict):
        return None

    prompt_details = raw_usage.get("prompt_tokens_details")
    if not isinstance(prompt_details, dict):
        prompt_details = {}
    completion_details = raw_usage.get("completion_tokens_details")
    if not isinstance(completion_details, dict):
        completion_details = {}
    output_details = raw_usage.get("output_token_details")
    if not isinstance(output_details, dict):
        output_details = {}

    prompt_tokens = first_int(raw_usage.get("prompt_tokens"), raw_usage.get("input_tokens"))
    completion_tokens = first_int(raw_usage.get("completion_tokens"), raw_usage.get("output_tokens"))
    total_tokens = int_or_none(raw_usage.get("total_tokens"))
    reasoning_tokens = first_int(
        completion_details.get("reasoning_tokens"),
        output_details.get("reasoning_tokens"),
        output_details.get("reasoning"),
    )
    cached_tokens = first_int(
        raw_usage.get("cache_read_input_tokens"),
        prompt_details.get("cached_tokens"),
    )
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_tokens": cached_tokens,
    }
    normalized = {key: value for key, value in usage.items() if isinstance(value, int)}
    return normalized or None


def extract_response_usage(response: Any) -> dict[str, int] | None:
    usage = normalize_usage(getattr(response, "usage_metadata", None))
    if usage:
        return usage

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        for key in ("token_usage", "usage"):
            usage = normalize_usage(response_metadata.get(key))
            if usage:
                return usage
    return None


def add_usage(total: dict[str, int], usage: dict[str, int] | None) -> None:
    if not usage:
        return
    for key, value in usage.items():
        total[key] = total.get(key, 0) + value


def text_tokens_from_usage(usage: dict[str, int]) -> int:
    return max((usage.get("completion_tokens") or 0) - (usage.get("reasoning_tokens") or 0), 0)


def log_usage(
    logger: Any,
    message: str,
    usage: dict[str, int] | None,
    *,
    elapsed_seconds: float | None = None,
    **fields: Any,
) -> dict[str, int]:
    normalized = usage or {}
    parts = [message]
    if elapsed_seconds is not None:
        parts.append("elapsed_seconds=%.3f")
    for key in fields:
        parts.append(f"{key}=%s")
    parts.extend(
        [
            "prompt_tokens=%s",
            "completion_tokens=%s",
            "reasoning_tokens=%s",
            "total_tokens=%s",
        ]
    )
    args: list[Any] = []
    if elapsed_seconds is not None:
        args.append(elapsed_seconds)
    args.extend(fields.values())
    args.extend(
        [
            normalized.get("prompt_tokens"),
            normalized.get("completion_tokens"),
            normalized.get("reasoning_tokens"),
            normalized.get("total_tokens"),
        ]
    )
    logger.info(" ".join(parts), *args)
    return normalized


__all__ = [
    "add_usage",
    "extract_response_usage",
    "first_int",
    "int_or_none",
    "log_usage",
    "normalize_usage",
    "text_tokens_from_usage",
]
