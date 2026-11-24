from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile

from src.agents.manager import AGENTS
from src.llm import LLMModel, LLMProvider, load_llm_registry, resolve_model, sanitize_llm_args_for_model
from src.logger import get_logger
from src.skills import load_skill_registries
from src.utils import (
    PROJECT_ROOT,
    PROMPT_PATH,
    bool_or_false,
    ensure_conversation_workspace,
    load_agent_config,
    string_or_empty,
)

router = APIRouter(prefix="/user/agent", tags=["user-agent-general"])
logger = get_logger(__name__)
UPLOAD_CHUNK_SIZE = 1024 * 1024
_CREATE_MARKER_STATUS: bool | None = None


def _safe_upload_filename(filename: str | None) -> str:
    raw_name = (filename or "upload").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not raw_name or raw_name in {".", ".."}:
        return "upload"
    safe_name = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in raw_name).strip("._")
    return safe_name or "upload"


def _unique_upload_path(conversation_id: str, filename: str) -> Path:
    workspace = ensure_conversation_workspace(conversation_id)
    candidate = workspace / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem or "upload"
    suffix = candidate.suffix
    for index in range(1, 1000):
        indexed = workspace / f"{stem}_{index}{suffix}"
        if not indexed.exists():
            return indexed
    raise ValueError(f"too many uploaded files named {filename}")


def _serialize_model(model: LLMModel) -> dict[str, Any]:
    return {
        "name": model.name,
        "description": model.description,
        "reasoning": model.reasoning,
        "contextWindow": model.context_window,
        "args": _serialize_llm_args(sanitize_llm_args_for_model(model, model.args)),
    }


def _serialize_provider(provider: LLMProvider) -> dict[str, Any]:
    return {
        "name": provider.name,
        "logo": provider.logo,
        "models": [_serialize_model(model) for model in provider.models if not model.internal],
    }


def _get_configured_model(config: dict[str, Any]) -> str:
    return str(config["llm"]["model"]).strip().rsplit("/", 1)[-1]


def _get_configured_model_logo(config: dict[str, Any]) -> str:
    return str(config["llm"]["logo"]).strip()


def _get_configured_llm_args(config: dict[str, Any]) -> dict[str, Any]:
    llm_config = config["llm"]
    saved_args = {str(key): value for key, value in llm_config.items() if key not in {"model", "logo"}}
    model = resolve_model(llm_config if isinstance(llm_config, dict) else None)
    return _serialize_llm_args(sanitize_llm_args_for_model(model, saved_args))


