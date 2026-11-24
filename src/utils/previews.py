from __future__ import annotations

import mimetypes
import os
from pathlib import PurePosixPath
from typing import Any

from src.utils.chart_cards import validate_chart_resource
from src.utils.interactions import parse_json_object

PREVIEW_EVENT_TYPE = "preview"
PREVIEW_FILE_TOOL_NAME = "preview_file"
PREVIEW_FOLDER_TOOL_NAME = "preview_folder"
PREVIEW_ASSETS_TOOL_NAME = "preview_assets"
PREVIEW_CHART_TOOL_NAME = "show_chart"

PREVIEW_TOOL_NAMES = frozenset(
    {
        PREVIEW_FILE_TOOL_NAME,
        PREVIEW_FOLDER_TOOL_NAME,
        PREVIEW_ASSETS_TOOL_NAME,
        PREVIEW_CHART_TOOL_NAME,
    }
)

_MIME_TYPE_OVERRIDES = {
    ".7z": "application/x-7z-compressed",
    ".aac": "audio/aac",
    ".avif": "image/avif",
    ".avi": "video/x-msvideo",
    ".bmp": "image/bmp",
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".gif": "image/gif",
    ".gz": "application/gzip",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".html": "text/html",
    ".ico": "image/x-icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".json": "application/json",
    ".md": "text/markdown",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".ogg": "audio/ogg",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".py": "text/x-python",
    ".sh": "text/x-shellscript",
    ".svg": "image/svg+xml",
    ".tar": "application/x-tar",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".txt": "text/plain",
    ".webp": "image/webp",
    ".wav": "audio/wav",
    ".webm": "video/webm",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".zip": "application/zip",
}


def mime_type_for_path(path: str) -> str:
    """Resolve a stable MIME type from a file path, with a binary fallback."""

    suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    if suffix in _MIME_TYPE_OVERRIDES:
        return _MIME_TYPE_OVERRIDES[suffix]
    guessed_type, _ = mimetypes.guess_type(path)
    return guessed_type or "application/octet-stream"


def normalize_preview_resource(resource: Any) -> dict[str, Any]:
    """Normalize preview resources to the current public field names."""

    if not isinstance(resource, dict):
        return {}
    normalized = dict(resource)
    if normalized.get("type") != "efiles":
        return normalized

    files = normalized.get("files")
    if not isinstance(files, list):
        normalized["files"] = []
        return normalized

    normalized_files: list[dict[str, Any]] = []
    for file in files:
        if not isinstance(file, dict):
            continue
        normalized_file = dict(file)
        if "mimeType" not in normalized_file and "mime_type" in normalized_file:
            normalized_file["mimeType"] = normalized_file["mime_type"]
        if "clusterId" not in normalized_file and "cluster_id" in normalized_file:
            normalized_file["clusterId"] = normalized_file["cluster_id"]
        normalized_file.pop("mime_type", None)
        normalized_file.pop("cluster_id", None)
        normalized_files.append(normalized_file)
    normalized["files"] = normalized_files
    return normalized


def preview_event_from_tool_output(tool_name: Any, content: Any) -> dict[str, Any] | None:
    """Convert a preview tool result into the public preview SSE payload."""

    if tool_name not in PREVIEW_TOOL_NAMES:
        return None
    payload = parse_json_object(content)
    if not isinstance(payload, dict):
        return None
    cluster_id = str(os.getenv("CLUSTER_ID") or "").strip() or None

    if tool_name == PREVIEW_CHART_TOOL_NAME:
        resource = payload.get("resource") if payload.get("type") == PREVIEW_EVENT_TYPE else payload
        chart_resource = validate_chart_resource(resource)
        if chart_resource is None:
            return None
        return {"type": PREVIEW_EVENT_TYPE, "resource": chart_resource}

    if tool_name == PREVIEW_FOLDER_TOOL_NAME:
        path = _non_empty_string(payload.get("path"))
        if path is None:
            return None
        return {
            "type": PREVIEW_EVENT_TYPE,
            "resource": {
                "type": "folder",
                "description": _non_empty_string(payload.get("description")) or "",
                "folder": {"path": path, "clusterId": cluster_id},
            },
        }

    if tool_name == PREVIEW_FILE_TOOL_NAME:
        path = _non_empty_string(payload.get("path"))
        if path is None:
            return None
        filename = _non_empty_string(payload.get("filename")) or _filename(path)
        paths = [(filename, path)]
    else:
        path_list = payload.get("pathList")
        if not isinstance(path_list, list):
            return None
        paths = [(_filename(path), path) for item in path_list if (path := _non_empty_string(item))]

    if not paths:
        return None
    resource = {
        "type": "efiles",
        "files": [
            {
                "name": name,
                "mimeType": mime_type_for_path(path),
                "path": path,
                "clusterId": cluster_id,
            }
            for name, path in paths
        ],
    }
    if description := _non_empty_string(payload.get("description")):
        resource["description"] = description
    return {"type": PREVIEW_EVENT_TYPE, "resource": resource}


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _filename(path: str) -> str:
    return path.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1]


__all__ = [
    "PREVIEW_ASSETS_TOOL_NAME",
    "PREVIEW_CHART_TOOL_NAME",
    "PREVIEW_EVENT_TYPE",
    "PREVIEW_FILE_TOOL_NAME",
    "PREVIEW_FOLDER_TOOL_NAME",
    "PREVIEW_TOOL_NAMES",
    "mime_type_for_path",
    "normalize_preview_resource",
    "preview_event_from_tool_output",
]
