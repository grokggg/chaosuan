from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from src.logger import get_logger
from src.utils.conversation_progress import (
    CONVERSATION_STATUS_ERROR,
    CONVERSATION_STATUS_INTERACTION,
    MARK_TASK_ERROR_TOOL_NAME,
    TASK_ERROR_CHANGED_METADATA_KEY,
    emit_todolist_sync,
    set_conversation_status_from_runtime,
    todos_with_current_in_progress_as_interaction,
)
from src.utils.iframe_cards import iframe_event_from_tool_output
from src.utils.interactions import interaction_event_from_tool_output, parse_json_object
from src.utils.previews import PREVIEW_EVENT_TYPE, PREVIEW_TOOL_NAMES, preview_event_from_tool_output
from src.utils.streaming import CUSTOM_JOB_MONITOR, CUSTOM_TOOL_HANDOFF_FINISH
from src.utils.todolists import (
    TODOLIST_EVENT_TYPE,
    WRITE_TODOS_TOOL_NAME,
    current_in_progress_step_id,
    todolist_event,
)

logger = get_logger(__name__)
RESOURCE_CARDS_TOOL_NAME = "show_resource_cards"
RECOMMEND_RESOURCE_CARDS_TOOL_NAME = "show_recommand_resource_cards"
IFRAME_TOOL_NAME = "show_iframe"


@dataclass(frozen=True, slots=True)
class ToolHandoffPolicy:
    """Controls tool-event replacement independently from response termination."""

    event_type: str | None = None
    suppress_tool_stream: bool = False
    stop_response: bool = False
    finish_reason: str | None = None


TOOL_HANDOFF_POLICIES: dict[str, ToolHandoffPolicy] = {
    RESOURCE_CARDS_TOOL_NAME: ToolHandoffPolicy(
        event_type="interaction",
        suppress_tool_stream=True,
        stop_response=True,
        finish_reason="resource_cards",
    ),
    RECOMMEND_RESOURCE_CARDS_TOOL_NAME: ToolHandoffPolicy(
        event_type="interaction",
        suppress_tool_stream=True,
        stop_response=True,
        finish_reason="resource_cards",
    ),
    IFRAME_TOOL_NAME: ToolHandoffPolicy(
        event_type="iframe",
        suppress_tool_stream=True,
        stop_response=False,
    ),
    WRITE_TODOS_TOOL_NAME: ToolHandoffPolicy(
        event_type=TODOLIST_EVENT_TYPE,
        suppress_tool_stream=True,
    ),
    **{
        tool_name: ToolHandoffPolicy(
            event_type=PREVIEW_EVENT_TYPE,
            suppress_tool_stream=True,
        )
        for tool_name in PREVIEW_TOOL_NAMES
    },
}


def tool_handoff_policy(tool_name: Any) -> ToolHandoffPolicy | None:
    return TOOL_HANDOFF_POLICIES.get(tool_name) if isinstance(tool_name, str) else None


def suppress_tool_stream(tool_name: Any) -> bool:
    policy = tool_handoff_policy(tool_name)
    return policy.suppress_tool_stream if policy is not None else False


def extract_job_monitor_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    current: Any = payload
    for _ in range(3):
        if not isinstance(current, dict):
            return None
        if (
            current.get("asyncMonitor") is True
            and current.get("terminal") is False
            and current.get("agentAction") == "stop_response"
        ):
            return current
        current = current.get("data")
    return None


def extract_job_terminal_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    current: Any = payload
    for _ in range(3):
        if not isinstance(current, dict):
            return None
        if current.get("asyncMonitor") is False and current.get("terminal") is True:
            return current
        current = current.get("data")
    return None


def is_job_monitor(message: ToolMessage) -> bool:
    payload = parse_json_object(message.content)
    if not isinstance(payload, dict):
        return False

    return extract_job_monitor_data(payload) is not None


def is_resource_cards_handoff(message: ToolMessage) -> bool:
    policy = tool_handoff_policy(message.name)
    return policy is not None and policy.event_type == "interaction" and policy.stop_response


