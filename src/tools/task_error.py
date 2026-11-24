from __future__ import annotations

from typing import Annotated, Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.context import AgentRuntimeContext
from src.utils.conversation_progress import (
    CONVERSATION_STATUS_ERROR,
    MARK_TASK_ERROR_TOOL_NAME,
    TASK_ERROR_CHANGED_METADATA_KEY,
    TASK_ERROR_RECORDED_MESSAGE,
    todos_with_current_in_progress_as_error,
)


@tool(
    MARK_TASK_ERROR_TOOL_NAME,
    description=(
        "Record that execution is blocked by an unresolved error and hand control back to the user. "
        "Use this only after a remote execution failure that must be handed back to the user, or after "
        "the same blocking error still cannot be resolved after two corrective attempts. This is a terminal "
        "status-reporting tool, not a planning tool: do not use it to create, revise, continue, or complete "
        "todos. Use write_todos for normal plan management. After calling this tool, stop retrying and ask "
        "the user what to do next."
    ),
)
def mark_task_error(
    error_summary: Annotated[
        str,
        "Clear user-facing summary of the unresolved error that blocks progress.",
    ],
    current_progress: Annotated[
        str,
        "Brief summary of what has already been completed or attempted before the task became blocked.",
    ] = "",
    runtime: ToolRuntime[AgentRuntimeContext, Any] = None,
) -> Command | dict[str, Any]:
    """Mark the active planned task as errored and synchronize the status."""

    normalized_error = " ".join(str(error_summary).strip().split())
    normalized_progress = " ".join(str(current_progress).strip().split())
    if not normalized_error:
        normalized_error = "任务被未解决的错误阻塞，无法继续执行。"

    todos = todos_with_current_in_progress_as_error(getattr(runtime, "state", None))
    changed = todos is not None
    result = {
        "status": CONVERSATION_STATUS_ERROR if changed else "no_active_todo",
        "error_summary": normalized_error,
        "current_progress": normalized_progress,
        "message": TASK_ERROR_RECORDED_MESSAGE if changed else "未找到活跃计划，未修改会话状态。",
    }

    if runtime is None or runtime.tool_call_id is None:
        return result

    update: dict[str, Any] = {
        "messages": [
            ToolMessage(
                content=result["message"],
                name=MARK_TASK_ERROR_TOOL_NAME,
                tool_call_id=runtime.tool_call_id,
                additional_kwargs={TASK_ERROR_CHANGED_METADATA_KEY: changed},
            )
        ]
    }
    if changed:
        update["todos"] = todos
    return Command(update=update)


__all__ = ["mark_task_error"]

