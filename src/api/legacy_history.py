"""Read-only adapters from legacy session messages to the current history contract."""

from __future__ import annotations

from typing import Any

from src.utils.interactions import INTERACTION_EVENT_TYPE, parse_json_object
from src.utils.previews import (
    PREVIEW_ASSETS_TOOL_NAME,
    PREVIEW_FILE_TOOL_NAME,
    PREVIEW_FOLDER_TOOL_NAME,
    PREVIEW_TOOL_NAMES,
    normalize_preview_resource,
    preview_event_from_tool_output,
)
from src.utils.todolists import TODOLIST_ID_TYPE, WRITE_TODOS_TOOL_NAME, todolist_resource

_SHOW_RESOURCE_CARDS_TOOL_NAME = "show_resource_cards"
_QUEUE_CARD_TITLE = "选择要使用的计算队列"
_QUEUE_CARD_DESCRIPTION = "请选择用于本次计算的计算队列"
_LEGACY_PREVIEW_MESSAGE_TYPES = {
    PREVIEW_FILE_TOOL_NAME: "preview-file",
    PREVIEW_ASSETS_TOOL_NAME: "preview-assets-list",
    PREVIEW_FOLDER_TOOL_NAME: "preview-folder",
}


def _legacy_user_message(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("role") != "user" or isinstance(message.get("inputs"), list):
        return None

    inputs: list[dict[str, Any]] = []
    text = message.get("text")
    if isinstance(text, str):
        inputs.append({"type": "text", "text": text})

    files = message.get("files")
    raw_efiles = files.get("efile") if isinstance(files, dict) else None
    if isinstance(raw_efiles, list):
        for raw_efile in raw_efiles:
            if not isinstance(raw_efile, dict):
                continue
            cluster_id = raw_efile.get("clusterId")
            if not isinstance(cluster_id, str | int) or isinstance(cluster_id, bool):
                cluster_id = ""
            inputs.append(
                {
                    "type": "efile",
                    "resource": {
                        "name": str(raw_efile.get("name") or ""),
                        "mimeType": str(raw_efile.get("mimeType") or raw_efile.get("type") or ""),
                        "url": str(raw_efile.get("path") or ""),
                        "clusterId": cluster_id,
                    },
                }
            )

    if not inputs:
        return None
    return {
        "role": "user",
        "inputs": inputs,
        "time": message.get("time"),
    }


def _legacy_tool(message: Any, tool_name: str) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("role") != "assistant" or message.get("type") != "tool":
        return None
    tool = message.get("tool")
    if not isinstance(tool, dict) or tool.get("name") != tool_name:
        return None
    return tool


def _preview_history_message(message: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        **event,
        "time": message.get("time"),
    }


def _legacy_preview_message(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None

    message_type = message.get("type")
    if message_type == "preview-file":
        event = preview_event_from_tool_output(
            PREVIEW_FILE_TOOL_NAME,
            {"filename": message.get("filename"), "path": message.get("path")},
        )
    elif message_type == "preview-assets-list":
        event = preview_event_from_tool_output(
            PREVIEW_ASSETS_TOOL_NAME,
            {"pathList": message.get("pathList")},
        )
    elif message_type == "preview-folder":
        event = preview_event_from_tool_output(
            PREVIEW_FOLDER_TOOL_NAME,
            {"path": message.get("path"), "description": message.get("description")},
        )
    else:
        return None
    return _preview_history_message(message, event) if event is not None else None


def _legacy_preview_tool_name(message: Any) -> str | None:
    if not isinstance(message, dict) or message.get("role") != "assistant" or message.get("type") != "tool":
        return None
    tool = message.get("tool")
    if not isinstance(tool, dict):
        return None
    tool_name = tool.get("name")
    return tool_name if isinstance(tool_name, str) and tool_name in PREVIEW_TOOL_NAMES else None


def _legacy_preview_tool_message(message: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    tool = message.get("tool")
    if not isinstance(tool, dict):
        return None
    event = preview_event_from_tool_output(tool_name, tool.get("output"))
    return _preview_history_message(message, event) if event is not None else None


def _has_following_legacy_preview(messages: list[Any], index: int, tool_name: str) -> bool:
    if index + 1 >= len(messages):
        return False
    following = messages[index + 1]
    if not isinstance(following, dict) or following.get("type") != _LEGACY_PREVIEW_MESSAGE_TYPES[tool_name]:
        return False
    return _legacy_preview_message(following) is not None


def _legacy_todolist_message(message: Any) -> dict[str, Any] | None:
    tool = _legacy_tool(message, WRITE_TODOS_TOOL_NAME)
    if tool is None:
        return None
    tool_input = tool.get("input")
    if not isinstance(tool_input, dict):
        return None
    todos = tool_input.get("todos")
    if not isinstance(todos, list):
        return None
    return {
        "role": "assistant",
        "type": "todolist",
        "resource": todolist_resource(todos),
        "time": message.get("time"),
    }


def _legacy_queue_card_resource(output: Any) -> dict[str, Any] | None:
    payload = parse_json_object(output)
    if payload is None:
        return None

    if payload.get("type") == "resource_card" and isinstance(payload.get("options"), list):
        return payload

    cards = payload.get("cards")
    if not isinstance(cards, list):
        return None
    options: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        name = str(card.get("nameCn") or card.get("name") or "")
        options.append(
            {
                "value": str(card.get("value") or name),
                "label": {"name": name},
                "selected": bool(card.get("selected", False)),
                "description": str(card.get("desc") or card.get("description") or ""),
                "type": str(card.get("resourceType") or card.get("type") or "queue"),
                "id": str(card.get("id") or ""),
            }
        )
    return {
        "type": "resource_card",
        "title": str(payload.get("title") or _QUEUE_CARD_TITLE),
        "description": str(payload.get("description") or _QUEUE_CARD_DESCRIPTION),
        "optionType": str(payload.get("optionType") or "single"),
        "showUserMessage": bool(payload.get("showUserMessage", False)),
        "enable": bool(payload.get("enable", True)),
        "options": options,
    }


def _legacy_interaction_message(message: Any) -> dict[str, Any] | None:
    tool = _legacy_tool(message, _SHOW_RESOURCE_CARDS_TOOL_NAME)
    if tool is None:
        return None
    resource = _legacy_queue_card_resource(tool.get("output"))
    if resource is None:
        return None
    return {
        "role": "assistant",
        "type": INTERACTION_EVENT_TYPE,
        "resource": resource,
        "time": message.get("time"),
    }


def _used_part_indexes(messages: list[Any], part_type: str) -> set[int]:
    prefix = f"{part_type}_"
    indexes: set[int] = set()
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        part_id = message.get("id")
        if not isinstance(part_id, str) or not part_id.startswith(prefix):
            continue
        suffix = part_id.removeprefix(prefix)
        if suffix.isdigit():
            indexes.add(int(suffix))
    return indexes


def normalize_legacy_history_messages(messages: list[Any]) -> list[Any]:
    """Return current-contract history messages without mutating legacy storage."""

    used_indexes = {
        TODOLIST_ID_TYPE: _used_part_indexes(messages, TODOLIST_ID_TYPE),
        INTERACTION_EVENT_TYPE: _used_part_indexes(messages, INTERACTION_EVENT_TYPE),
    }
    next_indexes = {TODOLIST_ID_TYPE: 1, INTERACTION_EVENT_TYPE: 1}
    normalized_messages: list[Any] = []

    for index, message in enumerate(messages):
        normalized_user_message = _legacy_user_message(message)
        if normalized_user_message is not None:
            normalized_messages.append(normalized_user_message)
            continue

        if isinstance(message, dict) and message.get("role") == "assistant" and message.get("type") == "preview":
            normalized_preview_message = dict(message)
            normalized_preview_message["resource"] = normalize_preview_resource(message.get("resource"))
            normalized_messages.append(normalized_preview_message)
            continue

        preview_tool_name = _legacy_preview_tool_name(message)
        if preview_tool_name is not None:
            if _has_following_legacy_preview(messages, index, preview_tool_name):
                continue
            normalized_preview_tool = _legacy_preview_tool_message(message, preview_tool_name)
            if normalized_preview_tool is not None:
                normalized_messages.append(normalized_preview_tool)
                continue

        normalized_preview = _legacy_preview_message(message)
        if normalized_preview is not None:
            normalized_messages.append(normalized_preview)
            continue

        normalized = _legacy_todolist_message(message)
        part_type = TODOLIST_ID_TYPE
        if normalized is None:
            normalized = _legacy_interaction_message(message)
            part_type = INTERACTION_EVENT_TYPE
        if normalized is None:
            normalized_messages.append(message)
            continue

        next_index = next_indexes[part_type]
        while next_index in used_indexes[part_type]:
            next_index += 1
        used_indexes[part_type].add(next_index)
        next_indexes[part_type] = next_index + 1
        normalized["id"] = f"{part_type}_{next_index}"
        normalized_messages.append(normalized)

    return normalized_messages


__all__ = ["normalize_legacy_history_messages"]
