from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from src.utils.previews import mime_type_for_path

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _created_at(value: Any) -> int:
    if not isinstance(value, str):
        return 0
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
        return int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError, OSError):
        return 0


def extract_output_files(
    session: dict[str, Any] | None,
    *,
    user_id: str,
    conversation_id: str,
    agent_id: str,
    agent_name: str,
) -> list[dict[str, Any]]:
    """Read normalized history without changing it or inspecting file contents.

    A file is identified by its cluster/path, with the first preview retained.
    Keys are deterministic within the agent/user/conversation scope. Preview IDs
    must come from history: legacy previews without IDs cannot be chat anchors.
    """
    messages = session.get("messages") if isinstance(session, dict) else None
    if not isinstance(messages, list):
        return []

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant" or message.get("type") != "preview":
            continue
        resource = message.get("resource")
        if not isinstance(resource, dict) or resource.get("type") != "efiles":
            continue
        files = resource.get("files")
        if not isinstance(files, list):
            continue
        for file in files:
            if not isinstance(file, dict):
                continue
            name, path = _text(file.get("name")), _text(file.get("path"))
            if not name or not path:
                continue
            raw_cluster = file.get("clusterId")
            if raw_cluster is not None and (isinstance(raw_cluster, bool) or not isinstance(raw_cluster, (str, int))):
                continue
            cluster_id = str(raw_cluster).strip() if raw_cluster is not None else ""
            locator = (cluster_id, path)
            if locator in seen:
                continue
            seen.add(locator)
            identity = json.dumps(
                [agent_id, user_id, conversation_id, *locator], ensure_ascii=False, separators=(",", ":")
            )
            items.append(
                {
                    "file_key": f"file_{sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                    "preview_id": _text(message.get("id")),
                    "source_agent_id": agent_id,
                    "source_agent_name": agent_name,
                    "name": name,
                    "mimeType": _text(file.get("mimeType")) or mime_type_for_path(path),
                    "url": path,
                    "clusterId": cluster_id,
                    "created_at": _created_at(message.get("time")),
                }
            )
    return items


__all__ = ["extract_output_files"]
