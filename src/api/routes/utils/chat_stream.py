from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessageChunk, ToolMessage

from src.agents.agent import load_agent_config
from src.api.routes.utils.payload import parse_json_payload_or_none
from src.llm import resolve_model_ref
from src.middleware.tool_description_param_middleware import split_tool_call_description
from src.utils.chart_cards import validate_chart_resource
from src.utils.iframe_cards import iframe_event_from_tool_output, validate_iframe_resource
from src.utils.interactions import INTERACTION_EVENT_TYPE
from src.utils.previews import PREVIEW_EVENT_TYPE, normalize_preview_resource
from src.utils.streaming import (
    CUSTOM_AI_MESSAGE_DELTA,
    CUSTOM_JOB_MONITOR,
    CUSTOM_RESPONSE_FINISH_REASON,
    CUSTOM_TOOL_CALL_SYNC,
    CUSTOM_TOOL_HANDOFF_FINISH,
)
from src.utils.todolists import TODOLIST_EVENT_TYPE, normalize_todolist_resource


def sse_message(payload: str) -> str:
    return f"data: {payload}\n\n"


def resolve_configured_model_name() -> str:
    config = load_agent_config()
    llm_config = config.get("llm", {})
    return resolve_model_ref(llm_config if isinstance(llm_config, dict) else None)


def serialize_usage(raw_usage: Any) -> dict[str, Any] | None:
    if not isinstance(raw_usage, dict):
        return None
    prompt_tokens = raw_usage.get("prompt_tokens", raw_usage.get("input_tokens"))
    completion_tokens = raw_usage.get("completion_tokens", raw_usage.get("output_tokens"))
    total_tokens = raw_usage.get("total_tokens")
    if total_tokens is None and isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        total_tokens = prompt_tokens + completion_tokens
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    return {key: value for key, value in usage.items() if value is not None}


def _strip_think_close_tag(text: str) -> str:
    return text.replace("</think>", "")


def extract_text_content(message: AIMessageChunk) -> str:
    return _strip_think_close_tag(message.content) if isinstance(message.content, str) else ""


def extract_reasoning_content(message: AIMessageChunk) -> str:
    reasoning_content = message.additional_kwargs.get("reasoning_content")
    if isinstance(reasoning_content, str) and reasoning_content:
        return _strip_think_close_tag(reasoning_content)
    reasoning = message.additional_kwargs.get("reasoning")
    return _strip_think_close_tag(reasoning) if isinstance(reasoning, str) else ""


