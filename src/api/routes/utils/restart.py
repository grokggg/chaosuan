from __future__ import annotations

import json
from typing import Any

from src.api.routes.model import PrivateResourcesUpdateRequest, UserAgentRestartRequest
from src.llm import (
    MODEL_CONFIG_PATH,
    clear_llm_registry_cache,
    resolve_model,
    resolve_model_ref,
    sanitize_llm_config_with_model,
    sync_llm_config_with_model_args,
)
from src.mcp.names import normalize_mcp_servers_mapping
from src.skills import sync_configured_skills, sync_private_configured_skills
from src.utils import (
    AGENT_CONFIG_PATH,
    PROMPT_PATH,
    bool_or_false,
    load_agent_config,
    string_or_empty,
    write_agent_config,
)

_LLM_CONFIG_METADATA_KEYS = {"model", "logo"}
_BACKEND_ONLY_LLM_ARGS = {
    "max_retries",
    "base_delay_seconds",
    "max_delay_seconds",
    "maxRetries",
    "baseDelaySeconds",
    "maxDelaySeconds",
}


def apply_restart_config(request: UserAgentRestartRequest) -> dict[str, Any]:
    config = load_agent_config()
    config.pop("rag", None)
    previous_model: str | None = None
    selected_model: str | None = None
    model_updated = False

    for field_name in ("name", "avatar", "welcome_message"):
        value = getattr(request, field_name)
        if value is not None:
            config[field_name] = value
    if request.desc is not None:
        config["description"] = request.desc

    if request.suggested_questions is not None:
        config["suggested_questions"] = _normalize_suggested_questions(request.suggested_questions)

    if request.model is not None:
        if not request.model.strip():
            raise ValueError("model must not be empty")
        selected = resolve_model({"model": request.model})
        if selected.internal:
            raise ValueError(f"model '{selected.name}' is internal and cannot be selected")
        selected_model = selected.ref
        llm_config = config.get("llm")
        if not isinstance(llm_config, dict):
            llm_config = {}
            config["llm"] = llm_config
        previous_model = resolve_model_ref(llm_config) if llm_config else resolve_model_ref(None)
        model_updated = selected_model != previous_model
        if model_updated:
            _write_current_llm_args_to_model_json(previous_model, llm_config)
            llm_config.clear()
            llm_config["model"] = selected_model
            sync_llm_config_with_model_args(llm_config, force=True)
        else:
            llm_config["model"] = previous_model
    else:
        llm_config = config.get("llm")
        if not isinstance(llm_config, dict):
            llm_config = {}
            config["llm"] = llm_config

    for field_name in _BACKEND_ONLY_LLM_ARGS:
        llm_config.pop(field_name, None)

    if request.llm_args is not None:
        llm_config = config.get("llm")
        if not isinstance(llm_config, dict):
            llm_config = {}
            config["llm"] = llm_config
        if "model" not in llm_config:
            llm_config["model"] = resolve_model_ref(None)
        llm_config.update(_normalize_llm_args(request.llm_args))
        sanitize_llm_config_with_model(llm_config)

    prompt_updated = False
    if request.system_prompt is not None:
        PROMPT_PATH.write_text(request.system_prompt, encoding="utf-8")
        prompt_updated = True

    if request.datasets is not None:
        config["dataset"] = _normalize_datasets(request.datasets)

    if request.mcp is not None:
        config["mcp"] = _normalize_mcp_config(request.mcp)

    refreshed_skills = sync_configured_skills(request.skills)
    write_agent_config(config, AGENT_CONFIG_PATH)

    return {
        "previousModel": previous_model,
        "selectedModel": selected_model,
        "modelUpdated": model_updated,
        "promptUpdated": prompt_updated,
        "skills": [_serialize_skill(skill) for skill in refreshed_skills],
    }


def apply_private_resources_config(request: PrivateResourcesUpdateRequest) -> dict[str, Any]:
    """Apply a full update of private skills, MCP services, and datasets."""
    config = load_agent_config()
    normalized_mcp = _normalize_mcp_config(request.mcp)
    normalized_datasets = _normalize_datasets(request.datasets)
    refreshed_skills = sync_private_configured_skills(request.skills)

    config.pop("rag", None)
    config["mcp"] = normalized_mcp
    config["dataset"] = normalized_datasets
    write_agent_config(config, AGENT_CONFIG_PATH)
    return {
        "skills": [_serialize_skill(skill) for skill in refreshed_skills],
        "mcp": normalized_mcp,
        "datasets": normalized_datasets,
    }


def _write_current_llm_args_to_model_json(model_ref: str, llm_config: dict[str, Any]) -> None:
    args = {
        str(key): value
        for key, value in llm_config.items()
        if key not in _LLM_CONFIG_METADATA_KEYS and key not in _BACKEND_ONLY_LLM_ARGS
    }
    if not args:
        return

    provider_name, _, model_name = model_ref.partition("/")
    if not provider_name or not model_name:
        raise ValueError(f"Invalid model ref '{model_ref}'")

    with MODEL_CONFIG_PATH.open("r", encoding="utf-8") as file:
        model_config = json.load(file)
    providers = model_config.get("providers") if isinstance(model_config, dict) else None
    provider = providers.get(provider_name) if isinstance(providers, dict) else None
    models = provider.get("models") if isinstance(provider, dict) else None
    if not isinstance(models, list):
        raise ValueError(f"model.json provider '{provider_name}' field 'models' must be a list")

    for model in models:
        if isinstance(model, dict) and model.get("name") == model_name:
            model["args"] = args
            with MODEL_CONFIG_PATH.open("w", encoding="utf-8") as file:
                json.dump(model_config, file, ensure_ascii=False, indent=2)
                file.write("\n")
            clear_llm_registry_cache()
            return

    raise ValueError(f"model.json does not define model '{model_ref}'")


