"""Tool for emitting a validated, data-backed chart card."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException

from src.agents.context import AgentRuntimeContext
from src.utils.chart_cards import ChartItem, validate_chart_resource

_NON_DATA_TOOL_NAMES = frozenset(
    {
        "preview_assets",
        "preview_file",
        "preview_folder",
        "show_iframe",
        "show_chart",
        "show_recommand_resource_cards",
        "show_resource_cards",
    }
)


def _latest_data_tool(runtime: ToolRuntime[AgentRuntimeContext, Any] | None) -> str | None:
    if runtime is None:
        return None
    messages = runtime.state.get("messages", [])
    for message in reversed(messages if isinstance(messages, list) else []):
        if isinstance(message, ToolMessage) and message.status != "error":
            name = str(message.name or "").strip()
            if name and name not in _NON_DATA_TOOL_NAMES:
                return name
    return None


# @tool(
#     "show_chart",
#     description=(
#         "Render an AgentEarth ECharts chart card. Use only when data supports a useful comparison, "
#         "ranking, proportion, trend, or distribution. Provide title and a JSON-safe ECharts option "
#         "whose non-empty series each have a supported type. Never invent data or include functions, "
#         "remote resources, or executable code. The tool emits preview/chart SSE with the same JSON "
#         "shape used inside an agent-earth-chart block."
#     ),
# )
async def show_chart(
    title: Annotated[str, "Concise user-facing chart title."],
    option: Annotated[dict[str, Any], "JSON-safe ECharts option object with a non-empty series."],
    description: Annotated[str, "Short explanation of the data and what the chart shows."] = "",
    source_label: Annotated[str | None, "Optional data source label."] = None,
    chart_type: Annotated[str | None, "Short chart descriptor such as line, mixed, or other."] = None,
    theme: Annotated[str | dict[str, Any], "light, dark, or a host-supported JSON theme."] = "light",
    height: Annotated[int, "Card height in pixels, from 120 to 1200."] = 320,
    runtime: ToolRuntime[AgentRuntimeContext, Any] = None,
) -> str:
    normalized_title = title.strip()
    if not normalized_title:
        raise ToolException("Chart title must not be empty.")

    source_tool = _latest_data_tool(runtime)
    item = ChartItem(
        chart_type=chart_type.strip() if isinstance(chart_type, str) and chart_type.strip() else None,
        source_label=source_label.strip() if isinstance(source_label, str) and source_label.strip() else None,
        height=height,
        option=option,
        theme=theme,
        source={"tool": source_tool, "at": datetime.now(UTC).isoformat()} if source_tool else None,
    ).model_dump(mode="json", by_alias=True, exclude_none=True)
    resource = {
        "type": "chart",
        "title": normalized_title,
        "description": description.strip(),
        "chart": item,
    }
    normalized = validate_chart_resource(resource)
    if normalized is None:
        raise ToolException("Chart data is invalid or exceeds the 256KB card limit.")

    series = option.get("series")
    series_count = len(series) if isinstance(series, list) else 1
    summary = f"Chart card ready: {normalized_title} ({series_count} series)."
    return f"{summary}\n{json.dumps(normalized, ensure_ascii=False, separators=(',', ':'))}"


__all__ = ["show_chart"]