def _serialize_llm_args(args: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in args.items():
        if key == "top_p":
            serialized["topP"] = value
        elif key == "frequency_penalty":
            serialized["frequencyPenalty"] = value
        elif key == "presence_penalty":
            serialized["presencePenalty"] = value
        elif key == "enable_thinking":
            serialized["enableThinking"] = value
        else:
            serialized[key] = value
    return serialized


def _serialize_mcp_env(env_vars: Any) -> list[dict[str, Any]]:
    """Serialize auth.envVars (new format) to API response mcpServersConfigEnv format."""
    if not isinstance(env_vars, list):
        return []

    items: list[dict[str, Any]] = []
    for var in env_vars:
        if not isinstance(var, dict):
            continue
        items.append(
            {
                "name": var.get("name"),
                "type": var.get("type", "string"),
                "defaultValue": var.get("default_value", var.get("defaultValue")),
                "isRequired": var.get("required", var.get("is_required", var.get("isRequired", True))),
                "description": var.get("description", ""),
                "link": var.get("link", ""),
            }
        )
    return items


def _serialize_tags(raw_tags: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_tags, list):
        return []

    tags: list[dict[str, Any]] = []
    for item in raw_tags:
        if not isinstance(item, dict):
            continue
        tags.append(
            {
                "category": string_or_empty(item.get("category")),
                "nameCn": string_or_empty(item.get("nameCn")),
                "nameEn": string_or_empty(item.get("nameEn")),
                "name": string_or_empty(item.get("name")),
            }
        )
    return tags


def _rebuild_mcp_servers_config(servers: dict[str, Any]) -> dict[str, Any]:
    """Wrap new-format flat servers dict into legacy API format."""
    if not servers:
        return {}
    return {"mcpServers": servers}


def _serialize_mcp_servers_config_for_api(servers: dict[str, Any]) -> str:
    """Serialize MCP servers config as JSON string for API/chatbot compatibility."""
    payload = _rebuild_mcp_servers_config(servers)
    return json.dumps(payload, ensure_ascii=False) if payload else ""


def _serialize_mcp_servers(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Map new agent.json MCP format to API response format (field names unchanged)."""
    raw_mcp = config.get("mcp", [])
    if raw_mcp in (None, []):
        return []
    if not isinstance(raw_mcp, list):
        raise ValueError("agent.json field 'mcp' must be a list")

    servers: list[dict[str, Any]] = []
    for item in raw_mcp:
        if not isinstance(item, dict):
            continue
        auth = item.get("auth") or {}
        servers.append(
            {
                "nameEn": item.get("name", ""),
                "nameCn": item.get("displayName", ""),
                "id": string_or_empty(item.get("sourceId", "")),
                "visibility": string_or_empty(item.get("visibility", "")),
                "desc": item.get("description", ""),
                "imageUrl": item.get("imageUrl", ""),
                "tags": _serialize_tags(item.get("tags")),
                "mcpServersConfig": _serialize_mcp_servers_config_for_api(item.get("servers", {})),
                "mcpServersConfigEnv": _serialize_mcp_env(auth.get("envVars", [])),
                "timeout": item.get("timeout", 30),
                "available": bool(item.get("available", False)),
                "builtIn": bool_or_false(item.get("builtIn")),
                "deferred": item.get("deferred") is True,
            }
        )
    return servers


def _serialize_datasets(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_datasets = config.get("dataset", [])
    if raw_datasets in (None, []):
        return []
    if not isinstance(raw_datasets, list):
        raise ValueError("agent.json field 'dataset' must be a list")

    datasets: list[dict[str, Any]] = []
    for raw_dataset in raw_datasets:
        if not isinstance(raw_dataset, dict):
            continue
        datasets.append(
            {
                "nameCn": raw_dataset.get("nameCn"),
                "nameEn": raw_dataset.get("nameEn"),
                "datasetId": raw_dataset.get("dataset_id"),
                "id": string_or_empty(raw_dataset.get("id")),
                "visibility": string_or_empty(raw_dataset.get("visibility")),
                "desc": raw_dataset.get("desc"),
                "imageUrl": raw_dataset.get("image_url", raw_dataset.get("imageUrl")),
                "tags": _serialize_tags(raw_dataset.get("tags")),
                "builtIn": bool_or_false(raw_dataset.get("builtIn")),
            }
        )
    return datasets


def _serialize_skill(skill: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(skill)
    serialized["builtIn"] = bool_or_false(serialized.get("builtIn"))
    return serialized


def _serialize_general_config(config: dict[str, Any], prompt: str) -> dict[str, Any]:
    suggested_questions = config.get("suggested_questions", [])
    if not isinstance(suggested_questions, list):
        suggested_questions = []

    return {
        "name": config.get("name", "user_agent"),
        "repoName": config.get("repo_name", ""),
        "description": config.get("description", ""),
        "avatar": string_or_empty(config.get("avatar")),
        "welcomeMessage": config.get("welcome_message", ""),
        "suggestedQuestions": _serialize_suggested_questions(suggested_questions),
        "prompt": prompt,
    }


def _serialize_suggested_questions(raw_questions: list[Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        questions.append(
            {
                "question": question,
                "weight": item.get("weight", 1),
                "enable": bool(item.get("enable", True)),
            }
        )
    return questions


def _health_payload() -> dict[str, Any]:
    agent_ready = AGENTS.has_default()
    source = os.getenv("SOURCE", "").strip().lower()
    has_create_marker = True if source == "aihub" else _has_create_marker()
    reasons: list[str] = []
    if not agent_ready:
        reasons.append("agent is not initialized")
    if not has_create_marker:
        reasons.append("project create marker is missing")
    return {
        "status": agent_ready and has_create_marker,
        "reasons": reasons,
    }


def _has_create_marker() -> bool:
    global _CREATE_MARKER_STATUS

    if _CREATE_MARKER_STATUS is None:
        _CREATE_MARKER_STATUS = (PROJECT_ROOT / ".create").is_file()
    return _CREATE_MARKER_STATUS


def reset_create_marker_cache() -> None:
    global _CREATE_MARKER_STATUS

    _CREATE_MARKER_STATUS = None


def _llm_payload(config: dict[str, Any], registry: Any, *, model_field: str) -> dict[str, Any]:
    return {
        model_field: _get_configured_model(config),
        "currentModelLogo": _get_configured_model_logo(config),
        "currentArgs": _get_configured_llm_args(config),
        "providers": [_serialize_provider(provider) for provider in registry.providers],
    }


def _config_payload(config: dict[str, Any], prompt: str) -> dict[str, Any]:
    registry = load_llm_registry()
    return {
        **_serialize_general_config(config, prompt),
        **_llm_payload(config, registry, model_field="currentModel"),
        "skills": [_serialize_skill(skill) for skill in load_skill_registries(config.get("skills", []))],
        "mcp": _serialize_mcp_servers(config),
        "datasets": _serialize_datasets(config),
    }


@router.get("/health")
async def user_health() -> dict[str, Any]:
    try:
        payload = _health_payload()
    except Exception as exc:
        logger.exception("Health check failed")
        return {"code": 0, "msg": str(exc), "data": {"status": "error"}}

    if not payload["status"]:
        msg = "; ".join(payload["reasons"]) or "health check failed"
        logger.warning("Health check failed: %s", msg)
        return {"code": 0, "msg": msg, "data": {"status": "error"}}

    return {"code": 0, "msg": "success", "data": {"status": "ok"}}


@router.get("/config")
async def get_agent_config() -> dict[str, Any]:
    try:
        config = load_agent_config()
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        return {"code": 0, "msg": "success", "data": _config_payload(config, prompt)}
    except Exception as exc:
        logger.exception("Failed to read agent config")
        return {"code": 1, "msg": str(exc), "data": None}


@router.post("/files")
async def upload_agent_file(
    conversation_id: str = Form(..., alias="conversationId"),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        filename = _safe_upload_filename(file.filename)
        upload_path = _unique_upload_path(conversation_id, filename)
        size = 0
        with upload_path.open("wb") as target:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                size += len(chunk)
                target.write(chunk)
        data = {
            "name": upload_path.name,
            "path": str(upload_path),
            "clusterId": "",
            "type": upload_path.suffix.lstrip(".").lower(),
            "size": str(size),
            "content": "",
        }
        return {"code": 0, "msg": "success", "data": data}
    except Exception as exc:
        logger.exception("Failed to upload file conversation_id=%s filename=%s", conversation_id, file.filename)
        return {"code": 1, "msg": str(exc), "data": None}
    finally:
        with contextlib.suppress(Exception):
            await file.close()


__all__ = ["router"]
