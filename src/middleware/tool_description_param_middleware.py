from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, AgentState, ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, create_model

from src.logger import get_logger
from src.tools.deferred import DEFERRED_MCP_NAMES_METADATA_KEY, deferred_tool_keyword

logger = get_logger(__name__)

_DESCRIPTION_FIELD = "tool_call_description"
_DESCRIPTION_FIELD_TEXT = (
    "这是展示给用户的工具动作标题，描述调用意图，不是执行结果；工具返回前不得声称成功或验证通过。"
    "必须使用‘正在 + 动作 + 对象’的中文句式，说清当前在做什么业务动作，"
    "以及正在处理什么对象。优先使用用户能理解的科学或业务语言，已知时可体现数据类型、计算方法或目标对象。"
    "不要写工具名、函数名、技能名、文件绝对路径或实现细节，不要有主语，不要使用句号或冒号。"
    "长度建议12-30个汉字。正例：正在查询可用计算队列、正在检查SCF输入参数、正在提取总能量与收敛信息。"
    "反例：查询队列、调用工具、正在执行任务。"
)


class DeferredToolState(AgentState[Any]):
    activated_deferred_keywords: NotRequired[list[str]]


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            function_payload = tool.get("function")
            name = function_payload.get("name") if isinstance(function_payload, dict) else None
    else:
        name = getattr(tool, "name", None)
    return name if isinstance(name, str) and name else None


def _tool_args_schema(tool: Any) -> type[BaseModel] | dict[str, Any] | None:
    schema = getattr(tool, "args_schema", None)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    if isinstance(schema, dict):
        return schema
    return None


def _extend_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, dict) or _DESCRIPTION_FIELD in properties:
        return schema

    required = schema.get("required")
    updated_required = list(required) if isinstance(required, list) else []
    if _DESCRIPTION_FIELD not in updated_required:
        updated_required.append(_DESCRIPTION_FIELD)

    return {
        **schema,
        "required": updated_required,
        "properties": {
            **properties,
            _DESCRIPTION_FIELD: {
                "type": "string",
                "description": _DESCRIPTION_FIELD_TEXT,
            },
        },
    }


def _extend_dict_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    function_payload = tool.get("function")
    if not isinstance(function_payload, dict):
        return tool

    parameters = function_payload.get("parameters")
    if not isinstance(parameters, dict):
        return tool

    updated_parameters = _extend_json_schema(parameters)
    if updated_parameters is parameters:
        return tool

    return {
        **tool,
        "function": {
            **function_payload,
            "parameters": updated_parameters,
        },
    }


def split_tool_call_description(args: Any) -> tuple[Any, str | None]:
    if isinstance(args, str):
        try:
            parsed_args = json.loads(args)
        except json.JSONDecodeError:
            return args, None
        if not isinstance(parsed_args, dict):
            return args, None
        stripped_args, description = split_tool_call_description(parsed_args)
        if stripped_args is parsed_args:
            return args, description
        return json.dumps(stripped_args, ensure_ascii=False), description

    if not isinstance(args, dict) or _DESCRIPTION_FIELD not in args:
        return args, None

    description = args.get(_DESCRIPTION_FIELD)
    stripped_args = {key: value for key, value in args.items() if key != _DESCRIPTION_FIELD}
    if isinstance(description, str):
        description = description.strip() or None
    else:
        description = None
    return stripped_args, description


