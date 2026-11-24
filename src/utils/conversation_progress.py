from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from langgraph.config import get_stream_writer

from src.agents.context import AgentRuntimeContext
from src.api.session_store import update_session_status
from src.logger import get_logger
from src.utils.streaming import CUSTOM_TOOL_CALL_SYNC
from src.utils.todolists import WRITE_TODOS_TOOL_NAME

logger = get_logger(__name__)

CONVERSATION_STATUS_IN_PROGRESS = "in_progress"
CONVERSATION_STATUS_INTERACTION = "interaction"
CONVERSATION_STATUS_COMPLETED = "completed"
CONVERSATION_STATUS_ERROR = "error"
CONVERSATION_STATUS_CANCELLED = "cancelled"
TODO_STATUS_INTERACTION = CONVERSATION_STATUS_INTERACTION
MARK_TASK_ERROR_TOOL_NAME = "mark_task_error"
TASK_ERROR_CHANGED_METADATA_KEY = "task_error_changed"
TASK_ERROR_RECORDED_MESSAGE = "已记录阻塞错误状态，并同步给用户界面。"


def _todo_to_dict(todo: Any) -> dict[str, Any] | None:
    if isinstance(todo, dict):
        return deepcopy(todo)

    model_dump = getattr(todo, "model_dump", None)
    if callable(model_dump):
        dumped_todo = model_dump()
        if isinstance(dumped_todo, dict):
            return deepcopy(dumped_todo)

    content = getattr(todo, "content", None)
    status = getattr(todo, "status", None)
    if content is not None or status is not None:
        return {"content": content, "status": status}
    return None


def runtime_ids(runtime: Any) -> tuple[str | None, str | None]:
    context = getattr(runtime, "context", None)
    if isinstance(context, AgentRuntimeContext):
        return context.user_id, context.conversation_id
    return None, None


def set_conversation_status_from_runtime(runtime: Any, status: str | None) -> bool:
    """Persist the conversation status without emitting a stream event."""
    user_id, conversation_id = runtime_ids(runtime)
    if not user_id or not conversation_id:
        return False

    try:
        updated = update_session_status(user_id, conversation_id, status)
    except Exception:
        logger.exception("Failed to update conversation status conversation_id=%s status=%s", conversation_id, status)
        return False

    if updated:
        logger.info("Conversation status updated conversation_id=%s status=%s", conversation_id, status)
    return updated


def _todos_with_statuses_replaced(
    state: Any,
    *,
    source_statuses: set[str],
    target_status: str,
    replace_all: bool,
) -> list[Any] | None:
    if not isinstance(state, dict):
        return None

    raw_todos = state.get("todos")
    if not isinstance(raw_todos, list):
        return None

    todos: list[Any] = []
    for raw_todo in raw_todos:
        todos.append(_todo_to_dict(raw_todo) or deepcopy(raw_todo))

    changed = False
    for todo in todos:
        if not isinstance(todo, dict) or todo.get("status") not in source_statuses:
            continue
        todo["status"] = target_status
        changed = True
        if not replace_all:
            return todos
    return todos if changed else None


def todos_with_current_in_progress_as_error(state: Any) -> list[Any] | None:
    return _todos_with_statuses_replaced(
        state,
        source_statuses={CONVERSATION_STATUS_IN_PROGRESS},
        target_status=CONVERSATION_STATUS_ERROR,
        replace_all=False,
    )


def todos_with_current_in_progress_as_interaction(state: Any) -> list[Any] | None:
    return _todos_with_statuses_replaced(
        state,
        source_statuses={CONVERSATION_STATUS_IN_PROGRESS},
        target_status=TODO_STATUS_INTERACTION,
        replace_all=False,
    )


def todos_with_errors_as_in_progress(state: Any) -> list[Any] | None:
    return _todos_with_statuses_replaced(
        state,
        source_statuses={CONVERSATION_STATUS_ERROR},
        target_status=CONVERSATION_STATUS_IN_PROGRESS,
        replace_all=True,
    )


def todos_with_paused_as_in_progress(state: Any) -> list[Any] | None:
    return _todos_with_statuses_replaced(
        state,
        source_statuses={CONVERSATION_STATUS_ERROR, TODO_STATUS_INTERACTION},
        target_status=CONVERSATION_STATUS_IN_PROGRESS,
        replace_all=True,
    )


def emit_todolist_sync(todos: list[Any], *, reason: str) -> None:
    writer = get_stream_writer()
    writer(
        {
            "type": CUSTOM_TOOL_CALL_SYNC,
            "toolCallId": f"middleware_todolist_{uuid4().hex}",
            "toolName": WRITE_TODOS_TOOL_NAME,
            "input": {"todos": todos},
            "reason": reason,
        }
    )
    logger.info("Synthetic todolist event emitted reason=%s", reason)


__all__ = [
    "CONVERSATION_STATUS_CANCELLED",
    "CONVERSATION_STATUS_COMPLETED",
    "CONVERSATION_STATUS_ERROR",
    "CONVERSATION_STATUS_IN_PROGRESS",
    "CONVERSATION_STATUS_INTERACTION",
    "MARK_TASK_ERROR_TOOL_NAME",
    "TASK_ERROR_CHANGED_METADATA_KEY",
    "TASK_ERROR_RECORDED_MESSAGE",
    "TODO_STATUS_INTERACTION",
    "WRITE_TODOS_TOOL_NAME",
    "emit_todolist_sync",
    "runtime_ids",
    "set_conversation_status_from_runtime",
    "todos_with_current_in_progress_as_interaction",
    "todos_with_errors_as_in_progress",
    "todos_with_paused_as_in_progress",
    "todos_with_current_in_progress_as_error",
]
