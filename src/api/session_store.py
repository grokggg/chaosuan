from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.api.legacy_history import normalize_legacy_history_messages
from src.utils import ensure_conversation_workspace, validate_conversation_id, validate_user_id
from src.utils.previews import normalize_preview_resource
from src.utils.todolists import normalize_todolist_resource
from src.utils.tool_call_ids import public_tool_call_id

SESSION_DIR_RELATIVE = Path(".data") / "user" / "sessions"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_HIDE_NEXT_USER_MESSAGE_KEY = "hideNextUserMessage"
_MESSAGE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_SESSION_STATUSES = (None, "in_progress", "interaction", "completed", "error", "cancelled")
_SESSION_WRITE_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(_SHANGHAI_TZ).isoformat(timespec="milliseconds")


def current_message_time() -> str:
    return datetime.now(_SHANGHAI_TZ).strftime(_MESSAGE_TIME_FORMAT)


def _session_dir() -> Path:
    home_dir = os.getenv("HOME", "").strip()
    if not home_dir:
        raise ValueError("HOME environment variable is required")
    return Path(home_dir) / SESSION_DIR_RELATIVE


def _user_session_dir(user_id: str) -> Path:
    return _session_dir() / validate_user_id(user_id)


def _session_file(user_id: str, conversation_id: str) -> Path:
    return _user_session_dir(user_id) / f"{validate_conversation_id(conversation_id)}.json"


def _state_session_file(user_id: str, conversation_id: str) -> Path:
    return _user_session_dir(user_id) / f"state_{validate_conversation_id(conversation_id)}.json"


def _default_session(user_id: str, conversation_id: str, now: str) -> dict[str, Any]:
    return {
        "userId": validate_user_id(user_id),
        "conversationId": conversation_id,
        "createAt": now,
        "updatedAt": now,
        "title": "New conversation",
        "status": None,
        "messages": [],
    }


def _load_session(user_id: str, conversation_id: str) -> dict[str, Any]:
    now = _now_iso()
    path = _session_file(user_id, conversation_id)
    if not path.exists():
        return _default_session(user_id, conversation_id, now)

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        return _default_session(user_id, conversation_id, now)

    payload["conversationId"] = conversation_id
    payload["userId"] = validate_user_id(user_id)
    payload.setdefault("createAt", now)
    payload.setdefault("updatedAt", now)
    payload["createAt"] = _to_shanghai_iso(str(payload.get("createAt") or now))
    payload["updatedAt"] = _to_shanghai_iso(str(payload.get("updatedAt") or now))
    payload.setdefault("title", "New conversation")
    payload["status"] = _normalize_session_status(payload.get("status"))
    if not isinstance(payload.get("messages"), list):
        payload["messages"] = []
    else:
        for message in payload["messages"]:
            if isinstance(message, dict):
                message["time"] = normalize_message_time(message.get("time") or payload.get("updatedAt") or now)
    return payload


def _normalize_session_status(status: Any) -> str | None:
    if status in _SESSION_STATUSES:
        return status
    return None


def _session_status(session: dict[str, Any]) -> str | None:
    return _normalize_session_status(session.get("status"))


