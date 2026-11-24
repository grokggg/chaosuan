from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from typing import Any, Self

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables.config import ensure_config
from langchain_openai import ChatOpenAI
from pydantic import PrivateAttr

from src.llm.attempt_stream import (
    attempt_stream_available,
    begin_attempt,
    commit_attempt,
    emit_attempt_delta,
    reset_attempt,
)
from src.llm.retry import (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_MAX_DELAY_SECONDS,
    DEFAULT_MAX_RETRIES,
    MissingFinishReasonError,
    ModelRetryExhaustedError,
    is_retryable_error,
    retry_delay,
    validate_retry_config,
)
from src.llm.timing import mark_first_token
from src.logger import get_logger

logger = get_logger(__name__)
_STREAM_TOOL_NAMES: ContextVar[dict[int, str] | None] = ContextVar(
    "stream_tool_names",
    default=None,
)


def _stream_lc_source(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    model_metadata: dict[str, Any] | None = None,
) -> str | None:
    if isinstance(model_metadata, dict):
        value = model_metadata.get("lc_source")
        if isinstance(value, str) and value:
            return value
    run_manager = kwargs.get("run_manager")
    if run_manager is None and len(args) >= 3:
        run_manager = args[2]
    for attribute in ("metadata", "inheritable_metadata"):
        metadata = getattr(run_manager, attribute, None)
        if isinstance(metadata, dict):
            value = metadata.get("lc_source")
            if isinstance(value, str) and value:
                return value
    metadata = ensure_config().get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("lc_source")
        if isinstance(value, str) and value:
            return value
    return None


def _deduplicate_streamed_tool_names(chunk: dict[str, Any], names: dict[int, str]) -> dict[str, Any]:
    choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
    if not choices:
        return chunk

    choice = choices[0]
    delta = choice.get("delta")
    tool_calls = delta.get("tool_calls") if isinstance(delta, dict) else None
    if not isinstance(tool_calls, list):
        return chunk

    updated_tool_calls: list[Any] = []
    changed = False
    for position, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            updated_tool_calls.append(tool_call)
            continue
        function = tool_call.get("function")
        name = function.get("name") if isinstance(function, dict) else None
        if not isinstance(name, str) or not name:
            updated_tool_calls.append(tool_call)
            continue

        index = int(tool_call.get("index", position) or 0)
        accumulated = names.get(index, "")
        if accumulated and name == accumulated:
            updated_function = {**function, "name": None}
            updated_tool_calls.append({**tool_call, "function": updated_function})
            changed = True
        else:
            names[index] = f"{accumulated}{name}"
            updated_tool_calls.append(tool_call)

    if not changed:
        return chunk

    updated_delta = {**delta, "tool_calls": updated_tool_calls}
    updated_choice = {**choice, "delta": updated_delta}
    if chunk.get("choices"):
        return {**chunk, "choices": [updated_choice, *choices[1:]]}
    nested = chunk.get("chunk", {})
    return {**chunk, "chunk": {**nested, "choices": [updated_choice, *choices[1:]]}}


