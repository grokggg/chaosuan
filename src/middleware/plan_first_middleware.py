"""Require a committed scientific plan before exposing or executing business tools."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelCallResult,
    ModelRequest,
    ToolCallRequest,
)
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command
from pydantic import ValidationError

from src.agents.write_todos import ExtendedWriteTodosInput

PLAN_TOOL_ROUND = "science_plan_tool_round"
PLAN_TOOL_DECISION = "science_plan_tool_decision"
PLAN_TOOL_REJECTED = "science_plan_tool_rejected"


def _todos(state: dict[str, Any]) -> list[Any]:
    values = state.get("todos") or []
    return [item.model_dump() if hasattr(item, "model_dump") else item for item in values]


def _has_active_plan(state: dict[str, Any]) -> bool:
    todos = _todos(state)
    return bool(todos) and all(
        isinstance(item, dict) and str(item.get("content") or "").strip()
        and item.get("status") in {"pending", "in_progress", "interaction", "error", "completed", "skipped"}
        for item in todos
    ) and sum(item["status"] in {"in_progress", "interaction", "error"} for item in todos) == 1


def _call_error(state: dict[str, Any], call: dict[str, Any], calls: list[dict[str, Any]]) -> str | None:
    if len(calls) > 1 and any(item.get("name") == "write_todos" for item in calls):
        return "Call write_todos alone and wait for it to succeed before calling any business tool."
    if call.get("name") != "write_todos":
        if not _has_active_plan(state):
            return (
                "No valid active plan exists. Call write_todos alone with the first actionable step in_progress "
                "and wait for it to succeed before retrying this tool. No work was executed."
            )
        return None
    try:
        todos = ExtendedWriteTodosInput.model_validate(call.get("args")).todos
    except ValidationError:
        return "Invalid write_todos input. Submit a complete valid plan in a separate call."
    if not todos or any(not todo.content.strip() for todo in todos):
        return "The scientific plan must contain nonempty steps."
    if not _todos(state):
        if todos[0].status != "in_progress" or any(todo.status != "pending" for todo in todos[1:]):
            return (
                "Plan creation failed. Retry write_todos alone with the first step in_progress, "
                "all later steps pending, and all summaries empty. Wait for success before using other tools."
            )
        if any(todo.summary for todo in todos):
            return "Initial steps have not been executed; their summaries must be empty."
    unfinished = [todo for todo in todos if todo.status in {"pending", "in_progress"}]
    if unfinished and sum(todo.status == "in_progress" for todo in unfinished) != 1:
        return "An unfinished plan must have exactly one in_progress step."
    return None


class PlanFirstMiddleware(AgentMiddleware):
    """Enabled only for science agents; no instance state shared between conversations."""

    def _prepare(self, request: ModelRequest) -> tuple[ModelRequest, str]:
        round_id = uuid4().hex
        model = request.model.model_copy(update={
            "metadata": {**(request.model.metadata or {}), PLAN_TOOL_ROUND: round_id},
        })
        tools = request.tools
        if not _has_active_plan(request.state):
            tools = [tool for tool in tools if (
                tool.get("name", (tool.get("function") or {}).get("name"))
                if isinstance(tool, dict) else getattr(tool, "name", None)
            ) == "write_todos"]
        return request.override(model=model, tools=tools), round_id

    def _publish_decision(self, request: ModelRequest, round_id: str, response: ModelCallResult) -> None:
        if isinstance(response, ExtendedModelResponse):
            response = response.model_response
        messages = [response] if isinstance(response, AIMessage) else response.result
        calls = [call for message in messages if isinstance(message, AIMessage) for call in message.tool_calls]
        allowed, rejected = [], []
        for call in calls:
            (rejected if _call_error(request.state, call, calls) else allowed).append(call["id"])
        request.runtime.stream_writer({
            "type": PLAN_TOOL_DECISION,
            "roundId": round_id,
            "allowedToolCallIds": allowed,
            "rejectedToolCallIds": rejected,
        })

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelCallResult],
    ) -> ModelCallResult:
        prepared, round_id = self._prepare(request)
        response = handler(prepared)
        self._publish_decision(request, round_id, response)
        return response

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelCallResult]],
    ) -> ModelCallResult:
        prepared, round_id = self._prepare(request)
        response = await handler(prepared)
        self._publish_decision(request, round_id, response)
        return response

    def _reject(self, request: ToolCallRequest) -> ToolMessage | None:
        calls = next((message.tool_calls for message in reversed(request.state.get("messages", []))
                      if isinstance(message, AIMessage) and message.tool_calls), [request.tool_call])
        if error := _call_error(request.state, request.tool_call, calls):
            return ToolMessage(
                content=error, name=request.tool_call["name"], tool_call_id=request.tool_call["id"],
                status="error", additional_kwargs={PLAN_TOOL_REJECTED: True},
            )
        return None

    def wrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        rejected = self._reject(request)
        return rejected if rejected is not None else handler(request)

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        rejected = self._reject(request)
        return rejected if rejected is not None else await handler(request)
