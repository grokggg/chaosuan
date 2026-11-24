from __future__ import annotations

from typing import Any


def string_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def bool_or_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    return False


def dict_string(item: dict[str, Any], key: str) -> str:
    return string_or_empty(item.get(key))


__all__ = ["bool_or_false", "dict_string", "string_or_empty"]
