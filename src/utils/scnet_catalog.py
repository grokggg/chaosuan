from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.logger import get_logger
from src.mcp.names import normalize_mcp_servers_mapping
from src.skills import is_skill_permission_error, sync_configured_skills, sync_private_configured_skills
from src.skills.scanner import expand_skill_source, load_skill_registry, private_skill_source
from src.utils.config import AGENT_CONFIG_PATH, load_agent_config, write_agent_config
from src.utils.strings import bool_or_false, string_or_empty

logger = get_logger(__name__)


@dataclass
class ScnetTag:
    category: str = ""
    nameCn: str = ""
    nameEn: str = ""
    name: str = ""

    @classmethod
    def from_raw(cls, raw_tag: dict[str, Any]) -> ScnetTag:
        return cls(
            category=string_or_empty(raw_tag.get("category")),
            nameCn=string_or_empty(raw_tag.get("nameCn")),
            nameEn=string_or_empty(raw_tag.get("nameEn")),
            name=string_or_empty(raw_tag.get("name")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScnetSkill:
    nameCn: str = ""
    nameEn: str = ""
    id: str = ""
    visibility: str = ""
    desc: str = ""
    httpUrlToRepo: str = ""
    tags: list[ScnetTag] = field(default_factory=list)
    avatarUrl: str = ""
    builtIn: bool = False

    @classmethod
    def from_raw(cls, raw_skill: dict[str, Any]) -> ScnetSkill | None:
        name_en = string_or_empty(raw_skill.get("nameEn"))
        repo_url = string_or_empty(raw_skill.get("httpUrlToRepo"))
        built_in = bool_or_false(raw_skill.get("builtIn"))
        if not name_en or (not built_in and not repo_url):
            return None
        return cls(
            nameCn=string_or_empty(raw_skill.get("nameCn")),
            nameEn=name_en,
            id=string_or_empty(raw_skill.get("id")),
            visibility=string_or_empty(raw_skill.get("visibility")),
            desc=string_or_empty(raw_skill.get("desc")),
            httpUrlToRepo=repo_url,
            tags=_normalize_tags(raw_skill.get("tags")),
            avatarUrl=string_or_empty(raw_skill.get("avatarUrl", raw_skill.get("avatar_url"))),
            builtIn=built_in,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nameCn": self.nameCn,
            "nameEn": self.nameEn,
            "id": self.id,
            "visibility": self.visibility,
            "desc": self.desc,
            "httpUrlToRepo": self.httpUrlToRepo,
            "tags": [tag.to_dict() for tag in self.tags],
            "avatarUrl": self.avatarUrl,
            "builtIn": self.builtIn,
        }


@dataclass
class ScnetMcp:
    nameCn: str = ""
    nameEn: str = ""
    id: str = ""
    visibility: str = ""
    desc: str | None = None
    image_url: str | None = None
    tags: list[ScnetTag] = field(default_factory=list)
    mcp_servers_config: Any = None
    mcp_servers_config_env: list[Any] = field(default_factory=list)
    timeout: Any = 30
    available: bool = False
    builtIn: bool = False
    deferred: bool = False

    @classmethod
    def from_raw(cls, raw_mcp: dict[str, Any]) -> ScnetMcp | None:
        name_en = string_or_empty(raw_mcp.get("nameEn") or raw_mcp.get("name"))
        config = raw_mcp.get("mcp_servers_config", raw_mcp.get("mcpServersConfig") or raw_mcp.get("servers"))
        if not name_en or not config:
            return None
        mcp_env = raw_mcp.get("mcp_servers_config_env", raw_mcp.get("mcpServersConfigEnv"))
        timeout = raw_mcp.get("timeout")
        return cls(
            nameCn=string_or_empty(raw_mcp.get("nameCn") or raw_mcp.get("displayName")),
            nameEn=name_en,
            id=string_or_empty(raw_mcp.get("id") or raw_mcp.get("sourceId")),
            visibility=string_or_empty(raw_mcp.get("visibility")),
            desc=raw_mcp.get("desc") or raw_mcp.get("description"),
            image_url=raw_mcp.get("image_url", raw_mcp.get("imageUrl")),
            tags=_normalize_tags(raw_mcp.get("tags")),
            mcp_servers_config=config,
            mcp_servers_config_env=mcp_env if isinstance(mcp_env, list) else [],
            timeout=30 if timeout is None else timeout,
            available=False,
            builtIn=bool_or_false(raw_mcp.get("builtIn")),
            deferred=raw_mcp.get("deferred") is True,
        )

    def to_dict(self) -> dict[str, Any]:
        """Output new agent.json MCP format."""
        return {
            "name": self.nameEn,
            "displayName": self.nameCn,
            "description": self.desc or "",
            "imageUrl": self.image_url or "",
            "visibility": self.visibility,
            "tags": [tag.to_dict() for tag in self.tags],
            "source": "scnet_community",
            "sourceId": self.id,
            "servers": _parse_mcp_servers_config(self.mcp_servers_config),
            "auth": _build_auth_from_env(self.mcp_servers_config_env),
            "timeout": self.timeout,
            "enabled": True,
            "available": False,
            "builtIn": self.builtIn,
            "deferred": self.deferred,
        }


@dataclass
class ScnetDataset:
    nameCn: str = ""
    nameEn: str = ""
    id: str = ""
    visibility: str = ""
    dataset_id: Any = None
    desc: str | None = None
    image_url: str | None = None
    tags: list[ScnetTag] = field(default_factory=list)
    builtIn: bool = False

    @classmethod
    def from_raw(cls, raw_dataset: dict[str, Any]) -> ScnetDataset | None:
        dataset_id = string_or_empty(raw_dataset.get("id"))
        name_en = string_or_empty(raw_dataset.get("nameEn"))
        name_cn = string_or_empty(raw_dataset.get("nameCn"))
        if not dataset_id and not name_en and not name_cn:
            return None
        return cls(
            nameCn=name_cn,
            nameEn=name_en,
            id=dataset_id,
            visibility=string_or_empty(raw_dataset.get("visibility")),
            dataset_id=raw_dataset.get("dataset_id", raw_dataset.get("datasetId")),
            desc=raw_dataset.get("desc", raw_dataset.get("description")),
            image_url=raw_dataset.get("image_url", raw_dataset.get("imageUrl")),
            tags=_normalize_tags(raw_dataset.get("tags")),
            builtIn=bool_or_false(raw_dataset.get("builtIn")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nameCn": self.nameCn,
            "nameEn": self.nameEn,
            "id": self.id,
            "visibility": self.visibility,
            "dataset_id": self.dataset_id,
            "desc": self.desc,
            "image_url": self.image_url,
            "tags": [tag.to_dict() for tag in self.tags],
            "builtIn": self.builtIn,
        }


def _normalize_tags(raw_tags: Any) -> list[ScnetTag]:
    if not isinstance(raw_tags, list):
        return []

    tags: list[ScnetTag] = []
    for item in raw_tags:
        if not isinstance(item, dict):
            continue
        tags.append(ScnetTag.from_raw(item))
    return tags


def _parse_mcp_servers_config(raw_config: Any) -> dict[str, Any]:
    """Parse mcp_servers_config (JSON string or dict) into flat servers dict."""
    if isinstance(raw_config, str):
        try:
            payload = json.loads(raw_config)
        except (json.JSONDecodeError, TypeError):
            return {}
    elif isinstance(raw_config, dict):
        payload = raw_config
    else:
        return {}

    servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    if isinstance(servers, dict):
        normalized, _ = normalize_mcp_servers_mapping(servers)
        return normalized
    if isinstance(payload, dict) and "transport" in payload:
        return {"default": payload}
    if isinstance(payload, dict):
        normalized, _ = normalize_mcp_servers_mapping(payload)
        return normalized
    return {}


def _build_auth_from_env(env_vars: list[Any]) -> dict[str, Any] | None:
    """Convert mcp_servers_config_env list into new auth format."""
    if not isinstance(env_vars, list) or not env_vars:
        return None
    normalized_vars = []
    for var in env_vars:
        if not isinstance(var, dict):
            continue
        normalized_vars.append({
            "name": var.get("name", ""),
            "type": var.get("type", "string"),
            "defaultValue": var.get("default_value", var.get("defaultValue")),
            "required": var.get("is_required", var.get("isRequired", var.get("required", True))),
            "description": var.get("description", ""),
            "link": var.get("link", ""),
        })
    if not normalized_vars:
        return None
    return {"type": "api_key", "envVars": normalized_vars}


def _record_key(record: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field_name in fields:
        value = string_or_empty(record.get(field_name))
        if value:
            return f"{field_name}:{value}"
    return ""


def _upsert_records(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    records = [dict(item) for item in existing if isinstance(item, dict)]
    index_by_key = {
        key: index
        for index, record in enumerate(records)
        if (key := _record_key(record, key_fields))
    }

    for item in incoming:
        if not isinstance(item, dict):
            continue
        key = _record_key(item, key_fields)
        if not key:
            continue
        if key in index_by_key:
            existing = records[index_by_key[key]]
            if bool_or_false(existing.get("builtIn")):
                continue
            existing.update(item)
        else:
            index_by_key[key] = len(records)
            records.append(dict(item))
    return records


def _has_private_skill_source(config: dict[str, Any]) -> bool:
    raw_sources = config.get("skills")
    if not isinstance(raw_sources, list):
        return False
    private_root = Path(private_skill_source()).resolve()
    for source in raw_sources:
        if not isinstance(source, str):
            continue
        try:
            if Path(expand_skill_source(source)).resolve() == private_root:
                return True
        except (OSError, ValueError):
            continue
    return False


def add_scnet_skills_to_config(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [ScnetSkill.from_raw(skill) for skill in skills if isinstance(skill, dict)]
    requested = [skill.to_dict() for skill in normalized if skill is not None]
    if not requested:
        raise ValueError("skills must include nameEn; external skills also require httpUrlToRepo")

    config = load_agent_config()
    desired_skills = _upsert_records(load_skill_registry(), requested, key_fields=("nameEn", "id", "nameCn"))
    project_permission_error: Exception | None = None
    try:
        refreshed_skills = sync_configured_skills(desired_skills)
    except Exception as exc:
        if not is_skill_permission_error(exc):
            raise
        project_permission_error = exc

    if project_permission_error is not None:
        if not _has_private_skill_source(config):
            raise ValueError(
                "Cannot fall back to the private skill directory because agent.json field "
                "'skills' does not include $HOME/.data/skills"
            )
        private_registry_path = Path(private_skill_source()).resolve() / "skills.json"
        private_skills = _upsert_records(
            load_skill_registry(private_registry_path),
            requested,
            key_fields=("nameEn", "id", "nameCn"),
        )
        logger.warning(
            "Project skill directory is not writable; retrying SCNet skill installation in private directory=%s",
            private_registry_path.parent,
        )
        refreshed_skills = sync_private_configured_skills(private_skills)
    write_agent_config(config, AGENT_CONFIG_PATH)
    return refreshed_skills


def add_scnet_mcp_to_config(mcp: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [ScnetMcp.from_raw(item) for item in mcp if isinstance(item, dict)]
    requested = [item.to_dict() for item in normalized if item is not None]
    if not requested:
        raise ValueError("mcp must include at least one item with nameEn and mcp_servers_config")

    config = load_agent_config()
    current = config.get("mcp")
    current_mcp = current if isinstance(current, list) else []
    config["mcp"] = _upsert_records(current_mcp, requested, key_fields=("name", "sourceId"))
    write_agent_config(config, AGENT_CONFIG_PATH)
    return config["mcp"]


def add_scnet_datasets_to_config(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [ScnetDataset.from_raw(item) for item in datasets if isinstance(item, dict)]
    requested = [item.to_dict() for item in normalized if item is not None]
    if not requested:
        raise ValueError("datasets must include at least one item with id, nameEn, or nameCn")

    config = load_agent_config()
    current = config.get("dataset")
    current_datasets = current if isinstance(current, list) else []
    config["dataset"] = _upsert_records(current_datasets, requested, key_fields=("id", "nameEn", "nameCn"))
    write_agent_config(config, AGENT_CONFIG_PATH)
    return config["dataset"]


__all__ = [
    "ScnetDataset",
    "ScnetMcp",
    "ScnetSkill",
    "ScnetTag",
    "add_scnet_datasets_to_config",
    "add_scnet_mcp_to_config",
    "add_scnet_skills_to_config",
]