def _normalize_suggested_questions(raw_questions: list[Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for item in raw_questions:
        question = str(item.question).strip()
        if not question:
            continue
        questions.append(
            {
                "question": question,
                "weight": item.weight,
                "enable": bool(item.enable),
            }
        )
    return questions


def _normalize_mcp_config(raw_mcp: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert frontend old-format MCP config to new agent.json format."""
    normalized: list[dict[str, Any]] = []
    for value in raw_mcp:
        if not isinstance(value, dict):
            continue
        name = str(value.get("nameEn") or value.get("name") or "").strip()
        if not name:
            continue

        servers, server_errors = _extract_servers(value.get("mcpServersConfig", value.get("mcp_servers_config", value.get("servers"))))
        env_vars = _extract_env_vars(value.get("mcpServersConfigEnv", value.get("mcp_servers_config_env")))

        normalized_item = {
            "name": name,
            "displayName": value.get("nameCn", value.get("displayName", "")),
            "description": value.get("desc", value.get("description", "")),
            "sourceId": string_or_empty(value.get("id", value.get("sourceId", ""))),
            "visibility": string_or_empty(value.get("visibility", "")),
            "imageUrl": value.get("imageUrl", value.get("image_url", "")),
            "tags": _normalize_tags(value.get("tags")),
            "servers": servers,
            "auth": {"type": "api_key", "envVars": env_vars} if env_vars else None,
            "timeout": value.get("timeout", 30),
            "enabled": True,
            "available": False,
            "builtIn": bool_or_false(value.get("builtIn")),
            "deferred": value.get("deferred") is True,
        }
        if server_errors:
            normalized_item["lastError"] = "; ".join(server_errors)
        normalized.append(normalized_item)
    return normalized


def _extract_servers(raw_config: Any) -> tuple[dict[str, Any], list[str]]:
    """Extract flat servers dict from various input formats."""
    if isinstance(raw_config, str):
        try:
            raw_config = json.loads(raw_config)
        except (ValueError, TypeError):
            return {}, ["MCP servers config must be valid JSON"]
    if not isinstance(raw_config, dict):
        return {}, ["MCP servers config must be an object"]
    servers = raw_config.get("mcpServers")
    if isinstance(servers, dict):
        return normalize_mcp_servers_mapping(servers)
    if "transport" in raw_config or "type" in raw_config:
        return {"default": raw_config}, []
    return normalize_mcp_servers_mapping(raw_config)


def _extract_env_vars(raw_env: Any) -> list[dict[str, Any]]:
    """Normalize env vars from API format to new auth.envVars format."""
    if not isinstance(raw_env, list):
        return []
    env_vars: list[dict[str, Any]] = []
    for item in raw_env:
        if not isinstance(item, dict):
            continue
        env_vars.append({
            "name": item.get("name", ""),
            "type": item.get("type", "string"),
            "defaultValue": item.get("defaultValue", item.get("default_value")),
            "required": item.get("isRequired", item.get("is_required", item.get("required", True))),
            "description": item.get("description", ""),
            "link": item.get("link", ""),
        })
    return env_vars


def _normalize_datasets(raw_datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    datasets: list[dict[str, Any]] = []
    for item in raw_datasets:
        if not isinstance(item, dict):
            continue
        datasets.append(
            {
                "nameCn": item.get("nameCn"),
                "nameEn": item.get("nameEn"),
                "dataset_id": item.get("datasetId"),
                "id": string_or_empty(item.get("id")),
                "visibility": string_or_empty(item.get("visibility")),
                "desc": item.get("desc"),
                "image_url": item.get("image_url", item.get("imageUrl")),
                "tags": _normalize_tags(item.get("tags")),
                "builtIn": bool_or_false(item.get("builtIn")),
            }
        )
    return datasets


def _normalize_tags(raw_tags: Any) -> list[dict[str, Any]]:
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


def _normalize_llm_args(raw_args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_args, dict):
        raise ValueError("llmArgs must be an object")

    normalized = dict(raw_args)
    for field_name in _BACKEND_ONLY_LLM_ARGS:
        normalized.pop(field_name, None)
    alias_map = {
        "topP": "top_p",
        "frequencyPenalty": "frequency_penalty",
        "presencePenalty": "presence_penalty",
        "enableThinking": "enable_thinking",
    }
    for alias, canonical in alias_map.items():
        if alias in normalized:
            normalized[canonical] = normalized.pop(alias)
    for field_name, min_value, max_value in (
        ("temperature", 0, 1),
        ("top_p", 0, 1),
        ("frequency_penalty", -2, 2),
    ):
        if field_name not in normalized:
            continue
        value = normalized[field_name]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"llmArgs.{field_name} must be a number")
        if value < min_value or value > max_value:
            raise ValueError(f"llmArgs.{field_name} must be between {min_value} and {max_value}")
        normalized[field_name] = float(value)

    if "enable_thinking" in normalized and not isinstance(normalized["enable_thinking"], bool):
        raise ValueError("llmArgs.enable_thinking must be a boolean")

    return normalized


def _serialize_skill(skill: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(skill)
    serialized["builtIn"] = bool_or_false(serialized.get("builtIn"))
    return serialized


__all__ = ["apply_private_resources_config", "apply_restart_config"]