class ToolDescriptionParamMiddleware(AgentMiddleware[DeferredToolState, Any, Any]):
    state_schema = DeferredToolState

    def __init__(self) -> None:
        self._schema_cache: dict[tuple[str, type[BaseModel]], type[BaseModel]] = {}

    def _extend_args_schema(self, tool_name: str, schema: type[BaseModel]) -> type[BaseModel]:
        if _DESCRIPTION_FIELD in schema.model_fields:
            return schema

        key = (tool_name, schema)
        cached = self._schema_cache.get(key)
        if cached is not None:
            return cached

        extended_schema = create_model(
            f"{schema.__name__}WithDescription",
            __base__=schema,
            tool_call_description=(str, Field(..., description=_DESCRIPTION_FIELD_TEXT)),
        )
        self._schema_cache[key] = extended_schema
        return extended_schema

    def _extend_tool(self, tool: Any) -> Any:
        name = _tool_name(tool)
        if name is None:
            return tool

        if isinstance(tool, dict):
            return _extend_dict_tool_schema(tool)

        if not isinstance(tool, BaseTool):
            return tool

        args_schema = _tool_args_schema(tool)
        if args_schema is None:
            return tool

        if isinstance(args_schema, dict):
            updated_args_schema = _extend_json_schema(args_schema)
            if updated_args_schema is args_schema:
                return tool
            return tool.model_copy(update={"args_schema": updated_args_schema})

        return tool.model_copy(update={"args_schema": self._extend_args_schema(name, args_schema)})

    @staticmethod
    def _activated_keywords(state: Any) -> set[str]:
        if not isinstance(state, dict):
            return set()
        values = state.get("activated_deferred_keywords", [])
        if not isinstance(values, list):
            return set()
        return {value for value in values if isinstance(value, str)}

    def _prepare_request_tools(self, request: ModelRequest) -> ModelRequest:
        activated_keywords = self._activated_keywords(request.state)
        tools = [
            tool
            for tool in request.tools or []
            if (keyword := deferred_tool_keyword(tool)) is None or keyword in activated_keywords
        ]
        extended_tools = [self._extend_tool(tool) for tool in tools]
        if all(original is extended for original, extended in zip(tools, extended_tools, strict=True)):
            if len(tools) == len(request.tools or []):
                return request
        return request.override(tools=extended_tools)

    def _deferred_tool_error(self, request: ToolCallRequest) -> ToolMessage | None:
        keyword = deferred_tool_keyword(request.tool)
        if keyword is None or keyword in self._activated_keywords(request.state):
            return None
        if keyword.startswith("mcp:"):
            activation_instruction = (
                f"Call search_deferred_tools with mcp='{keyword.removeprefix('mcp:')}' first."
            )
        else:
            activation_instruction = f"Call search_deferred_tools with keyword='{keyword}' first."
        return ToolMessage(
            content=(
                f"Deferred tool category '{keyword}' is not activated. "
                f"{activation_instruction}"
            ),
            tool_call_id=str(request.tool_call.get("id") or ""),
            status="error",
        )

    @staticmethod
    def _deferred_mcp_search_error(request: ToolCallRequest) -> ToolMessage | None:
        if _tool_name(request.tool) != "search_deferred_tools":
            return None
        args = request.tool_call.get("args")
        mcp_name = args.get("mcp") if isinstance(args, dict) else None
        if mcp_name is None:
            return None
        metadata = getattr(request.tool, "metadata", None)
        allowed_names = metadata.get(DEFERRED_MCP_NAMES_METADATA_KEY) if isinstance(metadata, dict) else None
        if isinstance(mcp_name, str) and isinstance(allowed_names, list) and mcp_name in allowed_names:
            return None
        return ToolMessage(
            content=f"Deferred MCP '{mcp_name}' is not available for activation.",
            tool_call_id=str(request.tool_call.get("id") or ""),
            status="error",
        )

    def _strip_description_arg(self, request: ToolCallRequest) -> ToolCallRequest:
        tool_call = request.tool_call
        args = tool_call.get("args")
        stripped_args, description = split_tool_call_description(args)
        if stripped_args is args:
            return request

        if description:
            logger.info(
                "Tool call description tool=%s description=%s",
                tool_call.get("name"),
                description,
            )

        return request.override(
            tool_call={
                **tool_call,
                "args": stripped_args,
            }
        )

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(self._prepare_request_tools(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._prepare_request_tools(request))

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        if error := self._deferred_mcp_search_error(request):
            return error
        if error := self._deferred_tool_error(request):
            return error
        return handler(self._strip_description_arg(request))

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        if error := self._deferred_mcp_search_error(request):
            return error
        if error := self._deferred_tool_error(request):
            return error
        return await handler(self._strip_description_arg(request))


__all__ = ["DeferredToolState", "ToolDescriptionParamMiddleware", "split_tool_call_description"]
