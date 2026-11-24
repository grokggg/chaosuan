"""Small wall-clock timers for startup; no profiler or third-party dependencies."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_CAPTURED_STAGES: ContextVar[dict[tuple[str, str], float] | None] = ContextVar("startup_stages", default=None)


@contextmanager
def capture_startup_stages() -> Iterator[dict[tuple[str, str], float]]:
    """Capture this startup's stages, including its child asyncio tasks."""
    stages: dict[tuple[str, str], float] = {}
    token = _CAPTURED_STAGES.set(stages)
    try:
        yield stages
    finally:
        _CAPTURED_STAGES.reset(token)


class StartupTimer:
    def __init__(self, logger: logging.Logger, scope: str, *, started_at: float | None = None) -> None:
        self.logger = logger
        self.scope = scope
        self.started_at = time.perf_counter() if started_at is None else started_at
        self.stages: list[tuple[str, float]] = []

    def record(self, stage: str, started_at: float, finished_at: float, *, status: str = "ok") -> None:
        duration_ms = (finished_at - started_at) * 1000
        self.stages.append((stage, duration_ms))
        captured = _CAPTURED_STAGES.get()
        if captured is not None:
            captured[(self.scope, stage)] = duration_ms
        self.logger.debug(
            "STARTUP_TIMING scope=%s stage=%s status=%s duration_ms=%.3f elapsed_ms=%.3f",
            self.scope,
            stage,
            status,
            duration_ms,
            (finished_at - self.started_at) * 1000,
        )

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        self.logger.debug("STARTUP_TIMING scope=%s stage=%s status=begin", self.scope, name)
        started_at = time.perf_counter()
        status = "ok"
        try:
            yield
        except BaseException:
            status = "failed"
            raise
        finally:
            self.record(name, started_at, time.perf_counter(), status=status)

    def summary(self) -> None:
        total_ms = (time.perf_counter() - self.started_at) * 1000
        measured_ms = sum(duration for _, duration in self.stages)
        overlap_ms = max(0.0, measured_ms - total_ms)
        other_ms = max(0.0, total_ms - measured_ms)
        stages_ms = {name: round(duration, 3) for name, duration in self.stages}
        self.logger.info(
            "STARTUP_SUMMARY scope=%s total_ms=%.3f measured_stages_ms=%.3f "
            "overlap_ms=%.3f other_ms=%.3f stages_ms=%s",
            self.scope,
            total_ms,
            measured_ms,
            overlap_ms,
            other_ms,
            json.dumps(stages_ms, separators=(",", ":")),
        )


class StartupReadiness:
    """Report once when all expected servers finish lifespan and socket startup.

    Call from the same event loop, after Uvicorn sets ``started``. This measures
    application startup, not container creation or an external HTTP probe.
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        started_at: float,
        servers: tuple[str, ...],
        stage_durations: dict[tuple[str, str], float] | None = None,
    ) -> None:
        self.logger = logger
        self.started_at = started_at
        self.expected = frozenset(servers)
        if not self.expected:
            raise ValueError("At least one server must be expected")
        self.started: set[str] = set()
        self.reported = False
        self.stage_durations = stage_durations if stage_durations is not None else {}

    def _phase_fields(self, total_ms: float) -> str:
        imports = [
            duration
            for (scope, stage), duration in self.stage_durations.items()
            if scope == "server" and stage.startswith("imports.")
        ]
        imports_ms = sum(imports) if imports else None
        # default_agent_preload encloses the whole agent_build scope, so it is a
        # top-level phase of its own. mcp_tools and model_client live inside it:
        # they are reported right after it as nested sub-items and must not be
        # subtracted from the total a second time.
        preload_ms = self.stage_durations.get(("server", "default_agent_preload"))
        top_level = [value for value in (imports_ms, preload_ms) if value is not None]
        phases = {
            "imports_ms": imports_ms,
            "preload_ms": preload_ms,
            "mcp_ms": self.stage_durations.get(("agent_build", "mcp_tools")),
            "model_client_ms": self.stage_durations.get(("agent_build", "model_client")),
            "other_ms": total_ms - sum(top_level) if top_level else None,
        }
        return " ".join(
            f"{name}={value:.3f}" if value is not None else f"{name}=not_measured" for name, value in phases.items()
        )

    def mark_started(self, name: str) -> None:
        if name not in self.expected:
            raise ValueError(f"Unexpected startup server: {name}")
        if name in self.started:
            return
        self.started.add(name)
        # Capture the finish before writing diagnostic output.
        total_seconds = time.perf_counter() - self.started_at
        self.logger.debug("STARTUP_LISTENER server=%s elapsed_ms=%.3f", name, total_seconds * 1000)
        if self.started == self.expected and not self.reported:
            self.reported = True
            self.logger.info(
                "STARTUP_READY status=ok total_seconds=%.3f total_ms=%.3f %s "
                "ready_definition=lifespan_and_listeners servers=%s",
                total_seconds,
                total_seconds * 1000,
                self._phase_fields(total_seconds * 1000),
                ",".join(sorted(self.expected)),
            )


@contextmanager
def trace_startup_ssl(logger: logging.Logger) -> Iterator[None]:
    """Opt-in SSL diagnostics during preload; always restore the original function."""
    if os.getenv("STARTUP_TRACE_SSL", "").lower() not in {"1", "true", "yes"}:
        yield
        return

    import ssl
    from functools import wraps

    original = ssl.create_default_context
    calls = 0
    total_ms = 0.0

    @wraps(original)
    def measured(*args, **kwargs):
        nonlocal calls, total_ms
        started_at = time.perf_counter()
        status = "ok"
        try:
            return original(*args, **kwargs)
        except BaseException:
            status = "failed"
            raise
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000
            calls += 1
            total_ms += duration_ms
            logger.debug(
                "STARTUP_TIMING scope=ssl stage=create_default_context status=%s call=%s duration_ms=%.3f",
                status,
                calls,
                duration_ms,
            )

    ssl.create_default_context = measured
    try:
        yield
    finally:
        ssl.create_default_context = original
        logger.info("STARTUP_SUMMARY scope=ssl calls=%s total_ms=%.3f", calls, total_ms)