class ChatOpenAICustom(ChatOpenAI):
    """ChatOpenAI variant that preserves OpenAI-compatible reasoning deltas."""

    _retry_max_retries: int = PrivateAttr(default=DEFAULT_MAX_RETRIES)
    _retry_base_delay_seconds: float = PrivateAttr(default=DEFAULT_BASE_DELAY_SECONDS)
    _retry_max_delay_seconds: float = PrivateAttr(default=DEFAULT_MAX_DELAY_SECONDS)
    _retry_model_label: str = PrivateAttr(default="")

    def configure_retry(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        model_label: str | None = None,
    ) -> Self:
        retries, base, maximum = validate_retry_config(
            max_retries,
            base_delay_seconds,
            max_delay_seconds,
        )
        self._retry_max_retries = retries
        self._retry_base_delay_seconds = base
        self._retry_max_delay_seconds = maximum
        if model_label:
            self._retry_model_label = model_label
        return self

    def _generate(
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Apply the same bounded retry policy to non-streaming requests."""

        max_attempts = self._retry_max_retries + 1
        for attempt_number in range(1, max_attempts + 1):
            try:
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except BaseException as exc:
                if not is_retryable_error(exc) or attempt_number >= max_attempts:
                    raise
                time.sleep(
                    retry_delay(
                        attempt_number,
                        base_delay_seconds=self._retry_base_delay_seconds,
                        max_delay_seconds=self._retry_max_delay_seconds,
                    )
                )

        raise AssertionError("unreachable")

    async def _agenerate(
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Apply the same bounded retry policy to async non-streaming requests."""

        max_attempts = self._retry_max_retries + 1
        for attempt_number in range(1, max_attempts + 1):
            try:
                return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except BaseException as exc:
                if not is_retryable_error(exc) or attempt_number >= max_attempts:
                    raise
                await asyncio.sleep(
                    retry_delay(
                        attempt_number,
                        base_delay_seconds=self._retry_base_delay_seconds,
                        max_delay_seconds=self._retry_max_delay_seconds,
                    )
                )

        raise AssertionError("unreachable")

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        max_attempts = self._retry_max_retries + 1
        provisional = attempt_stream_available()
        lc_source = _stream_lc_source(args, kwargs, self.metadata)
        for attempt_number in range(1, max_attempts + 1):
            chunks: list[ChatGenerationChunk] = []
            finish_reason: str | None = None
            produced_effective_output = False
            handle = begin_attempt(
                attempt_number,
                max_attempts,
                self._retry_model_label or str(self.model_name),
                lc_source=lc_source,
            )
            tool_names_token = _STREAM_TOOL_NAMES.set({})
            try:
                for chunk in super()._stream(*args, **kwargs):
                    finish_reason = _chunk_finish_reason(chunk) or finish_reason
                    produced_effective_output = produced_effective_output or _is_effective_generation_chunk(chunk)
                    if provisional:
                        chunks.append(chunk)
                        _emit_chunk_delta(chunk, handle)
                    else:
                        yield chunk
                if not finish_reason:
                    raise MissingFinishReasonError("Model stream ended without finish_reason")
                if provisional:
                    commit_attempt(handle, finish_reason)
                    yield from chunks
                return
            except BaseException as exc:
                if not is_retryable_error(exc) and not isinstance(exc, MissingFinishReasonError):
                    raise
                if not provisional and produced_effective_output:
                    raise
                if attempt_number >= max_attempts:
                    reset_attempt(handle, exc, retrying=False)
                    raise ModelRetryExhaustedError(
                        attempt_number,
                        exc,
                        model=str(self.model_name),
                    ) from exc
                reset_attempt(handle, exc)
                time.sleep(
                    retry_delay(
                        attempt_number,
                        base_delay_seconds=self._retry_base_delay_seconds,
                        max_delay_seconds=self._retry_max_delay_seconds,
                    )
                )
            finally:
                _STREAM_TOOL_NAMES.reset(tool_names_token)

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        max_attempts = self._retry_max_retries + 1
        provisional = attempt_stream_available()
        lc_source = _stream_lc_source(args, kwargs, self.metadata)
        for attempt_number in range(1, max_attempts + 1):
            chunks: list[ChatGenerationChunk] = []
            finish_reason: str | None = None
            produced_effective_output = False
            handle = begin_attempt(
                attempt_number,
                max_attempts,
                self._retry_model_label or str(self.model_name),
                lc_source=lc_source,
            )
            tool_names_token = _STREAM_TOOL_NAMES.set({})
            try:
                async for chunk in super()._astream(*args, **kwargs):
                    finish_reason = _chunk_finish_reason(chunk) or finish_reason
                    produced_effective_output = produced_effective_output or _is_effective_generation_chunk(chunk)
                    if provisional:
                        chunks.append(chunk)
                        _emit_chunk_delta(chunk, handle)
                    else:
                        yield chunk
                if not finish_reason:
                    raise MissingFinishReasonError("Model stream ended without finish_reason")
                if provisional:
                    commit_attempt(handle, finish_reason)
                    for chunk in chunks:
                        yield chunk
                return
            except BaseException as exc:
                if not is_retryable_error(exc) and not isinstance(exc, MissingFinishReasonError):
                    raise
                if not provisional and produced_effective_output:
                    raise
                if attempt_number >= max_attempts:
                    reset_attempt(handle, exc, retrying=False)
                    raise ModelRetryExhaustedError(
                        attempt_number,
                        exc,
                        model=str(self.model_name),
                    ) from exc
                reset_attempt(handle, exc)
                await asyncio.sleep(
                    retry_delay(
                        attempt_number,
                        base_delay_seconds=self._retry_base_delay_seconds,
                        max_delay_seconds=self._retry_max_delay_seconds,
                    )
                )
            finally:
                _STREAM_TOOL_NAMES.reset(tool_names_token)

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type,
        base_generation_info: dict[str, Any] | None,
    ) -> ChatGenerationChunk | None:
        streamed_tool_names = _STREAM_TOOL_NAMES.get()
        normalized_chunk = (
            _deduplicate_streamed_tool_names(chunk, streamed_tool_names)
            if streamed_tool_names is not None
            else chunk
        )
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            normalized_chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None

        reasoning_content = self._extract_reasoning_content_delta(normalized_chunk)
        message = generation_chunk.message
        if reasoning_content and isinstance(message, AIMessageChunk):
            message.additional_kwargs["reasoning_content"] = reasoning_content
        if isinstance(message, AIMessageChunk) and _is_effective_chunk(message, reasoning_content):
            mark_first_token()
        return generation_chunk

    @staticmethod
    def _extract_reasoning_content_delta(chunk: dict[str, Any]) -> str:
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        if not choices:
            return ""
        delta = choices[0].get("delta")
        if not isinstance(delta, dict):
            return ""
        reasoning_content = delta.get("reasoning_content")
        return reasoning_content if isinstance(reasoning_content, str) else ""


