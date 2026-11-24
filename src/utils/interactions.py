"""Helpers for converting tool results into user interaction events."""

from __future__ import annotations

import json
from typing import Any

INTERACTION_EVENT_TYPE = "interaction"


def parse_json_object(content: Any) -> dict[str, Any] | None:
    """Extract the first JSON object from a tool-message content value."""

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        content = "".join(text_parts)

    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None

    decoder = json.JSONDecoder()
    stripped = content.strip()
    if not stripped:
        return None

    try:
        payload, _ = decoder.raw_decode(stripped)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass

    for index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        return payload if isinstance(payload, dict) else None
    return None


def resource_from_tool_output(content: Any) -> dict[str, Any] | None:
    """Read the interaction resource returned by a card tool."""

    return parse_json_object(content)


def interaction_event_from_tool_output(content: Any) -> dict[str, Any] | None:
    """Build a custom-stream interaction event from a tool result."""

    resource = resource_from_tool_output(content)
    if resource is None:
        return None
    return {"type": INTERACTION_EVENT_TYPE, "resource": resource}


__all__ = [
    "INTERACTION_EVENT_TYPE",
    "interaction_event_from_tool_output",
    "parse_json_object",
    "resource_from_tool_output",
]
