from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.logger import get_logger
from src.utils.config import load_agent_config

TODOLIST_EVENT_TYPE = "todolist"
TODOLIST_ID_TYPE = "todolist_output"
WRITE_TODOS_TOOL_NAME = "write_todos"
MAX_TODOLIST_STEP_NAME_LENGTH = 60
MAX_TODOLIST_SUMMARY_LENGTH = 120

logger = get_logger(__name__)
_VALID_STEP_STATUSES = {"pending", "in_progress", "interaction", "completed", "error", "skipped"}
_VALID_TODOLIST_STATUSES = _VALID_STEP_STATUSES


def _agent_identity() -> str | None:
    agent_id = os.getenv("AGENT_ID", "").strip()
    try:
        config = load_agent_config()
    except (OSError, ValueError):
        config = {}

    repo_name = str(config.get("repo_name") or "").strip()
    identity_parts = [
        value
        for value in (
            f"agent_id:{agent_id}" if agent_id else "",
            f"repo_name:{repo_name}" if repo_name else "",
        )
        if value
    ]
    return "\0".join(identity_parts) or None


@lru_cache(maxsize=1)
def agent_namespace() -> str | None:
    identity = _agent_identity()
    if identity is None:
        return None
    return uuid5(NAMESPACE_URL, f"sag-maker:todolist:{identity}").hex


def clear_todolist_agent_namespace_cache() -> None:
    agent_namespace.cache_clear()


def _step_id(step_number: int, agent_namespace: str | None) -> str:
    if agent_namespace is None:
        return str(step_number)
    return f"{step_number}_{agent_namespace}"


def _normalized_status(value: Any) -> str:
    status = str(value or "pending")
    return status if status in _VALID_STEP_STATUSES else "pending"


def _step_name(value: Any) -> str:
    name = str(value or "")
    if len(name) <= MAX_TODOLIST_STEP_NAME_LENGTH:
        return name

    logger.warning(
        "Truncating todolist step name from %d to %d characters: %s",
        len(name),
        MAX_TODOLIST_STEP_NAME_LENGTH,
        name,
    )
    return f"{name[: MAX_TODOLIST_STEP_NAME_LENGTH - 1]}…"


def _step_summary(fields: Mapping[str, Any]) -> dict[str, str]:
    """Expose a brief result only on the completed step that owns it."""
    summary = fields.get("summary")
    if fields.get("status") != "completed" or not isinstance(summary, str):
        return {}
    summary = " ".join(summary.split())
    if not summary:
        return {}
    if len(summary) > MAX_TODOLIST_SUMMARY_LENGTH:
        summary = summary[: MAX_TODOLIST_SUMMARY_LENGTH - 1] + "…"
    return {"summary": summary}


def _overall_status(steps: list[dict[str, str]]) -> str:
    statuses = [step["status"] for step in steps]
    if "error" in statuses:
        return "error"
    if "interaction" in statuses:
        return "interaction"
    if "in_progress" in statuses:
        return "in_progress"
    if steps and set(statuses) <= {"completed", "skipped"}:
        return "completed"
    return "pending"


def _todo_fields(todo: Any) -> Mapping[str, Any] | None:
    """Return todo fields from plain mappings or validated model instances."""
    if isinstance(todo, Mapping):
        return todo

    model_dump = getattr(todo, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped

    return None


def todolist_resource(todos: Any) -> dict[str, Any]:
    steps: list[dict[str, str]] = []
    namespace = agent_namespace()
    if isinstance(todos, list):
        for todo in todos:
            fields = _todo_fields(todo)
            if fields is None:
                continue
            status = _normalized_status(fields.get("status"))
            steps.append(
                {
                    "stepId": _step_id(len(steps) + 1, namespace),
                    "name": _step_name(fields.get("content")),
                    "status": status,
                    **_step_summary(fields),
                }
            )

    return {"status": _overall_status(steps), "steps": steps}


def preserve_completed_summaries(previous: Any, todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain omitted results without transferring them into a replacement plan."""
    old = [_todo_fields(todo) or {} for todo in previous] if isinstance(previous, list) else []
    # Completed/skipped items are immutable within a plan. Replacing or
    # restarting one therefore starts a different plan, even if IDs are reused.
    for index, item in enumerate(old):
        if item.get("status") not in {"completed", "skipped"}:
            continue
        if (
            index >= len(todos)
            or todos[index].get("content") != item.get("content")
            or todos[index].get("status") != item.get("status")
        ):
            return todos
    updated = [dict(todo) for todo in todos]
    for index, todo in enumerate(updated):
        if index >= len(old) or todo.get("status") != "completed":
            continue
        item = old[index]
        if item.get("status") == "completed" and item.get("content") == todo.get("content"):
            if not _step_summary(todo):
                todo.update(_step_summary(item))
    return updated


def current_in_progress_step_id(todos: Any) -> str | None:
    """Return the public step ID for the current in-progress todo, if any."""
    for step in todolist_resource(todos)["steps"]:
        if step["status"] == "in_progress":
            return step["stepId"]
    return None


def normalize_todolist_resource(resource: Any) -> dict[str, Any]:
    """Return a public/session todolist resource with stable agent-scoped step IDs."""
    steps: list[dict[str, str]] = []
    namespace = agent_namespace()
    raw_steps = resource.get("steps") if isinstance(resource, dict) else None
    if isinstance(raw_steps, list):
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                continue
            steps.append(
                {
                    "stepId": _step_id(len(steps) + 1, namespace),
                    "name": _step_name(raw_step.get("name") or raw_step.get("content")),
                    "status": _normalized_status(raw_step.get("status")),
                    **_step_summary(raw_step),
                }
            )

    raw_status = resource.get("status") if isinstance(resource, dict) else None
    status = (
        raw_status
        if isinstance(raw_status, str) and raw_status in _VALID_TODOLIST_STATUSES
        else _overall_status(steps)
    )
    return {"status": status, "steps": steps}


def todolist_event(todos: Any) -> dict[str, Any]:
    return {
        "type": TODOLIST_EVENT_TYPE,
        "resource": todolist_resource(todos),
    }


__all__ = [
    "TODOLIST_EVENT_TYPE",
    "TODOLIST_ID_TYPE",
    "MAX_TODOLIST_STEP_NAME_LENGTH",
    "MAX_TODOLIST_SUMMARY_LENGTH",
    "WRITE_TODOS_TOOL_NAME",
    "agent_namespace",
    "clear_todolist_agent_namespace_cache",
    "current_in_progress_step_id",
    "normalize_todolist_resource",
    "todolist_event",
    "todolist_resource",
]