def _is_effective_chunk(message: AIMessageChunk, reasoning_content: str) -> bool:
    if reasoning_content:
        return True
    content = message.content
    if isinstance(content, str) and content:
        return True
    if isinstance(content, list) and content:
        return True
    return bool(getattr(message, "tool_call_chunks", None))


def _is_effective_generation_chunk(chunk: ChatGenerationChunk) -> bool:
    message = chunk.message
    if not isinstance(message, AIMessageChunk):
        return bool(message.content)
    reasoning_content = message.additional_kwargs.get("reasoning_content")
    return _is_effective_chunk(
        message,
        reasoning_content if isinstance(reasoning_content, str) else "",
    )


def _chunk_finish_reason(chunk: ChatGenerationChunk) -> str | None:
    for source in (getattr(chunk, "generation_info", None), getattr(chunk.message, "response_metadata", None)):
        if isinstance(source, dict):
            value = source.get("finish_reason") or source.get("finishReason")
            if value:
                return str(value)
    return None


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    return "".join(
        item.get("text", "") if isinstance(item, dict) and isinstance(item.get("text"), str) else str(item)
        for item in value
    )


def _emit_chunk_delta(chunk: ChatGenerationChunk, handle: Any) -> None:
    message = chunk.message
    reasoning = getattr(message, "additional_kwargs", {}).get("reasoning_content", "")
    emit_attempt_delta(
        handle,
        text_delta=_content_text(getattr(message, "content", "")),
        reasoning_delta=reasoning if isinstance(reasoning, str) else "",
    )


__all__ = ["ChatOpenAICustom"]
