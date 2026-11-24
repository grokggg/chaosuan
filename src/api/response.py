from __future__ import annotations

from typing import Any

from fastapi import status


def api_success(
    data: Any = None,
    *,
    msg: str = "ok",
    code: int = status.HTTP_200_OK,
    message: str | None = None,
) -> dict[str, Any]:
    if message is not None:
        msg = message
    return {
        "code": code,
        "msg": msg,
        "data": data,
    }


def api_error(
    *,
    code: int,
    msg: str | None = None,
    data: Any = None,
    message: str | None = None,
) -> dict[str, Any]:
    resolved_msg = msg if msg is not None else message
    return {
        "code": code,
        "msg": resolved_msg or "request failed",
        "data": data,
    }


__all__ = ["api_error", "api_success"]