def _policy_event(
    policy: ToolHandoffPolicy,
    message: ToolMessage,
    state: AgentState,
    tool_call: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if policy.event_type == "iframe":
        return iframe_event_from_tool_output(message.content)
    if policy.event_type == "interaction":
        return interaction_event_from_tool_output(message.content)
    if policy.event_type == TODOLIST_EVENT_TYPE:
        if message.status == "error":
            return None
        # The tool may preserve an omitted summary. Publish committed state,
        # never rejected or incomplete model arguments.
        if isinstance(state.get("todos"), list):
            return todolist_event(state["todos"])
        tool_call_args = tool_call.get("args") if tool_call is not None else None
        if not isinstance(tool_call_args, dict):
            tool_call_args = parse_json_object(tool_call_args)
        todos = tool_call_args.get("todos") if isinstance(tool_call_args, dict) else state.get("todos")
        return todolist_event(todos)
    if policy.event_type == PREVIEW_EVENT_TYPE:
        return preview_event_from_tool_output(message.name, message.content)
    return None


def tool_sync_handoff_event(tool_sync: dict[str, Any]) -> dict[str, Any] | None:
    policy = tool_handoff_policy(tool_sync.get("name"))
    if policy is None or policy.event_type is None:
        return None
    if policy.event_type == TODOLIST_EVENT_TYPE:
        tool_input = tool_sync.get("input")
        todos = tool_input.get("todos") if isinstance(tool_input, dict) else None
        return todolist_event(todos)
    if policy.event_type == "interaction":
        return interaction_event_from_tool_output(tool_sync.get("output"))
    if policy.event_type == "iframe":
        return iframe_event_from_tool_output(tool_sync.get("output"))
    if policy.event_type == PREVIEW_EVENT_TYPE:
        return preview_event_from_tool_output(tool_sync.get("name"), tool_sync.get("output"))
    return None


def handoff_finish_reason(message: ToolMessage) -> str | None:
    if is_job_monitor(message):
        return "job_monitor"
    policy = tool_handoff_policy(message.name)
    if policy is not None and policy.stop_response:
        if policy.event_type == "interaction" and interaction_event_from_tool_output(message.content) is None:
            return None
        return policy.finish_reason
    return None


def _ordered_tool_messages(messages: list[Any]) -> list[tuple[dict[str, Any] | None, ToolMessage]]:
    latest_ai_index: int | None = None
    ordered_tool_calls: list[dict[str, Any]] = []
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage):
            return []
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue
        latest_ai_index = index
        ordered_tool_calls = list(message.tool_calls)
        break

    if latest_ai_index is None:
        last_message = messages[-1] if messages else None
        return [(None, last_message)] if isinstance(last_message, ToolMessage) else []

    results_by_call_id = {
        str(message.tool_call_id): message
        for message in messages[latest_ai_index + 1 :]
        if isinstance(message, ToolMessage) and message.tool_call_id
    }
    ordered_results: list[tuple[dict[str, Any] | None, ToolMessage]] = []
    for tool_call in ordered_tool_calls:
        tool_call_id = tool_call.get("id")
        if not tool_call_id:
            continue
        result = results_by_call_id.get(str(tool_call_id))
        if result is not None:
            ordered_results.append((tool_call, result))
    return ordered_results


def _job_monitor_event(message: ToolMessage, state: AgentState) -> dict[str, Any] | None:
    payload = parse_json_object(message.content)
    if not isinstance(payload, dict) or extract_job_monitor_data(payload) is None:
        return None
    return {
        "type": CUSTOM_JOB_MONITOR,
        "toolCallId": str(message.tool_call_id or ""),
        "toolName": str(message.name or ""),
        "output": payload,
        "taskId": current_in_progress_step_id(state.get("todos")),
    }


def _task_error_event(message: ToolMessage, state: AgentState) -> dict[str, Any] | None:
    if (
        message.name != MARK_TASK_ERROR_TOOL_NAME
        or message.additional_kwargs.get(TASK_ERROR_CHANGED_METADATA_KEY) is not True
    ):
        return None
    return todolist_event(state.get("todos"))


class ToolHandoffMiddleware(AgentMiddleware):
    def _before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = list(state.get("messages", []))
        ordered_messages = _ordered_tool_messages(messages)
        if not ordered_messages:
            return None

        writer = getattr(runtime, "stream_writer", None)
        finish_reason: str | None = None
        for tool_call, message in ordered_messages:
            if message.name == WRITE_TODOS_TOOL_NAME and message.status == "error":
                continue
            policy = tool_handoff_policy(message.name)
            custom_event = _policy_event(policy, message, state, tool_call) if policy is not None else None
            if custom_event is None:
                custom_event = _job_monitor_event(message, state)
            if custom_event is None:
                custom_event = _task_error_event(message, state)

            if policy is not None and policy.event_type is not None and custom_event is None:
                logger.warning("Tool handoff returned no custom event tool=%s", message.name)
            elif custom_event is not None:
                custom_event = {**custom_event, "toolCallId": str(message.tool_call_id or "")}
                if callable(writer):
                    writer(custom_event)
                else:
                    logger.warning("Tool handoff stream writer unavailable tool=%s", message.name)

            if message.name == MARK_TASK_ERROR_TOOL_NAME and custom_event is not None:
                set_conversation_status_from_runtime(runtime, CONVERSATION_STATUS_ERROR)

            message_finish_reason = handoff_finish_reason(message)
            if message_finish_reason is not None:
                finish_reason = message_finish_reason

        if finish_reason is None:
            return None

        state_update: dict[str, Any] = {}
        if finish_reason == "resource_cards":
            todos = todos_with_current_in_progress_as_interaction(state)
            if todos is not None:
                try:
                    emit_todolist_sync(todos, reason="resource_cards_waiting_for_interaction")
                except Exception:
                    logger.exception("Failed to emit resource cards interaction todo sync")
                set_conversation_status_from_runtime(runtime, CONVERSATION_STATUS_INTERACTION)
                state_update["todos"] = todos

        if callable(writer):
            writer({"type": CUSTOM_TOOL_HANDOFF_FINISH, "finishReason": finish_reason})
        else:
            logger.warning("Tool handoff finish stream writer unavailable finish_reason=%s", finish_reason)

        logger.info(
            "Tool handoff detected, ending current agent response before next model call finish_reason=%s",
            finish_reason,
        )
        return {**state_update, "jump_to": "end"}

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._before_model(state, runtime)

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._before_model(state, runtime)


__all__ = [
    "RESOURCE_CARDS_TOOL_NAME",
    "RECOMMEND_RESOURCE_CARDS_TOOL_NAME",
    "TOOL_HANDOFF_POLICIES",
    "ToolHandoffPolicy",
    "ToolHandoffMiddleware",
    "extract_job_monitor_data",
    "extract_job_terminal_data",
    "handoff_finish_reason",
    "is_job_monitor",
    "is_resource_cards_handoff",
    "suppress_tool_stream",
    "tool_sync_handoff_event",
    "tool_handoff_policy",
]
