from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException
from langgraph.types import Command

from src.logger import get_logger

logger = get_logger(__name__)


def _tool_error_message(request: ToolCallRequest, exc: ToolException) -> ToolMessage:
    tool_call = request.tool_call
    tool_name = str(tool_call.get("name") or "")
    tool_call_id = str(tool_call.get("id") or "")
    content = f"Tool execution failed: {exc}"

    logger.warning(
        "Tool execution failed and returned as ToolMessage tool=%s error=%s",
        tool_name,
        exc,
    )
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        name=tool_name or None,
        status="error",
    )


class McpToolErrorMiddleware(AgentMiddleware):
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        try:
            return handler(request)
        except ToolException as exc:
            return _tool_error_message(request, exc)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            return await handler(request)
        except ToolException as exc:
            return _tool_error_message(request, exc)


__all__ = ["McpToolErrorMiddleware"]
