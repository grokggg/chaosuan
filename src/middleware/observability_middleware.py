"""Model request logging and low-overhead performance timing.

Environment variables:
- PERFORMANCE_TIMING_ENABLED: set to false/0/off/no to disable (default: enabled).
- PERFORMANCE_TIMING_SAMPLE_RATE: sampled request ratio from 0 to 1 (default: 1).
- PERFORMANCE_TIMING_INCLUDE_ITEMS: include aggregated model/tool details (default: enabled).

Request summaries are always logged and are independent of performance sampling.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel

from src.agents.context import AgentRuntimeContext
from src.llm import LLMModel, resolve_model
from src.llm.timing import reset_model_timing, start_model_timing
from src.logger import get_logger
from src.utils import load_current_llm_config

logger = get_logger(__name__)

_CONTEXT_ATTRIBUTE = "_performance_timing_run"
_FALSE_VALUES = {"0", "false", "no", "off"}
_LOGGED_MODEL_PARAM_KEYS = {
    "model_name",
    "temperature",
    "top_p",
    "frequency_penalty",
    "reasoning_effort",
    "extra_body",
    "model_kwargs",
}


def _resolve_current_model() -> LLMModel:
    llm_config = load_current_llm_config()
    return resolve_model(llm_config if isinstance(llm_config, dict) else None)


def _log_model_request_summary(request: ModelRequest, *, conversation_id: str | None, model: LLMModel) -> None:
    logger.info(
        "Model request before call conversation_id=%s model=%s system_message=%s messages=%s tools=%s params=%s",
        conversation_id or "-",
        model.ref,
        1 if request.system_message is not None else 0,
        len(request.messages or []),
        len(request.tools or []),
        json.dumps(_model_request_params(request), ensure_ascii=False, default=str),
    )


def _jsonable(value: Any, *, seen: set[int] | None = None) -> Any:
    if seen is None:
        seen = set()

    if value is None or isinstance(value, str | int | float | bool):
        return value

    value_id = id(value)
    if value_id in seen:
        return f"<circular:{value.__class__.__name__}>"

    if isinstance(value, BaseModel):
        seen.add(value_id)
        try:
            return _jsonable(value.model_dump(mode="json", exclude_none=True), seen=seen)
        except Exception:
            return _jsonable(value.model_dump(exclude_none=True), seen=seen)
        finally:
            seen.discard(value_id)

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        seen.add(value_id)
        try:
            return {field.name: _jsonable(getattr(value, field.name), seen=seen) for field in dataclasses.fields(value)}
        finally:
            seen.discard(value_id)

    if isinstance(value, dict):
        seen.add(value_id)
        try:
            return {str(key): _jsonable(item, seen=seen) for key, item in value.items()}
        finally:
            seen.discard(value_id)

    if isinstance(value, list | tuple | set | frozenset):
        seen.add(value_id)
        try:
            return [_jsonable(item, seen=seen) for item in value]
        finally:
            seen.discard(value_id)

    if hasattr(value, "model_dump"):
        seen.add(value_id)
        try:
            return _jsonable(value.model_dump(exclude_none=True), seen=seen)
        except Exception:
            pass
        finally:
            seen.discard(value_id)

    return {
        "_type": f"{value.__class__.__module__}.{value.__class__.__name__}",
        "repr": repr(value),
    }


def _model_summary(model: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "_type": f"{model.__class__.__module__}.{model.__class__.__name__}",
        "repr": repr(model),
    }
    for attr in (
        "model_name",
        "model",
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "max_tokens",
        "max_completion_tokens",
        "reasoning_effort",
        "extra_body",
        "model_kwargs",
        "streaming",
        "stream_usage",
        "disable_streaming",
    ):
        if hasattr(model, attr):
            value = getattr(model, attr)
            if value is not None:
                summary[attr] = _jsonable(value)
    return summary


def _model_request_params(request: ModelRequest) -> dict[str, Any]:
    summary = _model_summary(request.model)
    params = {key: value for key, value in summary.items() if key in _LOGGED_MODEL_PARAM_KEYS}
    settings = request.model_settings or {}
    if isinstance(settings, dict):
        params.update(
            {str(key): _jsonable(value) for key, value in settings.items() if str(key) in _LOGGED_MODEL_PARAM_KEYS}
        )
    return params


@dataclass(slots=True)
class _ModelSpan:
    index: int
    model: str
    started_at: float
    ended_at: float
    first_token_at: float | None
    status: str
    error_type: str | None = None


@dataclass(slots=True)
class _ToolSpan:
    name: str
    tool_call_id: str
    started_at: float
    ended_at: float
    status: str
    error_type: str | None = None


@dataclass(slots=True)
class _PerformanceRun:
    user_id: str | None
    conversation_id: str | None
    started_at: float
    include_items: bool
    model_spans: list[_ModelSpan] = field(default_factory=list)
    tool_spans: list[_ToolSpan] = field(default_factory=list)
    next_model_index: int = 1


def _env_enabled(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in _FALSE_VALUES


def _sample_rate() -> float:
    raw_value = os.getenv("PERFORMANCE_TIMING_SAMPLE_RATE", "1").strip()
    try:
        return min(1.0, max(0.0, float(raw_value)))
    except ValueError:
        return 1.0


def _runtime_context(runtime: Any) -> AgentRuntimeContext | None:
    context = getattr(runtime, "context", None)
    return context if isinstance(context, AgentRuntimeContext) else None


def _current_run(runtime: Any) -> _PerformanceRun | None:
    context = _runtime_context(runtime)
    run = getattr(context, _CONTEXT_ATTRIBUTE, None) if context is not None else None
    return run if isinstance(run, _PerformanceRun) else None


def _model_name(model: Any) -> str:
    for attribute in ("model_name", "model"):
        value = getattr(model, attribute, None)
        if isinstance(value, str) and value:
            return value
    return model.__class__.__name__


def _span_status(error: BaseException | None) -> str:
    if error is None:
        return "success"
    return "cancelled" if isinstance(error, asyncio.CancelledError) else "error"


def _seconds(value: float) -> float:
    return round(max(0.0, value), 6)


def _percentage(part: float, total: float) -> float:
    return round((part / total * 100.0) if total > 0 else 0.0, 2)


def _interval_union_seconds(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0

    ordered = sorted((start, max(start, end)) for start, end in intervals)
    union_seconds = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        union_seconds += current_end - current_start
        current_start, current_end = start, end
    return union_seconds + current_end - current_start


def _aggregate_status(spans: list[_ModelSpan] | list[_ToolSpan]) -> str:
    statuses = {span.status for span in spans}
    return statuses.pop() if len(statuses) == 1 else "mixed"


def _error_types(spans: list[_ModelSpan] | list[_ToolSpan]) -> list[str]:
    return sorted({span.error_type for span in spans if span.error_type})


def _model_item(spans: list[_ModelSpan]) -> dict[str, Any]:
    model_names = list(dict.fromkeys(span.model for span in spans))
    ttft_values = [span.first_token_at - span.started_at for span in spans if span.first_token_at is not None]
    generation_values = [span.ended_at - span.first_token_at for span in spans if span.first_token_at is not None]
    item: dict[str, Any] = {
        "index": 1,
        "model": model_names[0] if len(model_names) == 1 else "mixed",
        "calls": len(spans),
        "totalSeconds": _seconds(sum(max(0.0, span.ended_at - span.started_at) for span in spans)),
        "ttftSeconds": _seconds(sum(max(0.0, value) for value in ttft_values)),
        "generationSeconds": _seconds(sum(max(0.0, value) for value in generation_values)),
        "status": _aggregate_status(spans),
    }
    if len(model_names) > 1:
        item["models"] = model_names
    error_types = _error_types(spans)
    if error_types:
        item["errorTypes"] = error_types
    return item


def _tool_items(spans: list[_ToolSpan]) -> list[dict[str, Any]]:
    spans_by_name: dict[str, list[_ToolSpan]] = {}
    for span in spans:
        spans_by_name.setdefault(span.name, []).append(span)

    items: list[dict[str, Any]] = []
    for name, named_spans in spans_by_name.items():
        item: dict[str, Any] = {
            "name": name,
            "calls": len(named_spans),
            "durationSeconds": _seconds(sum(max(0.0, span.ended_at - span.started_at) for span in named_spans)),
            "status": _aggregate_status(named_spans),
        }
        error_types = _error_types(named_spans)
        if error_types:
            item["errorTypes"] = error_types
        items.append(item)
    return items


def _performance_payload(run: _PerformanceRun, *, ended_at: float, status: str) -> dict[str, Any]:
    agent_wall = max(0.0, ended_at - run.started_at)
    model_intervals = [(span.started_at, span.ended_at) for span in run.model_spans]
    tool_intervals = [(span.started_at, span.ended_at) for span in run.tool_spans]
    model_wall = _interval_union_seconds(model_intervals)
    tool_wall = _interval_union_seconds(tool_intervals)
    model_sum = sum(max(0.0, end - start) for start, end in model_intervals)
    tool_sum = sum(max(0.0, end - start) for start, end in tool_intervals)
    occupied_wall = _interval_union_seconds([*model_intervals, *tool_intervals])
    overlap = max(0.0, model_wall + tool_wall - occupied_wall)
    other = max(0.0, agent_wall - occupied_wall)

    ttft_values = [
        max(0.0, span.first_token_at - span.started_at) for span in run.model_spans if span.first_token_at is not None
    ]
    generation_values = [
        max(0.0, span.ended_at - span.first_token_at) for span in run.model_spans if span.first_token_at is not None
    ]
    ttft_total = sum(ttft_values)
    generation_total = sum(generation_values)
    first_model_span = run.model_spans[0] if run.model_spans else None
    first_call_ttft = (
        max(0.0, first_model_span.first_token_at - first_model_span.started_at)
        if first_model_span is not None and first_model_span.first_token_at is not None
        else None
    )

    model_payload: dict[str, Any] = {
        "calls": len(run.model_spans),
        "wallSeconds": _seconds(model_wall),
        "sumSeconds": _seconds(model_sum),
        "ratioPercent": _percentage(model_wall, agent_wall),
        "ttftCalls": len(ttft_values),
        "ttftSeconds": _seconds(ttft_total),
        "firstCallTtftSeconds": _seconds(first_call_ttft) if first_call_ttft is not None else None,
        "ttftRatioOfAgentPercent": _percentage(ttft_total, agent_wall),
        "ttftRatioOfModelPercent": _percentage(ttft_total, model_sum),
        "generationSeconds": _seconds(generation_total),
    }
    tool_payload: dict[str, Any] = {
        "calls": len(run.tool_spans),
        "wallSeconds": _seconds(tool_wall),
        "sumSeconds": _seconds(tool_sum),
        "ratioPercent": _percentage(tool_wall, agent_wall),
    }
    if run.include_items:
        model_payload["items"] = [_model_item(run.model_spans)] if run.model_spans else []
        tool_payload["items"] = _tool_items(run.tool_spans)

    return {
        "type": "performance_timing",
        "userId": run.user_id,
        "conversationId": run.conversation_id,
        "status": status,
        "agentWallSeconds": _seconds(agent_wall),
        "model": model_payload,
        "tools": tool_payload,
        "overlapSeconds": _seconds(overlap),
        "otherSeconds": _seconds(other),
        "otherRatioPercent": _percentage(other, agent_wall),
    }


class ObservabilityMiddleware(AgentMiddleware):
    """Log model requests and measure model/tool timing with low overhead."""

    def __init__(self) -> None:
        self.enabled = _env_enabled("PERFORMANCE_TIMING_ENABLED", default=True)
        self.sample_rate = _sample_rate()
        self.include_items = _env_enabled("PERFORMANCE_TIMING_INCLUDE_ITEMS", default=True)

    def _start_run(self, runtime: Runtime) -> None:
        if not self.enabled or self.sample_rate <= 0 or random.random() > self.sample_rate:
            return
        context = _runtime_context(runtime)
        if context is None:
            return
        setattr(
            context,
            _CONTEXT_ATTRIBUTE,
            _PerformanceRun(
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                started_at=time.perf_counter(),
                include_items=self.include_items,
            ),
        )

    def _finish_run(self, runtime: Runtime, *, status: str = "success") -> None:
        context = _runtime_context(runtime)
        run = _current_run(runtime)
        if context is None or run is None:
            return
        ended_at = time.perf_counter()
        try:
            payload = _performance_payload(run, ended_at=ended_at, status=status)
            logger.info("PERF_TIMING %s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        finally:
            try:
                delattr(context, _CONTEXT_ATTRIBUTE)
            except AttributeError:
                pass

    def _log_request(self, request: ModelRequest) -> None:
        context = request.runtime.context
        conversation_id = context.conversation_id if isinstance(context, AgentRuntimeContext) else None
        model = _resolve_current_model()
        _log_model_request_summary(request, conversation_id=conversation_id, model=model)

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        self._start_run(runtime)
        return None

    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        self._start_run(runtime)
        return None

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        self._finish_run(runtime)
        return None

    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        self._finish_run(runtime)
        return None

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        self._log_request(request)
        run = _current_run(request.runtime)
        if run is None:
            return handler(request)

        model_timing, timing_token = start_model_timing()
        model_index = run.next_model_index
        run.next_model_index += 1
        error: BaseException | None = None
        try:
            return handler(request)
        except BaseException as exc:
            error = exc
            raise
        finally:
            ended_at = time.perf_counter()
            reset_model_timing(timing_token)
            run.model_spans.append(
                _ModelSpan(
                    index=model_index,
                    model=_model_name(request.model),
                    started_at=model_timing.started_at,
                    ended_at=ended_at,
                    first_token_at=model_timing.first_token_at,
                    status=_span_status(error),
                    error_type=type(error).__name__ if error is not None else None,
                )
            )

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        self._log_request(request)
        run = _current_run(request.runtime)
        if run is None:
            return await handler(request)

        model_timing, timing_token = start_model_timing()
        model_index = run.next_model_index
        run.next_model_index += 1
        error: BaseException | None = None
        try:
            return await handler(request)
        except BaseException as exc:
            error = exc
            raise
        finally:
            ended_at = time.perf_counter()
            reset_model_timing(timing_token)
            run.model_spans.append(
                _ModelSpan(
                    index=model_index,
                    model=_model_name(request.model),
                    started_at=model_timing.started_at,
                    ended_at=ended_at,
                    first_token_at=model_timing.first_token_at,
                    status=_span_status(error),
                    error_type=type(error).__name__ if error is not None else None,
                )
            )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        run = _current_run(request.runtime)
        if run is None:
            return handler(request)

        started_at = time.perf_counter()
        error: BaseException | None = None
        try:
            return handler(request)
        except BaseException as exc:
            error = exc
            raise
        finally:
            run.tool_spans.append(
                _ToolSpan(
                    name=str(request.tool_call.get("name") or "tool"),
                    tool_call_id=str(request.tool_call.get("id") or ""),
                    started_at=started_at,
                    ended_at=time.perf_counter(),
                    status=_span_status(error),
                    error_type=type(error).__name__ if error is not None else None,
                )
            )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        run = _current_run(request.runtime)
        if run is None:
            return await handler(request)

        started_at = time.perf_counter()
        error: BaseException | None = None
        try:
            return await handler(request)
        except BaseException as exc:
            error = exc
            raise
        finally:
            run.tool_spans.append(
                _ToolSpan(
                    name=str(request.tool_call.get("name") or "tool"),
                    tool_call_id=str(request.tool_call.get("id") or ""),
                    started_at=started_at,
                    ended_at=time.perf_counter(),
                    status=_span_status(error),
                    error_type=type(error).__name__ if error is not None else None,
                )
            )


__all__ = ["ObservabilityMiddleware"]
