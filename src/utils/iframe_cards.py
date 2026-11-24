"""Validation and event helpers for generic iframe cards."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from src.utils.interactions import parse_json_object

MAX_IFRAME_INIT_DATA_BYTES = 64 * 1024
IFRAME_EVENT_TYPE = "interaction"


class IframeBody(BaseModel):
    """Inner ``iframe`` object of an iframe card resource."""

    model_config = ConfigDict(extra="forbid", strict=True)

    source: str = Field(default="earth", max_length=64)
    url: str = Field(min_length=1, max_length=4096)
    data: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("data", "initData"),
        serialization_alias="data",
    )


class IframeResource(BaseModel):
    """``resource`` block of an iframe card: ``type: "iframe"`` + ``iframe`` body.

    Also accepts the previous flat shape (``url`` / ``data`` at resource level).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["iframe"] = "iframe"
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    iframe: IframeBody
    # 会议约定：resource 下另有一个顶层 url，前端用它显示"预览地址"
    url: str | None = Field(default=None, max_length=4096)


def validate_iframe_resource(resource: Any) -> dict[str, Any] | None:
    """Validate and normalize the iframe resource used by the public event."""

    if not isinstance(resource, dict):
        return None
    payload = dict(resource)
    try:
        parsed = IframeResource.model_validate(payload)
        encoded = json.dumps(
            parsed.iframe.data,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > MAX_IFRAME_INIT_DATA_BYTES:
            return None
        return parsed.model_dump(mode="json", by_alias=True)
    except (ValidationError, TypeError, ValueError):
        return None


def iframe_event_from_tool_output(content: Any) -> dict[str, Any] | None:
    """Extract a validated iframe interaction event from a tool result."""

    payload = parse_json_object(content)
    if not isinstance(payload, dict):
        return None
    # ``show_iframe`` uses an interaction event for interactive pages and a
    # preview event for informational pages.  Both carry the same validated
    # iframe resource; preserve the event type so the stream can route either
    # form without silently dropping ``interactive=false`` cards.
    event_type = payload.get("type")
    if event_type not in {IFRAME_EVENT_TYPE, "preview"}:
        return None
    event_id = payload.get("id")
    resource = payload.get("resource")
    if not isinstance(resource, dict):
        return None
    if resource.get("type") != "iframe":
        return None
    validated = validate_iframe_resource(resource)
    if not isinstance(event_id, str) or not event_id.strip() or validated is None:
        return None
    return {"type": event_type, "id": event_id.strip(), "resource": validated}


__all__ = [
    "IFRAME_EVENT_TYPE",
    "IframeBody",
    "IframeResource",
    "MAX_IFRAME_INIT_DATA_BYTES",
    "iframe_event_from_tool_output",
    "validate_iframe_resource",
]