def extract_tool_message_content(message: ToolMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    if isinstance(message.content, list):
        parts: list[str] = []
        for item in message.content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(message.content)


def extract_custom_ai_message_delta(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    if payload.get("type") != CUSTOM_AI_MESSAGE_DELTA:
        return ""
    if payload.get("visible") is False:
        return ""
    content = payload.get("content")
    return content if isinstance(content, str) else ""


def extract_custom_job_monitor(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("type") != CUSTOM_JOB_MONITOR:
        return None
    tool_call_id = payload.get("toolCallId")
    tool_name = payload.get("toolName")
    output = payload.get("output")
    if not tool_call_id or not tool_name or not isinstance(output, dict):
        return None
    return {
        "toolCallId": str(tool_call_id),
        "toolName": str(tool_name),
        "output": output,
        "taskId": str(payload["taskId"]) if payload.get("taskId") is not None else None,
    }


def extract_custom_tool_handoff_finish(payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("type") != CUSTOM_TOOL_HANDOFF_FINISH:
        return None
    finish_reason = payload.get("finishReason")
    return str(finish_reason) if finish_reason in {"job_monitor", "resource_cards"} else None


def extract_custom_response_finish_reason(payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("type") != CUSTOM_RESPONSE_FINISH_REASON:
        return None
    finish_reason = payload.get("finishReason")
    return str(finish_reason) if finish_reason == "interaction" else None


def extract_custom_interaction(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("type") != INTERACTION_EVENT_TYPE:
        return None
    resource = payload.get("resource")
    if not isinstance(resource, dict):
        return None
    event: dict[str, Any] = {"type": INTERACTION_EVENT_TYPE, "resource": resource}
    event_id = payload.get("id")
    if isinstance(event_id, str) and event_id.strip():
        event["id"] = event_id.strip()
    return event


def extract_custom_iframe(payload: Any) -> dict[str, Any] | None:
    """Validate the standalone iframe event used by the generic card protocol."""

    return iframe_event_from_tool_output(payload)


def extract_custom_todolist(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("type") != TODOLIST_EVENT_TYPE:
        return None
    resource = payload.get("resource")
    if not isinstance(resource, dict):
        return None
    return {
        "type": TODOLIST_EVENT_TYPE,
        "resource": normalize_todolist_resource(resource),
    }


def extract_custom_preview(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("type") != PREVIEW_EVENT_TYPE:
        return None
    resource = payload.get("resource")
    if not isinstance(resource, dict) or resource.get("type") not in {
        "chart",
        "efiles",
        "folder",
        "iframe",
    }:
        return None
    if resource.get("type") == "chart":
        chart_resource = validate_chart_resource(resource)
        if chart_resource is None:
            return None
        resource = chart_resource
    elif resource.get("type") == "iframe":
        iframe_resource = validate_iframe_resource(resource)
        if iframe_resource is None:
            return None
        resource = iframe_resource
    event: dict[str, Any] = {"type": PREVIEW_EVENT_TYPE, "resource": normalize_preview_resource(resource)}
    event_id = payload.get("id")
    if isinstance(event_id, str) and event_id.strip():
        event["id"] = event_id.strip()
    else:
        event["id"] = f"preview_{uuid4().hex}"
    return event


def extract_custom_tool_call_sync(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != CUSTOM_TOOL_CALL_SYNC:
        return None

    raw_tool_call_id = payload.get("toolCallId")
    raw_tool_name = payload.get("toolName")
    if not raw_tool_call_id or not raw_tool_name:
        return None

    tool_record = {
        "toolCallId": str(raw_tool_call_id),
        "name": str(raw_tool_name),
        "input": payload.get("input"),
        "output": "" if payload.get("output") is None else str(payload.get("output")),
    }
    description = payload.get("toolCallDescription")
    if description is not None:
        tool_record["toolCallDescription"] = str(description)
    return tool_record


def extract_tool_call_deltas(message: AIMessageChunk) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for chunk in message.tool_call_chunks:
        function_payload: dict[str, Any] = {}
        if chunk.get("name") is not None:
            function_payload["name"] = chunk.get("name")
        if chunk.get("args") is not None:
            function_payload["arguments"] = chunk.get("args")

        tool_delta: dict[str, Any] = {
            "index": chunk.get("index", 0) or 0,
            "type": "function",
            "function": function_payload,
        }
        if chunk.get("id") is not None:
            tool_delta["id"] = chunk.get("id")
        tool_calls.append(tool_delta)
    return tool_calls


def upsert_tool_record(
    records: dict[str, dict[str, Any]],
    order: list[str],
    tool_id: str,
    *,
    name: str | None = None,
    arguments_delta: str | None = None,
    result: str | None = None,
) -> dict[str, Any]:
    record = records.get(tool_id)
    if record is None:
        record = {"id": tool_id, "name": None, "arguments": "", "description": None, "result": None}
        records[tool_id] = record
        order.append(tool_id)
    if name:
        record["name"] = name
    if arguments_delta:
        record["arguments"] = f"{record.get('arguments') or ''}{arguments_delta}"
        _, description = format_tool_arguments(
            record["arguments"],
            tool_name=record.get("name"),
        )
        if description:
            record["description"] = description
    if result is not None:
        record["result"] = result
    return record


def _fallback_tool_call_description(tool_name: Any, arguments: Any) -> str | None:
    if tool_name != "web_search":
        return None

    parsed_arguments = parse_json_payload_or_none(arguments) if isinstance(arguments, str) else arguments
    if not isinstance(parsed_arguments, dict):
        return None

    query = parsed_arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    return f"搜索{query.strip()}"


def format_tool_arguments(
    raw_arguments: str,
    *,
    tool_name: Any = None,
) -> tuple[str, str | None]:
    arguments, description = split_tool_call_description(raw_arguments)
    description = description or _fallback_tool_call_description(tool_name, arguments)
    if isinstance(arguments, str):
        return arguments, description
    return json.dumps(arguments, ensure_ascii=False), description


def resolve_tool_call_id(
    tool_call: dict[str, Any],
    index_to_id: dict[int, str],
) -> str:
    index = int(tool_call.get("index", 0) or 0)
    raw_id = tool_call.get("id")
    if isinstance(raw_id, str) and raw_id:
        index_to_id[index] = raw_id
        return raw_id
    return index_to_id.get(index, str(index))


def resolve_tool_record_id(
    records: dict[str, dict[str, Any]],
    tool_id: str,
    *,
    name: str | None = None,
) -> str:
    if tool_id in records:
        return tool_id
    pending = [
        record_id
        for record_id, record in records.items()
        if record.get("result") is None and (name is None or record.get("name") in (None, name))
    ]
    if len(pending) == 1:
        return pending[0]
    return tool_id


def serialize_tool_records(records: dict[str, dict[str, Any]], order: list[str]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for tool_id in order:
        record = records.get(tool_id)
        if not record:
            continue
        input_value, description = format_tool_arguments(
            record.get("arguments") or "",
            tool_name=record.get("name"),
        )
        if description:
            record["description"] = description
        item = {
            "toolCallId": record.get("id"),
            "name": record.get("name"),
            "input": input_value or "",
            "output": record.get("result"),
        }
        if record.get("description"):
            item["toolCallDescription"] = record["description"]
        arguments_json = parse_json_payload_or_none(item["input"])
        if arguments_json is not None:
            item["input"] = arguments_json
        serialized.append(item)
    return serialized


__all__ = [
    "extract_custom_ai_message_delta",
    "extract_custom_job_monitor",
    "extract_custom_response_finish_reason",
    "extract_custom_interaction",
    "extract_custom_iframe",
    "extract_custom_preview",
    "extract_custom_todolist",
    "extract_reasoning_content",
    "extract_text_content",
    "extract_custom_tool_call_sync",
    "extract_custom_tool_handoff_finish",
    "extract_tool_call_deltas",
    "extract_tool_message_content",
    "format_tool_arguments",
    "resolve_configured_model_name",
    "resolve_tool_call_id",
    "resolve_tool_record_id",
    "serialize_tool_records",
    "serialize_usage",
    "sse_message",
    "upsert_tool_record",
]
