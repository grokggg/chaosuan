from __future__ import annotations

import json
import re
from typing import Any

MCP_SERVER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_QUOTED_SET_PATTERN = re.compile(r"^\{\s*([\"'])(?P<name>[^\"']+)\1\s*\}$")


def normalize_mcp_server_name(raw_name: Any) -> str:
    name = str(raw_name or "").strip()
    if not name:
        raise ValueError("MCP server name must be a non-empty string")

    # Recover common double-serialized names such as "\"mark-mcp\"".
    for _ in range(2):
        try:
            parsed = json.loads(name)
        except json.JSONDecodeError:
            break
        if not isinstance(parsed, str):
            break
        next_name = parsed.strip()
        if not next_name or next_name == name:
            break
        name = next_name

    # Recover set-like strings produced by upstream serialization bugs:
    # {"mcp-server-markitdown"} -> mcp-server-markitdown
    match = _QUOTED_SET_PATTERN.fullmatch(name)
    if match is not None:
        name = match.group("name").strip()

    if not MCP_SERVER_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "MCP server name must match "
            f"{MCP_SERVER_NAME_PATTERN.pattern}; got {raw_name!r}"
        )
    return name


def normalize_mcp_servers_mapping(raw_servers: dict[Any, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized: dict[str, Any] = {}
    errors: list[str] = []
    for raw_name, config in raw_servers.items():
        try:
            server_name = normalize_mcp_server_name(raw_name)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if server_name in normalized:
            errors.append(f"duplicate MCP server name after normalization: {server_name}")
            continue
        normalized[server_name] = config
    return normalized, errors


__all__ = [
    "MCP_SERVER_NAME_PATTERN",
    "normalize_mcp_server_name",
    "normalize_mcp_servers_mapping",
]
