from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessageChunk, ToolMessage

from src.api.routes.utils.chat_errors import (
    connection_error_text,
    is_connection_error,
    is_mcp_tool_error,
    log_model_request_error,
    stream_error_text,
    tool_error_output,
)
from src.api.routes.utils.chat_stream import (
    extract_custom_ai_message_delta,
    extract_custom_iframe,
    extract_custom_interaction,
    extract_custom_job_monitor,
    extract_custom_preview,
    extract_custom_response_finish_reason,
    extract_custom_todolist,
    extract_custom_tool_call_sync,
    extract_custom_tool_handoff_finish,
    extract_reasoning_content,
    extract_text_content,
    extract_tool_call_deltas,
    extract_tool_message_content,
    format_tool_arguments,
    resolve_tool_call_id,
    resolve_tool_record_id,
    serialize_tool_records,
    serialize_usage,
    upsert_tool_record,
)
from src.api.routes.utils.payload import parse_json_payload
from src.api.routes.utils.stream_part_ids import next_stream_part_id
from src.api.routes.utils.tool_result_events import (
    extract_job_monitor_event,
    extract_job_terminal_notice,
)
from src.api.session_store import append_session_message, mark_next_user_message_hidden, update_session_status
from src.errors import ErrorInfo, classify_mcp_error
from src.errors.catalog import MODEL_RETRY_EXHAUSTED, SOURCE_MODEL
from src.llm.retry import ModelRetryExhaustedError
from src.logger import get_logger
from src.middleware.plan_first_middleware import PLAN_TOOL_DECISION, PLAN_TOOL_REJECTED, PLAN_TOOL_ROUND
from src.middleware.tool_handoff_middleware import (
    handoff_finish_reason,
    is_job_monitor,
    suppress_tool_stream,
    tool_sync_handoff_event,
)
from src.utils.retry_progress import build_retry_event
from src.utils.todolists import TODOLIST_ID_TYPE
from src.utils.tool_call_ids import public_tool_call_id

logger = get_logger(__name__)
JOB_MONITOR_TRIGGERED_OUTPUT = "异步作业监控已触发"
PATCH_TOOL_CALLS_BEFORE_AGENT_NODE = "PatchToolCallsMiddleware.before_agent"
TOOL_ARGUMENTS_INTERRUPTED_INPUT = "工具参数生成过程中断，未形成有效工具输入。"
TOOL_ARGUMENTS_INTERRUPTED_OUTPUT = "工具参数生成过程中断，工具未进入执行阶段。"
TOOL_EXECUTION_INTERRUPTED_OUTPUT = "工具调用因连接中断而终止，无法确认工具是否已经执行完成。"


def _metadata_has_lc_source(value: Any, expected: str) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("lc_source") == expected:
        return True
    return any(
        isinstance(value.get(key), dict) and _metadata_has_lc_source(value[key], expected)
        for key in ("metadata", "config", "kwargs")
    )


def _is_internal_summarization_message(message: Any, metadata: Any) -> bool:
    if _metadata_has_lc_source(metadata, "summarization"):
        return True
    return any(
        _metadata_has_lc_source(payload, "summarization")
        for payload in (
            getattr(message, "additional_kwargs", None),
            getattr(message, "response_metadata", None),
        )
    )


def _is_internal_summarization_attempt(event: Any) -> bool:
    return isinstance(event, dict) and event.get("lcSource") == "summarization"


def _is_patch_tool_calls_state_message(metadata: Any) -> bool:
    """Exclude full-history rewrites used only to repair dangling tool calls."""
    return (
        isinstance(metadata, dict)
        and metadata.get("langgraph_node") == PATCH_TOOL_CALLS_BEFORE_AGENT_NODE
    )


def _unpack_stream_part(part: Any) -> tuple[Any, Any] | None:
    if isinstance(part, dict):
        return part.get("type"), part.get("data")
    if isinstance(part, tuple) and len(part) == 2:
        return part
    return None


def _tool_arguments_complete(arguments: Any) -> bool:
    if not isinstance(arguments, str) or not arguments.strip():
        return False
    try:
        parsed = json.loads(arguments)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(parsed, dict)


