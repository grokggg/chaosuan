"""Tool for opening an allowlisted generic iframe card."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import uuid4

import yaml
from langchain.tools import tool
from langchain_core.tools import ToolException

from src.utils.iframe_cards import MAX_IFRAME_INIT_DATA_BYTES, validate_iframe_resource

_IFRAME_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "widgets.yaml"


def _configured_iframe_origins() -> set[str]:
    try:
        config = yaml.safe_load(_IFRAME_CONFIG_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ToolException(
            "Iframe cards are unavailable in this deployment. Do not retry; reply with the page URL as a markdown link."
        ) from exc
    if not isinstance(config, dict):
        raise ToolException(
            "Iframe cards are unavailable in this deployment. Do not retry; reply with the page URL as a markdown link."
        )
    origins = config.get("iframe_allowed_origins", [])
    if not isinstance(origins, list) or any(not isinstance(origin, str) for origin in origins):
        raise ToolException(
            "Iframe cards are unavailable in this deployment. Do not retry; reply with the page URL as a markdown link."
        )
    return {origin.strip().rstrip("/").lower() for origin in origins if origin.strip()}


def _validate_url_origin(url: str) -> None:
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise ToolException("Iframe URL is invalid.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ToolException("Iframe URL must be an HTTP(S) URL without credentials or a fragment.")
    origin = f"{parsed.scheme}://{parsed.netloc}".lower()
    allowed_origins = _configured_iframe_origins()
    if not allowed_origins:
        raise ToolException(
            "Iframe cards are disabled in this deployment. Do not retry; reply with the page URL as a markdown link."
        )
    if origin not in allowed_origins:
        raise ToolException(
            "This page origin is not enabled for iframe cards. Do not retry; reply with the page URL as a markdown link."
        )


# @tool(
#     "show_iframe",
#     description=(
#         "Open a generic iframe card using a URL returned by a configured MCP tool. Pass the exact URL "
#         "returned by that tool and any JSON object needed by the page as initData. Do not invent URLs "
#         "or claim the page loaded. Always repeat the page URL as a markdown link in your reply, since "
#         "some chat surfaces cannot render iframe cards. The server checks the URL origin against "
#         "config/widgets.yaml."
#     ),
# )
async def show_iframe(
    url: Annotated[str, "Exact iframe URL returned by the configured MCP tool."],
    init_data: Annotated[dict[str, Any], "JSON object passed to the iframe page as initData."],
    title: Annotated[str, "Short title shown with the iframe card."] = "交互页面",
    description: Annotated[str, "Brief explanation of the page and its purpose."] = "",
    source: Annotated[str, "Card source identifier, e.g. earth for the Cesium viewer."] = "earth",
    interactive: Annotated[bool, "True emits an interaction event (blocking); False emits a preview event."] = True,
) -> str:
    normalized_url = url.strip()
    _validate_url_origin(normalized_url)
    try:
        encoded_init_data = json.dumps(
            init_data,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ToolException("initData must be JSON serializable.") from exc
    if len(encoded_init_data) > MAX_IFRAME_INIT_DATA_BYTES:
        raise ToolException("initData exceeds the 64KB limit.")

    resource = {
        "type": "iframe",
        "title": title.strip(),
        "description": description.strip(),
        "iframe": {
            "source": source.strip() or "earth",
            "url": normalized_url,
            "data": init_data,
        },
    }
    normalized_resource = validate_iframe_resource(resource)
    if normalized_resource is None:
        raise ToolException("Iframe resource is invalid or exceeds the 64KB initData limit.")
    # 会议约定：resource 下同时暴露顶层 url，前端据此显示"预览地址"
    normalized_resource["url"] = normalized_url
    event_type = "interaction" if interactive else "preview"
    id_prefix = "interaction" if interactive else "iframe"
    payload = {
        "type": event_type,
        "id": f"{id_prefix}_{uuid4().hex}",
        "resource": normalized_resource,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


__all__ = ["show_iframe"]
