"""Validation for AgentEarth ECharts chart-card resources."""

from __future__ import annotations

import json
import math
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

MAX_CHART_FRAME_BYTES = 256 * 1024
MAX_CHART_HEIGHT = 1200
MIN_CHART_HEIGHT = 120

ECHARTS_SERIES_TYPES = frozenset(
    {
        "bar",
        "line",
        "pie",
        "scatter",
    }
)
_UNSAFE_OPTION_KEYS = frozenset(
    {
        "__proto__",
        "constructor",
        "formatter",
        "renderitem",
        "prototype",
    }
)
_REMOTE_RESOURCE_KEYS = frozenset({"image", "symbol", "url"})


class ChartModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class ChartSource(ChartModel):
    tool: Annotated[str, Field(min_length=1, max_length=128)]
    at: Annotated[str, Field(min_length=1, max_length=64)]


class ChartItem(ChartModel):
    """One chart inside a ``charts`` preview resource (platform 图表协议)."""

    chart_type: Annotated[str | None, Field(alias="chartType", max_length=32)] = None
    source_label: Annotated[str | None, Field(alias="sourceLabel", max_length=200)] = None
    height: int = Field(default=320, ge=MIN_CHART_HEIGHT, le=MAX_CHART_HEIGHT)
    option: dict[str, Any]
    # 内部字段：不进入协议输出，仅用于校验/溯源
    theme: str | dict[str, Any] = Field(default="light", exclude=True)
    fallback_table: bool = Field(default=True, alias="fallbackTable", exclude=True)
    source: ChartSource | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_chart_option(self) -> ChartItem:
        if isinstance(self.theme, str) and self.theme not in {"light", "dark"}:
            raise ValueError("theme name must be light or dark unless the host registers it")
        _validate_json_tree(self.option)
        if isinstance(self.theme, dict):
            _validate_json_tree(self.theme)
        _validate_chart_series(self.option)
        return self


class ChartCollectionResource(ChartModel):
    """``type: "chart"`` resource whose single chart lives in the ``chart`` object."""

    type: Literal["chart"]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=1000)] = ""
    chart: ChartItem = Field(serialization_alias="chart")


def _validate_chart_series(option: dict[str, Any]) -> None:
    series = option.get("series")
    if isinstance(series, dict):
        series_items = [series]
    elif isinstance(series, list):
        series_items = series
    else:
        raise ValueError("option.series must be a non-empty object or array")
    if not series_items:
        raise ValueError("option.series must not be empty")
    for index, item in enumerate(series_items):
        if not isinstance(item, dict):
            raise ValueError(f"option.series[{index}] must be an object")
        series_type = item.get("type")
        if series_type == "map":
            raise ValueError("map series requires a host-registered map and is not enabled in this build")
        if series_type == "custom":
            raise ValueError("custom series requires a host-registered renderItem and is not enabled in this build")
        if series_type not in ECHARTS_SERIES_TYPES:
            raise ValueError(f"option.series[{index}].type is not supported")


def _validate_json_tree(value: Any) -> None:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("ECharts option object keys must be strings")
            key = raw_key.lower()
            if key in _UNSAFE_OPTION_KEYS:
                raise ValueError(f"ECharts option key is not supported: {raw_key}")
            if key in _REMOTE_RESOURCE_KEYS and isinstance(item, str):
                normalized = item.strip().lower()
                if normalized.startswith(("http://", "https://", "//", "data:", "image://")):
                    raise ValueError("remote and data-URI chart resources are not supported")
            _validate_json_tree(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_tree(item)
        return
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise ValueError("ECharts option must contain only finite JSON values")


def validate_chart_resource(resource: Any) -> dict[str, Any] | None:
    """Validate and normalize a chart resource for the public SSE event."""

    if not isinstance(resource, dict):
        return None
    payload = dict(resource)
    try:
        collection = ChartCollectionResource.model_validate(payload)
        normalized = collection.model_dump(mode="json", by_alias=True, exclude_none=True)
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValidationError, TypeError, ValueError):
        return None
    if len(encoded) > MAX_CHART_FRAME_BYTES:
        return None
    return normalized


__all__ = [
    "ChartCollectionResource",
    "ChartItem",
    "ECHARTS_SERIES_TYPES",
    "MAX_CHART_FRAME_BYTES",
    "MAX_CHART_HEIGHT",
    "MIN_CHART_HEIGHT",
    "validate_chart_resource",
]