class ChatStreamProcessor:
    """Translate LangGraph stream parts while owning one chat run's mutable state."""

    def __init__(
        self,
        *,
        user_id: str,
        conversation_id: str,
        model_name: str,
        part_id_factory: Callable[[str, str, str], Awaitable[str]] = next_stream_part_id,
        session_message_writer: Callable[[str, str, dict[str, Any]], None] = append_session_message,
        hide_next_user_message: Callable[[str, str], None] = mark_next_user_message_hidden,
    ) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.model_name = model_name
        self._part_id_factory = part_id_factory
        self._session_message_writer = session_message_writer
        self._hide_next_user_message = hide_next_user_message
        self._current_attempt_id: str | None = None
        self._committed_attempt_id: str | None = None
        self._retry_info: dict[str, int] = {}
        self._retry_event_id: str | None = None
        self._operation_retry_event_ids: dict[str, str] = {}
        self._attempt_start_reasoning_id: str | None = None
        self._attempt_start_text_id: str | None = None
        self._attempt_reasoning: list[str] = []
        self._attempt_text: list[str] = []

        self.reasoning_id: str | None = None
        self.text_id: str | None = None
        self.model_reply_logged = False
        self.logged_tool_calls: set[str] = set()
        self.logged_complete_tool_calls: set[str] = set()
        self.tool_call_buffers: dict[str, dict[str, str]] = {}
        self.tool_call_ids_by_index: dict[int, str] = {}
        self.tool_streams: dict[str, dict[str, Any]] = {}
        self.tool_part_ids: dict[str, str] = {}
        self.session_tool_records: dict[str, dict[str, Any]] = {}
        self.session_tool_order: list[str] = []
        self.flushed_tool_result_ids: set[str] = set()
        self.handled_handoff_tool_call_ids: set[str] = set()
        self.handled_terminal_notice_tool_call_ids: set[str] = set()
        self.reasoning_parts: list[str] = []
        self.text_parts: list[str] = []
        self.latest_usage: dict[str, Any] | None = None
        self.summarization_chunks_filtered = 0
        self.patch_tool_call_messages_filtered = 0
        self.reasoning_active = False
        self.text_active = False
        self.finish_reason = "stop"
        self.handoff_hidden_marked = False
        self.interruption_finalized = False
        self.latest_todolist_status: str | None = None
        # Science tool chunks wait for the model-round policy decision. This
        # prevents rejected calls from ever becoming UI cards or history records.
        self._plan_tool_chunks: dict[str, list[dict[str, Any]]] = {}
        self._plan_tool_allowed: dict[str, set[str]] = {}
        self._plan_tool_indexes: dict[str, dict[int, str]] = {}
        self._plan_tool_rejected: set[str] = set()

    async def handle_part(self, part: Any) -> AsyncIterator[dict[str, Any]]:
        unpacked = _unpack_stream_part(part)
        if unpacked is None:
            return
        part_type, part_data = unpacked
        if part_type == "custom":
            async for event in self._handle_custom(part_data):
                yield event
        elif part_type == "messages":
            async for event in self._handle_messages(part_data):
                yield event

    async def _handle_custom(self, part_data: Any) -> AsyncIterator[dict[str, Any]]:
        if isinstance(part_data, dict):
            attempt_type = part_data.get("type")
            if attempt_type == PLAN_TOOL_DECISION:
                round_id = part_data["roundId"]
                self._plan_tool_allowed[round_id] = set(part_data["allowedToolCallIds"])
                self._plan_tool_rejected.update(part_data.get("rejectedToolCallIds", []))
                for tool_call in self._plan_tool_chunks.pop(round_id, []):
                    for event in await self._handle_plan_tool_chunk(round_id, tool_call):
                        yield event
                return
            if isinstance(attempt_type, str) and attempt_type.startswith("model-attempt-"):
                if _is_internal_summarization_attempt(part_data):
                    self.summarization_chunks_filtered += 1
                    if self.summarization_chunks_filtered == 1:
                        logger.info(
                            "Internal summarization attempt stream detected and filtered conversation_id=%s",
                            self.conversation_id,
                        )
                    return
                for event in await self._handle_model_attempt_event(part_data):
                    yield event
                return
            if attempt_type == "retry-progress":
                retry_event = await self._handle_retry_progress_event(part_data)
                if retry_event is not None:
                    yield retry_event
                return

        handoff_tool_call_id = (
            str(part_data.get("toolCallId") or "") if isinstance(part_data, dict) else ""
        )
        tool_handoff_finish = extract_custom_tool_handoff_finish(part_data)
        if tool_handoff_finish:
            self._apply_handoff_finish_reason(tool_handoff_finish)
            return

        response_finish_reason = extract_custom_response_finish_reason(part_data)
        if response_finish_reason:
            self.finish_reason = response_finish_reason
            return

        job_monitor = extract_custom_job_monitor(part_data)
        if job_monitor:
            async for event in self._handle_job_monitor(job_monitor):
                yield event
            return

        interaction = extract_custom_interaction(part_data)
        if interaction:
            async for event in self._persist_custom_event(
                interaction,
                part_type="interaction",
                handoff_tool_call_id=handoff_tool_call_id,
            ):
                yield event
            return

        tool_sync = extract_custom_tool_call_sync(part_data)
        iframe = extract_custom_iframe(part_data)
        if iframe is None and tool_sync is not None:
            iframe = extract_custom_iframe(tool_sync_handoff_event(tool_sync))
        if iframe:
            async for event in self._persist_custom_event(
                iframe,
                part_type="iframe",
                handoff_tool_call_id=handoff_tool_call_id,
            ):
                yield event
            return

        todolist = extract_custom_todolist(part_data)
        if todolist is None and tool_sync is not None:
            todolist = extract_custom_todolist(tool_sync_handoff_event(tool_sync))
        if todolist:
            async for event in self._persist_custom_event(
                todolist,
                part_type=TODOLIST_ID_TYPE,
                handoff_tool_call_id=handoff_tool_call_id,
            ):
                yield event
            return

        preview = extract_custom_preview(part_data)
        if preview is None and tool_sync is not None:
            preview = extract_custom_preview(tool_sync_handoff_event(tool_sync))
        if preview:
            async for event in self._persist_custom_event(
                preview,
                part_type="preview",
                handoff_tool_call_id=handoff_tool_call_id,
            ):
                yield event
            return

        if tool_sync:
            for event in await self._handle_tool_sync(tool_sync):
                yield event
            return

        text = extract_custom_ai_message_delta(part_data)
        if text and self._committed_attempt_id is None:
            for event in await self._append_text(text, log_model_reply=False):
                yield event

    async def _handle_retry_progress_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        operation_id = str(event.get("operationId") or "").strip()
        retry_count = event.get("retryCount")
        max_retries = event.get("maxRetries")
        if (
            not operation_id
            or not isinstance(retry_count, int)
            or isinstance(retry_count, bool)
            or not isinstance(max_retries, int)
            or isinstance(max_retries, bool)
            or retry_count < 1
            or max_retries < retry_count
        ):
            return None
        event_id = self._operation_retry_event_ids.get(operation_id)
        if event_id is None:
            event_id = await self._part_id_factory(
                self.user_id,
                self.conversation_id,
                "model-retry",
            )
            self._operation_retry_event_ids[operation_id] = event_id
        return build_retry_event(
            event_id=event_id,
            retry_id=None,
            retry_count=retry_count,
            max_retries=max_retries,
        )

    async def _handle_model_attempt_event(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        event_type = str(event.get("type") or "")
        attempt_id = str(event.get("attemptId") or "")
        if event_type == "model-attempt-start":
            events = self.close_content()
            self._current_attempt_id = attempt_id
            self._committed_attempt_id = None
            if event.get("attemptNumber") == 1:
                self._retry_event_id = None
            self._attempt_start_reasoning_id = self.reasoning_id
            self._attempt_start_text_id = self.text_id
            self._attempt_reasoning.clear()
            self._attempt_text.clear()
            attempt_number = event.get("attemptNumber")
            max_attempts = event.get("maxAttempts")
            if (
                isinstance(attempt_number, int)
                and not isinstance(attempt_number, bool)
                and isinstance(max_attempts, int)
                and not isinstance(max_attempts, bool)
            ):
                self._retry_info = {
                    "retryCount": max(0, attempt_number - 1),
                    "maxRetries": max(0, max_attempts - 1),
                }
            return events
        if not attempt_id or attempt_id != self._current_attempt_id:
            return []
        if event_type == "model-attempt-delta":
            events: list[dict[str, Any]] = []
            reasoning_delta = event.get("reasoningDelta")
            if isinstance(reasoning_delta, str) and reasoning_delta:
                self._attempt_reasoning.append(reasoning_delta)
                events.extend(await self._append_reasoning(reasoning_delta, persist=False))
            text_delta = event.get("textDelta")
            if isinstance(text_delta, str) and text_delta:
                self._attempt_text.append(text_delta)
                events.extend(await self._append_text(text_delta, log_model_reply=True, persist=False))
            return events
        if event_type == "model-attempt-reset":
            self._committed_attempt_id = None
            retrying = event.get("retrying") is True
            self._attempt_reasoning.clear()
            self._attempt_text.clear()
            events = self.close_content()
            rolled_back_ids: list[str] = []
            if self.reasoning_id is not None and self.reasoning_id != self._attempt_start_reasoning_id:
                rolled_back_ids.append(self.reasoning_id)
            if self.text_id is not None and self.text_id != self._attempt_start_text_id:
                rolled_back_ids.append(self.text_id)
            if retrying or rolled_back_ids:
                if self._retry_event_id is None:
                    self._retry_event_id = await self._part_id_factory(
                        self.user_id,
                        self.conversation_id,
                        "model-retry",
                    )
                retry_event = build_retry_event(
                    event_id=self._retry_event_id,
                    retry_id=None,
                )
                if retrying:
                    retry_event.update(
                        {
                            "retryCount": self._retry_info.get("retryCount", 0) + 1,
                            "maxRetries": self._retry_info.get("maxRetries", 0),
                        }
                    )
                if not rolled_back_ids:
                    events.append(
                        {
                            **retry_event,
                            "retryId": None,
                        }
                    )
                else:
                    for part_id in rolled_back_ids:
                        events.append(
                            {
                                **retry_event,
                                "retryId": part_id,
                            }
                        )
            self._current_attempt_id = None
            self._retry_info = {}
            if not retrying:
                self._retry_event_id = None
            return events
        if event_type == "model-attempt-commit":
            self._committed_attempt_id = attempt_id
            self._adopt_attempt_content()
            self._current_attempt_id = None
            self._retry_info = {}
            self._retry_event_id = None
        return []

    def _adopt_attempt_content(self) -> None:
        if self._attempt_reasoning:
            self.reasoning_parts.extend(self._attempt_reasoning)
            self._attempt_reasoning.clear()
        if self._attempt_text:
            self.text_parts.extend(self._attempt_text)
            self._attempt_text.clear()

    async def _handle_job_monitor(
        self,
        monitor: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        tool_call_id = monitor["toolCallId"]
        if tool_call_id in self.handled_handoff_tool_call_ids:
            return
        for event in self.close_content():
            yield event

        tool_name = monitor["toolName"]
        record_id = resolve_tool_record_id(
            self.session_tool_records,
            tool_call_id,
            name=tool_name,
        )
        record = upsert_tool_record(
            self.session_tool_records,
            self.session_tool_order,
            record_id,
            name=tool_name,
            result=json.dumps(monitor["output"], ensure_ascii=False),
        )
        event = extract_job_monitor_event(
            conversation_id=self.conversation_id,
            tool_result=monitor["output"],
            tool_record=record,
            task_id=monitor.get("taskId"),
        )
        if event:
            event = {
                **event,
                "id": await self._part_id_factory(
                    self.user_id,
                    self.conversation_id,
                    "job",
                ),
            }
            self.handled_handoff_tool_call_ids.add(tool_call_id)
            self._persist_assistant_event(event)
            yield event
        else:
            logger.warning(
                "Job monitor event could not be converted tool=%s tool_call_id=%s",
                tool_name,
                tool_call_id,
            )

    async def _persist_custom_event(
        self,
        event: dict[str, Any],
        *,
        part_type: str,
        handoff_tool_call_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        if handoff_tool_call_id and handoff_tool_call_id in self.handled_handoff_tool_call_ids:
            return
        for close_event in self.close_content():
            yield close_event

        if part_type == TODOLIST_ID_TYPE:
            self.latest_todolist_status = event["resource"].get("status")

        event_id = event.get("id")
        if isinstance(event_id, str) and event_id.strip():
            part_id = event_id.strip()
        elif part_type in {"preview", "interaction", "iframe"}:
            # 卡片 id 需要全局唯一：跨会话复用序号会撞车
            part_id = f"{part_type}_{uuid4().hex}"
        else:
            part_id = await self._part_id_factory(self.user_id, self.conversation_id, part_type)
        persisted_event = {**event, "id": part_id}
        if handoff_tool_call_id:
            self.handled_handoff_tool_call_ids.add(handoff_tool_call_id)
        self._persist_assistant_event(persisted_event)
        yield persisted_event

    async def _handle_tool_sync(self, tool_sync: dict[str, Any]) -> list[dict[str, Any]]:
        tool_call_id = str(tool_sync.get("toolCallId") or "")
        exposed_tool_call_id = public_tool_call_id(tool_call_id)
        tool_name = str(tool_sync.get("name") or "tool")
        if suppress_tool_stream(tool_name):
            return []

        events = self.close_content()
        part_id = await self._tool_part_id(tool_call_id)
        stored_tool_sync = {
            **tool_sync,
            "toolCallId": exposed_tool_call_id,
        }
        self._session_message_writer(
            self.user_id,
            self.conversation_id,
            {"role": "assistant", "id": part_id, "type": "tool", "tool": stored_tool_sync},
        )
        tool_input = tool_sync.get("input")
        input_text = (
            tool_input
            if isinstance(tool_input, str)
            else json.dumps(tool_input, ensure_ascii=False, default=str)
        )
        events.append(
            {
                "type": "tool-input-start",
                "id": part_id,
                "toolCallId": exposed_tool_call_id,
                "toolName": tool_name,
            }
        )
        if input_text:
            events.append(
                {
                    "type": "tool-input-delta",
                    "id": part_id,
                    "toolCallId": exposed_tool_call_id,
                    "inputTextDelta": input_text,
                }
            )
        available_event: dict[str, Any] = {
            "type": "tool-input-available",
            "id": part_id,
            "toolCallId": exposed_tool_call_id,
            "toolName": tool_name,
            "input": tool_input,
        }
        if tool_sync.get("toolCallDescription"):
            available_event["toolCallDescription"] = tool_sync["toolCallDescription"]
        events.extend(
            [
                available_event,
                {
                    "type": "tool-output-available",
                    "id": part_id,
                    "toolCallId": exposed_tool_call_id,
                    "toolName": tool_name,
                    "output": str(tool_sync.get("output") or ""),
                },
            ]
        )
        return events

    async def _handle_messages(self, part_data: Any) -> AsyncIterator[dict[str, Any]]:
        if not isinstance(part_data, tuple) or len(part_data) != 2:
            return
        message, metadata = part_data
        if not isinstance(metadata, dict):
            metadata = {}

        if _is_internal_summarization_message(message, metadata):
            self.summarization_chunks_filtered += 1
            if self.summarization_chunks_filtered == 1:
                logger.info(
                    "Internal summarization stream detected and filtered conversation_id=%s metadata_keys=%s",
                    self.conversation_id,
                    sorted(metadata),
                )
            return

        if _is_patch_tool_calls_state_message(metadata):
            self.patch_tool_call_messages_filtered += 1
            if self.patch_tool_call_messages_filtered == 1:
                logger.info(
                    "PatchToolCallsMiddleware state messages detected and filtered "
                    "conversation_id=%s",
                    self.conversation_id,
                )
            return

        if isinstance(message, ToolMessage):
            for event in await self._handle_tool_message(message):
                yield event
            return
        if isinstance(message, AIMessageChunk):
            async for event in self._handle_ai_message(message, plan_round=metadata.get(PLAN_TOOL_ROUND)):
                yield event

    async def _handle_tool_message(self, message: ToolMessage) -> list[dict[str, Any]]:
        if (message.additional_kwargs.get(PLAN_TOOL_REJECTED)
                or message.tool_call_id in self._plan_tool_rejected):
            return []
        events = self.close_content()
        is_job_monitor_result = is_job_monitor(message)
        tool_finish_reason = handoff_finish_reason(message)
        if tool_finish_reason:
            self._apply_handoff_finish_reason(tool_finish_reason)

        tool_call_id = str(message.tool_call_id or message.name or "unknown")
        tool_result = extract_tool_message_content(message)
        record_id = resolve_tool_record_id(
            self.session_tool_records,
            tool_call_id,
            name=message.name,
        )
        if is_job_monitor_result:
            record = upsert_tool_record(
                self.session_tool_records,
                self.session_tool_order,
                record_id,
                name=message.name,
                result=JOB_MONITOR_TRIGGERED_OUTPUT,
            )
            self._log_complete_tool_call(record_id, message.name)
            await self.flush_tool_result(record_id)
            events.extend(self.tool_input_events(record_id, force_available=True))
            events.append(
                {
                    "type": "tool-output-available",
                    "id": await self._tool_part_id(record_id),
                    "toolCallId": public_tool_call_id(record_id),
                    "toolName": record.get("name") or message.name or "tool",
                    "output": JOB_MONITOR_TRIGGERED_OUTPUT,
                }
            )
            return events
        if suppress_tool_stream(message.name):
            terminal_notice = await self._job_terminal_notice_event(
                tool_call_id,
                tool_result,
                self.session_tool_records.get(record_id),
            )
            if terminal_notice is not None:
                events.append(terminal_notice)
            return events

        record = upsert_tool_record(
            self.session_tool_records,
            self.session_tool_order,
            record_id,
            name=message.name,
            result=tool_result,
        )
        part_id = await self._tool_part_id(record_id)
        self._log_complete_tool_call(record_id, message.name)
        await self.flush_tool_result(record_id)
        events.extend(self.tool_input_events(record_id, force_available=True))
        events.append(
            {
                "type": "tool-output-available",
                "id": part_id,
                "toolCallId": public_tool_call_id(record_id),
                "toolName": record.get("name") or message.name or "tool",
                "output": tool_result,
            }
        )
        terminal_notice = await self._job_terminal_notice_event(tool_call_id, tool_result, record)
        if terminal_notice is not None:
            events.append(terminal_notice)
        return events

    async def _job_terminal_notice_event(
        self,
        tool_call_id: str,
        tool_result: str,
        tool_record: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if tool_call_id in self.handled_terminal_notice_tool_call_ids:
            return None

        notice = extract_job_terminal_notice(
            conversation_id=self.conversation_id,
            tool_result=tool_result,
            tool_record=tool_record,
        )
        if notice is None:
            return None

        notice = {
            **notice,
            "id": await self._part_id_factory(
                self.user_id,
                self.conversation_id,
                "job_terminal_notice",
            ),
        }
        self._session_message_writer(
            self.user_id,
            self.conversation_id,
            {"role": "assistant", **notice},
        )
        self.handled_terminal_notice_tool_call_ids.add(tool_call_id)
        return notice

    async def _handle_ai_message(
        self, message: AIMessageChunk, *, plan_round: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        finish_reason = message.response_metadata.get("finish_reason")
        usage = serialize_usage(getattr(message, "usage_metadata", None))
        if usage is None:
            usage = serialize_usage(getattr(message, "response_metadata", {}).get("token_usage"))
        if usage:
            self.latest_usage = usage

        reasoning_text = extract_reasoning_content(message)
        if reasoning_text and self._committed_attempt_id is None:
            for event in await self._append_reasoning(reasoning_text):
                yield event

        text = extract_text_content(message)
        if text and self._committed_attempt_id is None:
            for event in await self._append_text(text, log_model_reply=True):
                yield event

        tool_calls = extract_tool_call_deltas(message)
        if tool_calls:
            for event in self.close_content():
                yield event
            for tool_call in tool_calls:
                events = (await self._handle_plan_tool_chunk(plan_round, tool_call) if plan_round
                          else await self._record_tool_call_delta(tool_call))
                for event in events:
                    yield event

        if finish_reason:
            self._committed_attempt_id = None
            for record_id in self.pending_tool_ids():
                for event in self.tool_input_events(record_id, force_available=True):
                    yield event

        self.finish_reason = finish_reason or self.finish_reason

    async def _handle_plan_tool_chunk(self, round_id: str, tool_call: dict[str, Any]) -> list[dict[str, Any]]:
        if round_id not in self._plan_tool_allowed:
            self._plan_tool_chunks.setdefault(round_id, []).append(tool_call)
            return []
        call_id = resolve_tool_call_id(tool_call, self._plan_tool_indexes.setdefault(round_id, {}))
        if call_id not in self._plan_tool_allowed[round_id]:
            return []
        return await self._record_tool_call_delta({**tool_call, "id": call_id})

    async def _append_reasoning(self, text: str, *, persist: bool = True) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self.text_active:
            text_end = self.close_text_event()
            if text_end:
                events.append(text_end)
            self.flush_text()
        if not self.reasoning_active:
            self.reasoning_active = True
            self.reasoning_id = await self._part_id_factory(
                self.user_id,
                self.conversation_id,
                "reasoning",
            )
            events.append({"type": "reasoning-start", "id": self.reasoning_id})
        if persist:
            self.reasoning_parts.append(text)
        events.append({"type": "reasoning-delta", "id": self.reasoning_id, "delta": text})
        return events

    async def _append_text(
        self,
        text: str,
        *,
        log_model_reply: bool,
        persist: bool = True,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        reasoning_end = self.close_reasoning_event()
        if reasoning_end:
            events.append(reasoning_end)
        self.flush_reasoning()
        if not self.text_active:
            self.text_active = True
            self.text_id = await self._part_id_factory(
                self.user_id,
                self.conversation_id,
                "text",
            )
            events.append({"type": "text-start", "id": self.text_id})
        if persist:
            self.text_parts.append(text)
        if log_model_reply and not self.model_reply_logged:
            self.model_reply_logged = True
            logger.info("Model is replying model=%s", self.model_name)
        events.append({"type": "text-delta", "id": self.text_id, "delta": text})
        return events

    async def _record_tool_call_delta(self, tool_call: dict[str, Any]) -> list[dict[str, Any]]:
        call_id = resolve_tool_call_id(tool_call, self.tool_call_ids_by_index)
        function_payload = tool_call.get("function", {})
        tool_name = function_payload.get("name")
        tool_args = function_payload.get("arguments")
        if tool_name is None and tool_args is None:
            return []
        record = upsert_tool_record(
            self.session_tool_records,
            self.session_tool_order,
            call_id,
            name=str(tool_name) if tool_name is not None else None,
            arguments_delta=str(tool_args) if tool_args is not None else None,
        )
        buffered_call = self.tool_call_buffers.setdefault(call_id, {})
        if tool_name is not None:
            buffered_call["name"] = str(tool_name)
        if tool_args is not None:
            buffered_call["args"] = buffered_call.get("args", "") + str(tool_args)
        if call_id not in self.logged_tool_calls and "name" in buffered_call and "args" in buffered_call:
            self.logged_tool_calls.add(call_id)
            logger.info(
                "Tool call requested tool=%s args=%s",
                buffered_call["name"],
                buffered_call["args"] or "{}",
            )
        resolved_name = record.get("name")
        if resolved_name and not suppress_tool_stream(resolved_name):
            await self._tool_part_id(call_id)
            return self.tool_input_events(
                call_id,
                force_available=_tool_arguments_complete(record.get("arguments")),
            )
        return []

    async def handle_error(self, exc: Exception) -> AsyncIterator[dict[str, Any]]:
        log_model_request_error(
            logger,
            exc,
            conversation_id=self.conversation_id,
            model_name=self.model_name,
        )
        if isinstance(exc, ModelRetryExhaustedError):
            error_info = ErrorInfo.of(
                MODEL_RETRY_EXHAUSTED,
                source=SOURCE_MODEL,
                stage="chat_stream",
            )
            details = {
                "type": "upstream_model_error",
                "attempts": exc.actual_attempts,
                "message": error_info.message,
            }
            await self.persist_error(error_info.message)
            yield {"type": "error", "errorText": error_info.message, "error": details}
            return
        pending_tool_ids = self.pending_tool_ids()
        if pending_tool_ids:
            record_id = pending_tool_ids[-1]
            record = self.session_tool_records.get(record_id) or {}
            logger.exception("Tool call failed tool=%s", record.get("name") or record_id)
            if is_mcp_tool_error(exc):
                logger.warning(
                    "MCP tool call failed tool=%s error_code=%s",
                    record.get("name") or record_id,
                    classify_mcp_error(exc, stage="tool_execute").error_code,
                )
            tool_result = tool_error_output(exc, tool_name=record.get("name"))
            record = upsert_tool_record(
                self.session_tool_records,
                self.session_tool_order,
                record_id,
                result=tool_result,
            )
            await self.flush_tool_result(record_id)
            for event in self.tool_input_events(record_id, force_available=True):
                yield event
            yield {
                "type": "tool-output-available",
                "id": await self._tool_part_id(record_id),
                "toolCallId": public_tool_call_id(record_id),
                "toolName": record.get("name") or "tool",
                "output": tool_result,
            }
            error_text = f"Tool {record.get('name') or 'tool'} ({record_id}) failed: {stream_error_text(exc)}"
        elif is_connection_error(exc):
            logger.exception("Chat stream model connection failed")
            error_text = connection_error_text(exc)
        else:
            logger.exception("Chat stream failed")
            error_text = stream_error_text(exc)

        await self.persist_error(error_text)
        yield {"type": "error", "errorText": error_text}

    def close_reasoning_event(self) -> dict[str, Any] | None:
        if not self.reasoning_active:
            return None
        self.reasoning_active = False
        if self.reasoning_id is None:
            return None
        return {"type": "reasoning-end", "id": self.reasoning_id}

    def close_text_event(self) -> dict[str, Any] | None:
        if not self.text_active:
            return None
        self.text_active = False
        if self.text_id is None:
            return None
        payload: dict[str, Any] = {"type": "text-end", "id": self.text_id}
        if self.latest_usage:
            payload.update(self.latest_usage)
            self.latest_usage = None
        return payload

    def close_content(self) -> list[dict[str, Any]]:
        self._adopt_attempt_content()
        events = [
            event
            for event in (self.close_reasoning_event(), self.close_text_event())
            if event is not None
        ]
        self.flush()
        return events

    def finish_events(self) -> list[dict[str, Any]]:
        self._adopt_attempt_content()
        return [
            event
            for event in (self.close_reasoning_event(), self.close_text_event())
            if event is not None
        ]

    def complete_session(self) -> None:
        """Finish a successful plan after all response content has been persisted."""
        self.flush()
        if (
            self.finish_reason == "stop"
            and self.latest_todolist_status == "completed"
            and not self.pending_tool_ids()
        ):
            update_session_status(self.user_id, self.conversation_id, "completed")

    def finalize_approval_pause(self) -> list[dict[str, Any]]:
        """Close visible tool cards while their graph tool calls wait for approval."""
        events = self.finish_events()
        self.flush()
        for record_id in self.pending_tool_ids():
            stream = self.tool_streams.get(record_id)
            part_id = self.tool_part_ids.get(record_id)
            if not stream or not stream.get("started") or part_id is None:
                continue
            events.extend(self.tool_input_events(record_id, force_available=True))
            output = "等待用户确认，命令尚未执行。"
            record = upsert_tool_record(
                self.session_tool_records,
                self.session_tool_order,
                record_id,
                result=output,
            )
            self._persist_tool_result(record_id, part_id)
            events.append({
                "type": "tool-output-available",
                "id": part_id,
                "toolCallId": public_tool_call_id(record_id),
                "toolName": record.get("name") or "tool",
                "output": output,
            })
        return events

    def finalize_interruption(self) -> list[dict[str, Any]]:
        """Close display-only stream parts and persist interrupted tools to session history."""
        if self.interruption_finalized:
            return []
        self.interruption_finalized = True

        events = self.finish_events()
        self.flush()
        for record_id in self.pending_tool_ids():
            stream = self.tool_streams.get(record_id)
            part_id = self.tool_part_ids.get(record_id)
            if not stream or not stream.get("started") or part_id is None:
                continue

            input_was_available = bool(stream.get("available"))
            if not input_was_available:
                self.session_tool_records[record_id]["arguments"] = TOOL_ARGUMENTS_INTERRUPTED_INPUT
            events.extend(self.tool_input_events(record_id, force_available=True))
            output = (
                TOOL_EXECUTION_INTERRUPTED_OUTPUT
                if input_was_available
                else TOOL_ARGUMENTS_INTERRUPTED_OUTPUT
            )
            record = upsert_tool_record(
                self.session_tool_records,
                self.session_tool_order,
                record_id,
                result=output,
            )
            self._persist_tool_result(record_id, part_id)
            events.append(
                {
                    "type": "tool-output-available",
                    "id": part_id,
                    "toolCallId": public_tool_call_id(record_id),
                    "toolName": record.get("name") or "tool",
                    "output": output,
                }
            )
        return events

    def flush(self) -> None:
        self.flush_reasoning()
        self.flush_text()

    def flush_reasoning(self) -> None:
        if not self.reasoning_parts or self.reasoning_id is None:
            return
        self._session_message_writer(
            self.user_id,
            self.conversation_id,
            {
                "role": "assistant",
                "id": self.reasoning_id,
                "type": "reasoning",
                "reasoning": "".join(self.reasoning_parts),
            },
        )
        self.reasoning_parts.clear()

    def flush_text(self) -> None:
        if not self.text_parts or self.text_id is None:
            return
        self._session_message_writer(
            self.user_id,
            self.conversation_id,
            {
                "role": "assistant",
                "id": self.text_id,
                "type": "text",
                "text": "".join(self.text_parts),
            },
        )
        self.text_parts.clear()

    async def flush_tool_result(self, record_id: str) -> None:
        self._persist_tool_result(record_id, await self._tool_part_id(record_id))

    def _persist_tool_result(self, record_id: str, part_id: str) -> None:
        if record_id in self.flushed_tool_result_ids:
            return
        self._persist_tool_snapshot(record_id, part_id)
        self.flushed_tool_result_ids.add(record_id)

    def _persist_tool_snapshot(self, record_id: str, part_id: str) -> None:
        tool_payload = serialize_tool_records(self.session_tool_records, [record_id])
        if not tool_payload:
            return
        stored_tool_payload = {
            **tool_payload[0],
            "toolCallId": public_tool_call_id(tool_payload[0].get("toolCallId")),
        }
        self._session_message_writer(
            self.user_id,
            self.conversation_id,
            {
                "role": "assistant",
                "id": part_id,
                "type": "tool",
                "tool": stored_tool_payload,
            },
        )

    async def _tool_part_id(self, tool_call_id: str) -> str:
        part_id = self.tool_part_ids.get(tool_call_id)
        if part_id is None:
            part_id = await self._part_id_factory(
                self.user_id,
                self.conversation_id,
                "tool",
            )
            self.tool_part_ids[tool_call_id] = part_id
        return part_id

    def tool_input_events(
        self,
        record_id: str,
        *,
        force_available: bool = False,
    ) -> list[dict[str, Any]]:
        record = self.session_tool_records.get(record_id)
        if not record:
            return []
        name = record.get("name") or "tool"
        part_id = self.tool_part_ids.get(record_id)
        if part_id is None:
            return []
        raw_arguments = record.get("arguments") or ""
        stream = self.tool_streams.setdefault(
            record_id,
            {"started": False, "available": False, "sent_arguments_length": 0},
        )
        events: list[dict[str, Any]] = []
        if not stream["started"]:
            stream["started"] = True
            # Match the visible card's position even when parallel tool arguments
            # finish arriving in a different order.
            self._persist_tool_snapshot(record_id, part_id)
            events.append(
                {
                    "type": "tool-input-start",
                    "id": part_id,
                    "toolCallId": public_tool_call_id(record_id),
                    "toolName": name,
                }
            )

        sent_length = int(stream["sent_arguments_length"])
        raw_arguments_text = str(raw_arguments)
        if len(raw_arguments_text) > sent_length:
            stream["sent_arguments_length"] = len(raw_arguments_text)
            events.append(
                {
                    "type": "tool-input-delta",
                    "id": part_id,
                    "toolCallId": public_tool_call_id(record_id),
                    "inputTextDelta": raw_arguments_text[sent_length:],
                }
            )

        if force_available and not stream["available"]:
            arguments, description = format_tool_arguments(
                raw_arguments_text,
                tool_name=name,
            )
            if description:
                record["description"] = description
            stream["available"] = True
            available_event: dict[str, Any] = {
                "type": "tool-input-available",
                "id": part_id,
                "toolCallId": public_tool_call_id(record_id),
                "toolName": name,
                "input": parse_json_payload(arguments),
            }
            if description:
                available_event["toolCallDescription"] = description
            if record.get("result") is None:
                self._persist_tool_snapshot(record_id, part_id)
            events.append(available_event)
        return events

    def pending_tool_ids(self) -> list[str]:
        return [
            record_id
            for record_id in self.session_tool_order
            if self.session_tool_records.get(record_id, {}).get("result") is None
            and not suppress_tool_stream(self.session_tool_records.get(record_id, {}).get("name"))
        ]

    async def persist_error(self, error_text: str) -> None:
        try:
            error_id = await self._part_id_factory(self.user_id, self.conversation_id, "error")
            self._session_message_writer(
                self.user_id,
                self.conversation_id,
                {
                    "role": "assistant",
                    "id": error_id,
                    "type": "error",
                    "error": {"errorText": error_text},
                },
            )
        except Exception:
            logger.exception("Failed to persist chat stream error")

    def _apply_handoff_finish_reason(self, value: str) -> None:
        self.finish_reason = value
        if self.handoff_hidden_marked:
            return
        self._hide_next_user_message(self.user_id, self.conversation_id)
        self.handoff_hidden_marked = True

    def _log_complete_tool_call(self, record_id: str, fallback_name: str | None = None) -> None:
        if record_id in self.logged_complete_tool_calls:
            return
        record = self.session_tool_records.get(record_id)
        if not record:
            return
        self.logged_complete_tool_calls.add(record_id)
        logger.info(
            "Tool call complete tool=%s args=%s",
            record.get("name") or fallback_name or "-",
            record.get("arguments") or "{}",
        )

    def _persist_assistant_event(self, event: dict[str, Any]) -> None:
        self._session_message_writer(
            self.user_id,
            self.conversation_id,
            {"role": "assistant", **event},
        )


__all__ = ["ChatStreamProcessor"]
