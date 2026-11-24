"""Deferred-tool annotations and metadata helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langchain_core.tools import BaseTool

DeferredKeyword = Literal[
    "skill",
    "mcp",
    "knowledge",
    "environment",
    "paper_search",
    "recommand_resource_card",
]

DEFERRED_KEYWORDS = frozenset(
    {
        "skill",
        "mcp",
        "knowledge",
        "environment",
        "paper_search",
        "recommand_resource_card",
    }
)
DEFERRED_METADATA_KEY = "deferred"
DEFERRED_KEYWORD_METADATA_KEY = "deferred_keyword"
DEFERRED_MCP_DESCRIPTION_METADATA_KEY = "deferred_mcp_description"
DEFERRED_MCP_NAMES_METADATA_KEY = "deferred_mcp_names"
MCP_DEFERRED_PREFIX = "mcp:"
_MAX_MCP_DEFERRED_NAME_LENGTH = 256


def normalize_deferred_keyword(value: Any) -> str | None:
    if value is None or value is False:
        return None

    keyword = value.get("keyword") if isinstance(value, dict) else value
    if not isinstance(keyword, str) or keyword not in DEFERRED_KEYWORDS:
        allowed = ", ".join(sorted(DEFERRED_KEYWORDS))
        raise ValueError(f"deferred keyword must be one of: {allowed}")
    return keyword


def mcp_deferred_key(name: str) -> str:
    if not isinstance(name, str) or not name.strip() or name != name.strip() or len(name) > _MAX_MCP_DEFERRED_NAME_LENGTH:
        raise ValueError(f"invalid deferred MCP name: {name!r}")
    return f"{MCP_DEFERRED_PREFIX}{name}"


def normalize_deferred_activation_key(value: Any) -> str | None:
    if value is None or value is False:
        return None
    if isinstance(value, str) and value.startswith(MCP_DEFERRED_PREFIX):
        return mcp_deferred_key(value.removeprefix(MCP_DEFERRED_PREFIX))
    return normalize_deferred_keyword(value)


def deferred(keyword: DeferredKeyword) -> Callable[[BaseTool], BaseTool]:
    normalized_keyword = normalize_deferred_keyword(keyword)
    if normalized_keyword is None:
        raise ValueError("deferred keyword is required")

    def decorator(tool: BaseTool) -> BaseTool:
        if not isinstance(tool, BaseTool):
            raise TypeError("@deferred must wrap a tool created by @tool")
        metadata = {
            **(tool.metadata or {}),
            DEFERRED_METADATA_KEY: True,
            DEFERRED_KEYWORD_METADATA_KEY: normalized_keyword,
        }
        return tool.model_copy(update={"metadata": metadata})

    return decorator


def deferred_tool_keyword(tool: Any) -> str | None:
    if isinstance(tool, dict):
        metadata = tool.get("metadata")
    else:
        metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict) or metadata.get(DEFERRED_METADATA_KEY) is not True:
        return None

    keyword = metadata.get(DEFERRED_KEYWORD_METADATA_KEY)
    try:
        return normalize_deferred_activation_key(keyword)
    except ValueError:
        return None


def mark_tools_deferred(tools: list[BaseTool], keyword: str | None) -> list[BaseTool]:
    if keyword is None:
        return tools
    normalized_keyword = normalize_deferred_activation_key(keyword)
    if normalized_keyword is None:
        return tools

    return [
        tool.model_copy(
            update={
                "metadata": {
                    **(tool.metadata or {}),
                    DEFERRED_METADATA_KEY: True,
                    DEFERRED_KEYWORD_METADATA_KEY: normalized_keyword,
                }
            }
        )
        for tool in tools
    ]


def mark_mcp_tools_deferred(
    tools: list[BaseTool],
    *,
    name: str,
    description: str = "",
) -> list[BaseTool]:
    activation_key = mcp_deferred_key(name)
    return [
        tool.model_copy(
            update={
                "metadata": {
                    **(tool.metadata or {}),
                    DEFERRED_METADATA_KEY: True,
                    DEFERRED_KEYWORD_METADATA_KEY: activation_key,
                    DEFERRED_MCP_DESCRIPTION_METADATA_KEY: description,
                }
            }
        )
        for tool in tools
    ]


def deferred_mcp_routes(tools: list[BaseTool]) -> dict[str, str]:
    routes: dict[str, str] = {}
    for tool in tools:
        activation_key = deferred_tool_keyword(tool)
        if activation_key is None or not activation_key.startswith(MCP_DEFERRED_PREFIX):
            continue
        metadata = tool.metadata or {}
        name = activation_key.removeprefix(MCP_DEFERRED_PREFIX)
        description = metadata.get(DEFERRED_MCP_DESCRIPTION_METADATA_KEY)
        routes[name] = description if isinstance(description, str) else ""
    return routes


__all__ = [
    "DEFERRED_KEYWORDS",
    "DEFERRED_KEYWORD_METADATA_KEY",
    "DEFERRED_MCP_DESCRIPTION_METADATA_KEY",
    "DEFERRED_MCP_NAMES_METADATA_KEY",
    "DEFERRED_METADATA_KEY",
    "DeferredKeyword",
    "deferred",
    "deferred_tool_keyword",
    "deferred_mcp_routes",
    "mark_mcp_tools_deferred",
    "mark_tools_deferred",
    "mcp_deferred_key",
    "normalize_deferred_activation_key",
    "normalize_deferred_keyword",
]
