from __future__ import annotations

_THOUGHT_SIGNATURE_MARKER = "__thought__"


def public_tool_call_id(tool_call_id: object) -> str:
    """Remove provider-only thought signatures from externally exposed tool call IDs."""
    value = str(tool_call_id or "")
    call_id, marker, _ = value.partition(_THOUGHT_SIGNATURE_MARKER)
    return call_id if marker and call_id else value


__all__ = ["public_tool_call_id"]
