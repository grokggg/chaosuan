from __future__ import annotations

import json
import os
import time
from typing import Any

from fastapi import APIRouter, Query

from src.api.output_files import extract_output_files
from src.api.session_store import _session_file, read_session
from src.logger import get_logger
from src.utils import load_agent_config, validate_conversation_id, validate_user_id

router = APIRouter(prefix="/user/agent/sessions", tags=["user-agent"])
logger = get_logger(__name__)


def _agent_name() -> str:
    name = os.getenv("AGENT_NAME", "").strip()
    if name:
        return name
    try:
        configured_name = load_agent_config().get("name")
        return configured_name.strip() if isinstance(configured_name, str) else ""
    except (OSError, ValueError):
        # Optional display metadata must not prevent access to saved files.
        logger.warning("Could not load agent name for output-files", exc_info=True)
        return ""


@router.get("/{conversation_id}/output-files")
def get_output_files(
    conversation_id: str,
    user_id: str = Query(..., alias="user_id"),
    file_name: str | None = Query(None, alias="fileName"),
) -> dict[str, Any]:
    """List previewed files; url/clusterId are locators for the existing file service."""
    started_at = time.monotonic()
    logger.info(
        "output-files request params=%s",
        json.dumps({"conversation_id": conversation_id, "user_id": user_id, "fileName": file_name}, ensure_ascii=False),
    )
    try:
        user_id = validate_user_id(user_id.strip())
        conversation_id = validate_conversation_id(conversation_id)
        if user_id in {".", ".."} or conversation_id in {".", ".."}:
            raise ValueError("invalid user_id or conversationId")
        session_path = _session_file(user_id, conversation_id)
        logger.info(
            "output-files session_lookup conversation_id=%r user_id=%r agent_id=%r hostname=%r session_path=%s exists=%s",
            conversation_id,
            user_id,
            os.getenv("AGENT_ID", "").strip(),
            os.getenv("HOSTNAME", ""),
            session_path,
            session_path.is_file(),
        )
        session = read_session(user_id, conversation_id)
        messages = session.get("messages", []) if session else []
        previews = [
            message
            for message in messages
            if isinstance(message, dict) and message.get("role") == "assistant" and message.get("type") == "preview"
        ]
        file_previews = [
            message["resource"]
            for message in previews
            if isinstance(message.get("resource"), dict) and message["resource"].get("type") == "efiles"
        ]
        file_entries = sum(
            len(resource["files"]) for resource in file_previews if isinstance(resource.get("files"), list)
        )
        logger.info(
            "output-files history_loaded conversation_id=%r user_id=%r session_found=%s "
            "message_count=%d preview_count=%d efiles_preview_count=%d file_entries=%d",
            conversation_id,
            user_id,
            session is not None,
            len(messages),
            len(previews),
            len(file_previews),
            file_entries,
        )
        items = extract_output_files(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            agent_id=os.getenv("AGENT_ID", "").strip(),
            agent_name=_agent_name() if session else "",
        )
        before_filter = len(items)
        keyword = (file_name or "").strip().casefold()
        if keyword:
            items = [item for item in items if keyword in item["name"].casefold()]
        logger.info(
            "output-files file_filter conversation_id=%r user_id=%r file_entries=%d extracted=%d "
            "invalid_or_duplicate=%d keyword=%r filtered_out=%d returned=%d",
            conversation_id,
            user_id,
            file_entries,
            before_filter,
            file_entries - before_filter,
            keyword,
            before_filter - len(items),
            len(items),
        )
        reason = (
            "session_missing"
            if session is None
            else "no_file_previews"
            if before_filter == 0
            else "no_filename_match"
            if not items
            else "ok"
        )
        result = {"code": 0, "msg": "success", "data": {"items": items, "total": len(items)}}
        logger.info(
            "output-files response conversation_id=%r user_id=%r before_filter=%d total=%d reason=%s elapsed_ms=%d output=%s",
            conversation_id,
            user_id,
            before_filter,
            len(items),
            reason,
            round((time.monotonic() - started_at) * 1000),
            json.dumps(result, ensure_ascii=False),
        )
        return result
    except Exception as exc:
        logger.exception("Failed to list output files conversation_id=%r user_id=%r", conversation_id, user_id)
        return {"code": 1, "msg": str(exc), "data": None}


__all__ = ["router"]
