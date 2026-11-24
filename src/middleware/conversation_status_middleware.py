from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.utils.conversation_progress import (
    CONVERSATION_STATUS_IN_PROGRESS,
    WRITE_TODOS_TOOL_NAME,
    set_conversation_status_from_runtime,
)


def _is_write_todos(request: ToolCallRequest) -> bool:
    return request.tool_call.get("name") == WRITE_TODOS_TOOL_NAME


class ConversationStatusMiddleware(AgentMiddleware):
    def _before_write_todos(self, request: ToolCallRequest) -> None:
        set_conversation_status_from_runtime(request.runtime, CONVERSATION_STATUS_IN_PROGRESS)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if not _is_write_todos(request):
            return handler(request)

        self._before_write_todos(request)
        # Plan completion is not response completion: the summary still has to
        # stream and be persisted. The chat processor finalizes session status.
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not _is_write_todos(request):
            return await handler(request)

        self._before_write_todos(request)
        return await handler(request)


__all__ = ["ConversationStatusMiddleware"]
