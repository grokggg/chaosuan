from __future__ import annotations

import time
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass
class ModelTiming:
    started_at: float
    first_token_at: float | None = None


_CURRENT_MODEL_TIMING: ContextVar[ModelTiming | None] = ContextVar(
    "current_model_timing",
    default=None,
)


def start_model_timing() -> tuple[ModelTiming, Token[ModelTiming | None]]:
    timing = ModelTiming(started_at=time.perf_counter())
    token = _CURRENT_MODEL_TIMING.set(timing)
    return timing, token


def reset_model_timing(token: Token[ModelTiming | None]) -> None:
    _CURRENT_MODEL_TIMING.reset(token)


def mark_first_token() -> None:
    timing = _CURRENT_MODEL_TIMING.get()
    if timing is None or timing.first_token_at is not None:
        return
    timing.first_token_at = time.perf_counter()


__all__ = ["ModelTiming", "mark_first_token", "reset_model_timing", "start_model_timing"]
