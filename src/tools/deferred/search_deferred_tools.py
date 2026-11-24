"""Deferred-tool discovery and activation tool."""

from __future__ import annotations

import json
from typing import Annotated

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.tools.deferred import DeferredKeyword, mcp_deferred_key


@tool(
    "search_deferred_tools",
    description=(
        "Search for and activate optional tools that are not exposed by default. "
        "Current categories are: skill, for searching and adding SCNet community Skills; "
        "mcp, for searching and adding SCNet MCP services; and knowledge, for searching "
        "and adding SCNet knowledge bases or datasets; and environment, for updating "
        "runtime environment variables and rebuilding the agent; and paper_search, for "
        "searching academic papers from arXiv and OpenAlex; and recommand_resource_card, for showing "
        "recommended SCNet resources and a link to more resources after scnet-job-manager retrieves "
        "resource recommendations. Use this tool when the currently "
        "visible tools do not cover one of these requests."
    ),
)
def search_deferred_tools(
    *,
    keyword: Annotated[
        DeferredKeyword | None,
        (
            "Deferred tool category to activate: skill, mcp, knowledge, environment, paper_search, or recommand_resource_card."
        ),
    ] = None,
    mcp: Annotated[
        str | None,
        ("Exact name of a configured deferred MCP to activate. Use only a name listed in this tool's description."),
    ] = None,
    runtime: ToolRuntime,
) -> Command:
    if (keyword is None) == (mcp is None):
        content = json.dumps(
            {
                "status": "error",
                "message": "Provide exactly one of keyword or mcp.",
            },
            ensure_ascii=False,
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=content,
                        tool_call_id=runtime.tool_call_id or "",
                        status="error",
                    )
                ]
            }
        )

    activation_key = mcp_deferred_key(mcp) if mcp is not None else keyword
    activated = {value for value in runtime.state.get("activated_deferred_keywords", []) if isinstance(value, str)}
    activated.add(activation_key)
    activated_keywords = sorted(activated)
    content = json.dumps(
        {
            "status": "success",
            "activatedKeyword": activation_key,
            "activatedDeferredKeywords": activated_keywords,
            "message": "Matching deferred tools will be available in the next model call.",
        },
        ensure_ascii=False,
    )
    return Command(
        update={
            "activated_deferred_keywords": activated_keywords,
            "messages": [
                ToolMessage(
                    content=content,
                    tool_call_id=runtime.tool_call_id or "",
                )
            ],
        }
    )


__all__ = ["search_deferred_tools"]
