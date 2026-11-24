from __future__ import annotations

from collections.abc import Awaitable, Callable
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

from src.logger import get_logger
from src.statistics import (
    RESOURCE_METADATA_KEY,
    RESOURCE_TYPE_MCP,
    ResourceCatalog,
    ResourceStatisticsTracker,
    get_resource_statistics,
    start_resource_statistics,
)

logger = get_logger(__name__)

_SKILL_FILE_TOOL = "read_file"
_SKILL_COMMAND_TOOLS = frozenset({"execute", "scnet_remote_shell_execute"})


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list | tuple | set | frozenset):
        return [_string(item) for item in value if _string(item)]
    normalized = _string(value)
    return [normalized] if normalized else []


def _model_name(model: Any) -> str:
    for attribute in ("model_name", "model"):
        value = getattr(model, attribute, None)
        if isinstance(value, str) and value:
            return value
    return model.__class__.__name__


class ResourceStatisticsMiddleware(AgentMiddleware):
    """Collect per-agent-run model, MCP, knowledge, and Skill usage."""

    def __init__(self, catalog: ResourceCatalog) -> None:
        self.catalog = catalog

    def _start(self, runtime: Runtime) -> None:
        start_resource_statistics(runtime, self.catalog)

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        self._start(runtime)
        return None

    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        self._start(runtime)
        return None

    @staticmethod
    def _start_model(request: ModelRequest) -> tuple[ResourceStatisticsTracker | None, str, int | None]:
        tracker = get_resource_statistics(request.runtime)
        model_name = _model_name(request.model)
        model_call_id = tracker.start_model_call(model_name) if tracker is not None else None
        return tracker, model_name, model_call_id

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        tracker, model_name, model_call_id = self._start_model(request)
        response = handler(request)
        if tracker is not None and model_call_id is not None:
            try:
                tracker.finish_model_call(model_name, model_call_id, response)
            except Exception:
                logger.exception("Failed to record model resource statistics model=%s", model_name)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        tracker, model_name, model_call_id = self._start_model(request)
        response = await handler(request)
        if tracker is not None and model_call_id is not None:
            try:
                tracker.finish_model_call(model_name, model_call_id, response)
            except Exception:
                logger.exception("Failed to record model resource statistics model=%s", model_name)
        return response

    def _record_tool_call(self, request: ToolCallRequest) -> None:
        tracker = get_resource_statistics(request.runtime)
        if tracker is None:
            return
        tool_call = request.tool_call
        tool_call_id = _string(tool_call.get("id"))
        tool_name = _string(tool_call.get("name"))
        args = tool_call.get("args")
        args = args if isinstance(args, dict) else {}

        metadata = request.tool.metadata if request.tool is not None else None
        resource = metadata.get(RESOURCE_METADATA_KEY) if isinstance(metadata, dict) else None
        if isinstance(resource, dict) and resource.get("type") == RESOURCE_TYPE_MCP:
            tracker.record_mcp(tool_call_id, resource)
            logical_tool_name = _string(resource.get("tool")) or tool_name
        else:
            logical_tool_name = tool_name

        if logical_tool_name == "retrieve_knowledge_base":
            dataset_ids = _normalize_ids(args.get("dataset_id"))
            resources = (
                [
                    tracker.catalog.knowledges_by_dataset_id[item]
                    for item in dict.fromkeys(dataset_ids)
                    if item in tracker.catalog.knowledges_by_dataset_id
                ]
                if dataset_ids
                else tracker.catalog.configured_knowledges()
            )
            for knowledge in resources:
                tracker.record_knowledge(tool_call_id, knowledge)

        if logical_tool_name == _SKILL_FILE_TOOL:
            matched_skills = tracker.catalog.match_skill_path(_string(args.get("file_path")))
        elif logical_tool_name in _SKILL_COMMAND_TOOLS:
            matched_skills = tracker.catalog.match_skill_command(_string(args.get("command")))
        else:
            matched_skills = []
        for skill in matched_skills:
            tracker.record_skill(tool_call_id, skill)

    def _safe_record_tool_call(self, request: ToolCallRequest) -> None:
        try:
            self._record_tool_call(request)
        except Exception:
            logger.exception("Failed to record tool resource statistics tool=%s", request.tool_call.get("name"))

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        self._safe_record_tool_call(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        self._safe_record_tool_call(request)
        return await handler(request)


__all__ = ["ResourceStatisticsMiddleware"]