def _write_session(user_id: str, session: dict[str, Any]) -> None:
    session_dir = _user_session_dir(user_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    conversation_id = validate_conversation_id(str(session["conversationId"]))
    path = session_dir / f"{conversation_id}.json"
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    with _SESSION_WRITE_LOCK:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(session, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temp_path, path)


def _json_fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _title_from_user(user: str) -> str:
    title = " ".join(user.strip().split())
    if not title:
        return "New conversation"
    return title[:40]


def _user_text_from_inputs(raw_inputs: Any) -> str:
    if not isinstance(raw_inputs, list):
        return ""
    return "\n\n".join(
        str(item.get("text") or "")
        for item in raw_inputs
        if isinstance(item, dict) and item.get("type") == "text" and str(item.get("text") or "")
    )


def _to_shanghai_iso(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return _now_iso()
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return normalized
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(_SHANGHAI_TZ).isoformat(timespec="milliseconds")


def normalize_message_time(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return current_message_time()

    normalized = value.strip()
    try:
        parsed = datetime.strptime(normalized, _MESSAGE_TIME_FORMAT)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return current_message_time()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(_SHANGHAI_TZ).strftime(_MESSAGE_TIME_FORMAT)


def _with_message_time(message: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    message["time"] = normalize_message_time(source.get("time"))
    return message


def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    role = message.get("role")
    if role == "user":
        normalized: dict[str, Any] = {"role": "user"}
        raw_inputs = message.get("inputs")
        if isinstance(raw_inputs, list):
            normalized["inputs"] = [dict(item) for item in raw_inputs if isinstance(item, dict)]
        return _with_message_time(normalized, message)

    if role == "assistant":
        return _with_message_time(_normalize_assistant_message(message), message)

    raise ValueError("session message field 'role' must be 'user' or 'assistant'")


def _normalize_assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    message_type = str(message.get("type") or "text")
    if message_type == "statistics":
        statistics = message.get("statistics")
        return {
            "role": "assistant",
            "id": str(message.get("id") or ""),
            "type": "statistics",
            "statistics": dict(statistics) if isinstance(statistics, dict) else {},
        }
    if message_type == "job-terminal-notice":
        return {
            "role": "assistant",
            "id": str(message.get("id") or ""),
            "type": "job-terminal-notice",
            "conversationId": str(message.get("conversationId") or ""),
            "clusterId": str(message.get("clusterId") or ""),
            "jobId": str(message.get("jobId") or ""),
        }
    if message_type == "reasoning":
        return {
            "role": "assistant",
            "id": str(message.get("id") or ""),
            "type": "reasoning",
            "reasoning": str(message.get("reasoning") or ""),
        }
    if message_type == "tool":
        tool = message.get("tool")
        return {
            "role": "assistant",
            "id": str(message.get("id") or ""),
            "type": "tool",
            "tool": _normalize_tool_payload(tool if isinstance(tool, dict) else {}),
        }
    if message_type in {"interaction", "todolist", "preview"}:
        resource = message.get("resource")
        normalized_resource = (
            normalize_todolist_resource(resource)
            if message_type == "todolist"
            else normalize_preview_resource(resource)
            if message_type == "preview"
            else dict(resource)
            if isinstance(resource, dict)
            else {}
        )
        normalized = {
            "role": "assistant",
            "id": str(message.get("id") or ""),
            "type": message_type,
            "resource": normalized_resource,
        }
        return normalized
    if message_type == "error":
        error = message.get("error")
        error_text = error.get("errorText") if isinstance(error, dict) else None
        return {
            "role": "assistant",
            "id": str(message.get("id") or ""),
            "type": "error",
            "error": {
                "errorText": str(error_text or message.get("errorText") or message.get("text") or ""),
            },
        }
    if message_type == "job-monitor":
        return {
            "role": "assistant",
            "id": str(message.get("id") or ""),
            "type": "job-monitor",
            "conversationId": str(message.get("conversationId") or ""),
            "clusterId": str(message.get("clusterId") or ""),
            "jobId": str(message.get("jobId") or ""),
            "taskId": str(message["taskId"]) if message.get("taskId") is not None else None,
            "enable": bool(message.get("enable", True)),
        }
    return {
        "role": "assistant",
        "id": str(message.get("id") or ""),
        "type": "text",
        "text": str(message.get("text") or ""),
    }


def _normalize_tool_payload(tool: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "toolCallId": public_tool_call_id(tool.get("toolCallId")),
        "name": str(tool.get("name") or ""),
        "input": tool.get("input"),
        "output": None if tool.get("output") is None else str(tool.get("output")),
    }
    description = tool.get("toolCallDescription")
    if description is not None:
        normalized["toolCallDescription"] = str(description)
    return normalized


def _append_session_message(
    user_id: str,
    conversation_id: str,
    message: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    with _SESSION_WRITE_LOCK:
        now = _now_iso()
        ensure_conversation_workspace(conversation_id)
        session = _load_session(user_id, conversation_id)
        messages = session["messages"]
        normalized = _normalize_message(message)
        if (
            normalized.get("role") == "assistant"
            and normalized.get("type") in {"job-monitor", "job-terminal-notice"}
        ):
            normalized["conversationId"] = conversation_id
        disabled_handoff: dict[str, Any] | None = None
        if normalized.get("role") == "user" and session.pop(_HIDE_NEXT_USER_MESSAGE_KEY, False):
            normalized["hidden"] = True
            disabled_handoff = _disable_latest_handoff(messages)
        index = len(messages)
        if normalized.get("role") == "assistant" and normalized.get("type") == "tool" and normalized.get("id"):
            for existing_index, existing in enumerate(messages):
                if (
                    isinstance(existing, dict)
                    and existing.get("role") == "assistant"
                    and existing.get("type") == "tool"
                    and existing.get("id") == normalized["id"]
                ):
                    # Keep the original call position and time when its result arrives.
                    index = existing_index
                    normalized["time"] = existing.get("time", normalized["time"])
                    break
        if index == len(messages):
            messages.append(normalized)
        else:
            messages[index] = normalized
        user = _user_text_from_inputs(normalized.get("inputs")) if normalized.get("role") == "user" else ""
        if user and session.get("title") in (None, "", "New conversation"):
            session["title"] = _title_from_user(str(user))
        session["updatedAt"] = now
        _write_session(user_id, session)
        return index, disabled_handoff


def append_session_message(user_id: str, conversation_id: str, message: dict[str, Any]) -> int:
    index, _ = _append_session_message(user_id, conversation_id, message)
    return index


def append_session_message_with_handoff(
    user_id: str,
    conversation_id: str,
    message: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    return _append_session_message(user_id, conversation_id, message)


def _disable_latest_handoff(messages: list[Any]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        if message.get("type") in {"statistics", "todolist"}:
            continue
        if message.get("type") == "job-monitor":
            message["enable"] = False
            return dict(message)
        elif message.get("type") == "interaction":
            resource = message.get("resource")
            if isinstance(resource, dict):
                resource["enable"] = False
            return dict(message)
        return None
    return None


def mark_next_user_message_hidden(user_id: str, conversation_id: str) -> None:
    session = _load_session(user_id, conversation_id)
    session[_HIDE_NEXT_USER_MESSAGE_KEY] = True
    session["updatedAt"] = _now_iso()
    _write_session(user_id, session)


def update_resource_card_interaction_selection(
    user_id: str,
    conversation_id: str,
    interaction_id: str,
    selected_value: str,
) -> None:
    with _SESSION_WRITE_LOCK:
        session = _load_session(user_id, conversation_id)
        messages = session.get("messages")
        if not isinstance(messages, list):
            raise ValueError("conversation messages not found")

        interaction: dict[str, Any] | None = None
        for message in messages:
            if (
                isinstance(message, dict)
                and message.get("role") == "assistant"
                and message.get("type") == "interaction"
                and str(message.get("id") or "") == interaction_id
            ):
                interaction = message
                break
        if interaction is None:
            raise ValueError(f"resource card interaction not found: {interaction_id}")

        resource = interaction.get("resource")
        if not isinstance(resource, dict) or resource.get("type") != "resource_card":
            raise ValueError(f"interaction is not a resource card: {interaction_id}")
        option_type = resource.get("optionType")
        if option_type == "single":
            options = resource.get("options")
            if not isinstance(options, list):
                raise ValueError(f"resource card options not found: {interaction_id}")
            matching_options = [
                option
                for option in options
                if isinstance(option, dict) and str(option.get("value") or "") == selected_value
            ]
            if len(matching_options) != 1:
                raise ValueError(f"resource card option value must match exactly once: {selected_value}")

            for option in options:
                if isinstance(option, dict):
                    option["selected"] = option is matching_options[0]
        elif option_type != "link":
            raise ValueError(f"unsupported resource card option type: {option_type}")

        resource["enable"] = False
        session["updatedAt"] = _now_iso()
        _write_session(user_id, session)


def update_agent_state_messages(user_id: str, conversation_id: str, messages: list[dict[str, Any]]) -> bool:
    now = _now_iso()
    path = _state_session_file(user_id, conversation_id)
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            session = json.load(file)
        if not isinstance(session, dict):
            session = {}
    else:
        session = {}

    fingerprint = _json_fingerprint(messages)
    if session.get("agentMessagesFingerprint") == fingerprint:
        return False

    session["conversationId"] = conversation_id
    session["userId"] = validate_user_id(user_id)
    session["agentMessages"] = messages
    session["agentMessagesFingerprint"] = fingerprint
    session["agentMessagesUpdatedAt"] = now
    temp_path = path.with_suffix(".json.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(session, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temp_path, path)
    return True


def session_needs_title(user_id: str, conversation_id: str) -> bool:
    session = _load_session(user_id, conversation_id)
    title = session.get("title")
    messages = session.get("messages")
    return title in (None, "", "New conversation") and isinstance(messages, list) and not messages


def update_session_title(user_id: str, conversation_id: str, title: str) -> None:
    normalized = " ".join(title.strip().split())
    if not normalized:
        return
    session = _load_session(user_id, conversation_id)
    session["title"] = normalized[:40]
    session["updatedAt"] = _now_iso()
    _write_session(user_id, session)


def update_session_status(user_id: str, conversation_id: str, status: str | None) -> bool:
    if status not in _SESSION_STATUSES:
        raise ValueError(
            "session status must be one of: null, in_progress, interaction, completed, error, cancelled"
        )

    with _SESSION_WRITE_LOCK:
        session = _load_session(user_id, conversation_id)
        if session.get("status") == status:
            return False

        session["status"] = status
        session["updatedAt"] = _now_iso()
        _write_session(user_id, session)
        return True


def read_session(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    path = _session_file(user_id, conversation_id)
    if not path.exists():
        return None
    session = _load_session(user_id, conversation_id)
    messages = session.get("messages")
    if not isinstance(messages, list):
        return session
    normalized_session = dict(session)
    normalized_session["messages"] = normalize_legacy_history_messages(messages)
    return normalized_session


def delete_session(user_id: str, conversation_id: str) -> bool:
    removed = False
    for path in (_session_file(user_id, conversation_id), _state_session_file(user_id, conversation_id)):
        if not path.exists():
            continue
        path.unlink()
        removed = True
    return removed


def create_session(user_id: str, conversation_id: str) -> dict[str, Any]:
    session = _load_session(user_id, conversation_id)
    _write_session(user_id, session)
    ensure_conversation_workspace(conversation_id)
    return session


def list_sessions(user_id: str) -> list[dict[str, Any]]:
    session_dir = _user_session_dir(user_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    sessions: list[dict[str, Any]] = []
    for path in sorted(session_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.name.startswith(("state_", "last_call_")):
            continue
        conversation_id = path.stem
        try:
            session = _load_session(user_id, conversation_id)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        messages = session.get("messages")
        visible_message_count = (
            sum(
                1
                for message in messages
                if not isinstance(message, dict) or message.get("type") != "statistics"
            )
            if isinstance(messages, list)
            else 0
        )
        sessions.append(
            {
                "conversationId": session.get("conversationId"),
                "createAt": session.get("createAt"),
                "updatedAt": session.get("updatedAt"),
                "title": session.get("title"),
                "status": _session_status(session),
                "messageCount": visible_message_count,
            }
        )
    return sessions


__all__ = [
    "append_session_message",
    "append_session_message_with_handoff",
    "create_session",
    "current_message_time",
    "delete_session",
    "ensure_conversation_workspace",
    "list_sessions",
    "mark_next_user_message_hidden",
    "normalize_message_time",
    "read_session",
    "session_needs_title",
    "update_agent_state_messages",
    "update_resource_card_interaction_selection",
    "update_session_status",
    "update_session_title",
]
