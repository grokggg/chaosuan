from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import ModelResponse

from src.logger import get_logger
from src.skills.scanner import expand_skill_source, load_skill_registry
from src.utils import add_usage, bool_or_false, extract_response_usage

logger = get_logger(__name__)

RESOURCE_METADATA_KEY = "sag_resource"
RESOURCE_TYPE_MCP = "mcp"
RESOURCE_STATISTICS_EXCLUDE_BUILTIN_ENV = "RESOURCE_STATISTICS_EXCLUDE_BUILTIN"
_CONTEXT_ATTRIBUTE = "_resource_statistics"
_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")
_PATH_FOLLOWING_CHARS = r"[/\s\"'`;,&|)]"
_FALSE_ENV_VALUES = frozenset({"0", "false", "n", "no", "off"})


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list | tuple | set | frozenset):
        return [_string(item) for item in value if _string(item)]
    normalized = _string(value)
    return [normalized] if normalized else []


def _exclude_builtin_resources() -> bool:
    value = os.getenv(RESOURCE_STATISTICS_EXCLUDE_BUILTIN_ENV, "TRUE")
    return value.strip().lower() not in _FALSE_ENV_VALUES


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, usage: Mapping[str, Any] | None) -> TokenUsage:
        if not usage:
            return cls()

        def token(key: str) -> int:
            value = usage.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

        prompt_tokens = token("prompt_tokens")
        completion_tokens = token("completion_tokens")
        total_value = usage.get("total_tokens")
        total_tokens = (
            total_value
            if isinstance(total_value, int) and not isinstance(total_value, bool) and total_value >= 0
            else prompt_tokens + completion_tokens
        )
        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    def add(self, other: TokenUsage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens

    def to_dict(self) -> dict[str, int]:
        return {key: getattr(self, key) for key in _TOKEN_KEYS}


@dataclass(frozen=True, slots=True)
class KnowledgeResource:
    id: str
    name: str

    @property
    def key(self) -> tuple[str, str]:
        return self.id, self.name


@dataclass(frozen=True, slots=True)
class SkillResource:
    id: str
    name: str
    path_aliases: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        return self.id, self.name


@dataclass(slots=True)
class ResourceCatalog:
    knowledges_by_dataset_id: dict[str, KnowledgeResource]
    skills: list[SkillResource]
    exclude_builtin: bool = True

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> ResourceCatalog:
        exclude_builtin = _exclude_builtin_resources()
        return cls(
            knowledges_by_dataset_id=_build_knowledge_catalog(config.get("dataset")),
            skills=_build_skill_catalog(config.get("skills"), exclude_builtin=exclude_builtin),
            exclude_builtin=exclude_builtin,
        )

    def configured_knowledges(self) -> list[KnowledgeResource]:
        return list(dict.fromkeys(self.knowledges_by_dataset_id.values()))

    def match_skill_path(self, path: str) -> list[SkillResource]:
        return self._match_skills(path)

    def match_skill_command(self, command: str) -> list[SkillResource]:
        return self._match_skills(command)

    def _match_skills(self, text: str) -> list[SkillResource]:
        normalized = _expand_known_path_variables(_normalize_path_text(text))
        if not normalized:
            return []

        matched: list[SkillResource] = []
        for skill in self.skills:
            if any(_contains_path(normalized, alias) for alias in skill.path_aliases):
                matched.append(skill)
        return matched


@dataclass(slots=True)
class _ModelStatistics:
    name: str
    count: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass(slots=True)
class _McpStatistics:
    id: str
    name: str
    count: int = 0
    tools: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class _KnowledgeStatistics:
    id: str
    name: str
    count: int = 0


@dataclass(slots=True)
class _SkillStatistics:
    id: str
    name: str
    count: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass(slots=True)
class _JobStatistics:
    job_id: str
    cluster_id: str
    submitters: list[SkillResource]


@dataclass(frozen=True, slots=True)
class _ToolCallUsage:
    model_call_id: int
    token_usage: TokenUsage


@dataclass(slots=True)
class ResourceStatisticsTracker:
    catalog: ResourceCatalog
    models: dict[str, _ModelStatistics] = field(default_factory=dict)
    mcps: dict[tuple[str, str], _McpStatistics] = field(default_factory=dict)
    knowledges: dict[tuple[str, str], _KnowledgeStatistics] = field(default_factory=dict)
    skills: dict[tuple[str, str], _SkillStatistics] = field(default_factory=dict)
    jobs: list[_JobStatistics] = field(default_factory=list)
    pending_job_submitters: dict[tuple[str, str], SkillResource] = field(default_factory=dict)
    tool_call_usage: dict[str, _ToolCallUsage] = field(default_factory=dict)
    attributed_skill_usage: set[tuple[int, tuple[str, str]]] = field(default_factory=set)
    counted_skill_calls: set[tuple[str, tuple[str, str]]] = field(default_factory=set)
    counted_mcp_calls: set[str] = field(default_factory=set)
    counted_knowledge_calls: set[tuple[str, tuple[str, str]]] = field(default_factory=set)
    next_model_call_id: int = 1

    def start_model_call(self, model_name: str) -> int:
        model = self.models.setdefault(model_name, _ModelStatistics(name=model_name))
        model.count += 1
        model_call_id = self.next_model_call_id
        self.next_model_call_id += 1
        return model_call_id

    def finish_model_call(self, model_name: str, model_call_id: int, response: ModelResponse[Any]) -> None:
        usage_values: dict[str, int] = {}
        for message in response.result:
            add_usage(usage_values, extract_response_usage(message))
        usage = TokenUsage.from_mapping(usage_values)
        self.models.setdefault(model_name, _ModelStatistics(name=model_name)).token_usage.add(usage)

        for message in response.result:
            tool_calls = getattr(message, "tool_calls", None)
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                tool_call_id = _string(tool_call.get("id"))
                if tool_call_id:
                    self.tool_call_usage[tool_call_id] = _ToolCallUsage(model_call_id, usage)

    def record_mcp(self, tool_call_id: str, resource: Mapping[str, Any]) -> None:
        if self.catalog.exclude_builtin and bool_or_false(resource.get("builtIn")):
            return
        if tool_call_id and tool_call_id in self.counted_mcp_calls:
            return
        if tool_call_id:
            self.counted_mcp_calls.add(tool_call_id)

        resource_id = _string(resource.get("id"))
        name = _string(resource.get("name"))
        tool_name = _string(resource.get("tool"))
        key = (resource_id, name)
        item = self.mcps.setdefault(key, _McpStatistics(id=resource_id, name=name))
        item.count += 1
        if tool_name:
            item.tools[tool_name] = item.tools.get(tool_name, 0) + 1

    def record_knowledge(self, tool_call_id: str, resource: KnowledgeResource) -> None:
        call_key = (tool_call_id, resource.key)
        if tool_call_id and call_key in self.counted_knowledge_calls:
            return
        if tool_call_id:
            self.counted_knowledge_calls.add(call_key)
        item = self.knowledges.setdefault(
            resource.key,
            _KnowledgeStatistics(id=resource.id, name=resource.name),
        )
        item.count += 1

    def record_skill(self, tool_call_id: str, resource: SkillResource) -> None:
        self.pending_job_submitters.setdefault(resource.key, resource)
        attribution = self.tool_call_usage.get(tool_call_id)
        # A tool restored from a prior SSE round has no model-call attribution in
        # the current tracker. Skipping it prevents approval resume from counting
        # the same generated tool call twice.
        if attribution is None:
            return

        call_key = (tool_call_id, resource.key)
        if call_key in self.counted_skill_calls:
            return
        self.counted_skill_calls.add(call_key)

        item = self.skills.setdefault(
            resource.key,
            _SkillStatistics(id=resource.id, name=resource.name),
        )
        item.count += 1

        usage_key = (attribution.model_call_id, resource.key)
        if usage_key in self.attributed_skill_usage:
            return
        self.attributed_skill_usage.add(usage_key)
        item.token_usage.add(attribution.token_usage)

    def record_job(self, job_id: str, cluster_id: str) -> None:
        normalized_job_id = _string(job_id)
        normalized_cluster_id = _string(cluster_id)
        if not normalized_job_id or not normalized_cluster_id:
            return
        self.jobs.append(
            _JobStatistics(
                job_id=normalized_job_id,
                cluster_id=normalized_cluster_id,
                submitters=list(self.pending_job_submitters.values()),
            )
        )
        self.pending_job_submitters.clear()

    def to_statistics(self) -> dict[str, Any]:
        return {
            "models": [
                {
                    "count": item.count,
                    "id": "",
                    "name": item.name,
                    "tokenUsage": item.token_usage.to_dict(),
                }
                for item in self.models.values()
            ],
            "mcps": [
                {
                    "name": item.name,
                    "id": item.id,
                    "count": item.count,
                    "tools": dict(item.tools),
                }
                for item in self.mcps.values()
            ],
            "knowledges": [
                {
                    "count": item.count,
                    "id": item.id,
                    "name": item.name,
                }
                for item in self.knowledges.values()
            ],
            "skills": [
                {
                    "count": item.count,
                    "id": item.id,
                    "name": item.name,
                    "tokenUsage": item.token_usage.to_dict(),
                }
                for item in self.skills.values()
            ],
            "jobs": [
                {
                    "jobId": item.job_id,
                    "clusterId": item.cluster_id,
                    "submitter": [
                        {
                            "id": submitter.id,
                            "name": submitter.name,
                            "type": "skill",
                        }
                        for submitter in item.submitters
                    ],
                }
                for item in self.jobs
            ],
        }

    def to_payload(self) -> dict[str, Any]:
        return {"type": "statistics", **self.to_statistics()}

    def consume_statistics(self) -> dict[str, Any]:
        statistics = self.to_statistics()
        self.clear()
        return statistics

    def clear(self) -> None:
        self.models.clear()
        self.mcps.clear()
        self.knowledges.clear()
        self.skills.clear()
        self.jobs.clear()
        self.pending_job_submitters.clear()
        self.tool_call_usage.clear()
        self.attributed_skill_usage.clear()
        self.counted_skill_calls.clear()
        self.counted_mcp_calls.clear()
        self.counted_knowledge_calls.clear()
        self.next_model_call_id = 1


def empty_resource_statistics() -> dict[str, list[dict[str, Any]]]:
    return {
        "models": [],
        "mcps": [],
        "knowledges": [],
        "skills": [],
        "jobs": [],
    }


def _build_knowledge_catalog(raw_datasets: Any) -> dict[str, KnowledgeResource]:
    catalog: dict[str, KnowledgeResource] = {}
    if not isinstance(raw_datasets, list):
        return catalog
    for item in raw_datasets:
        if not isinstance(item, dict):
            continue
        resource = KnowledgeResource(
            id=_string(item.get("id")),
            name=_string(item.get("nameCn")),
        )
        for dataset_id in _normalize_ids(item.get("dataset_id", item.get("dataset_ids"))):
            catalog[dataset_id] = resource
    return catalog


def _build_skill_catalog(raw_sources: Any, *, exclude_builtin: bool) -> list[SkillResource]:
    if not isinstance(raw_sources, list):
        return []

    skills: list[SkillResource] = []
    seen_paths: set[str] = set()
    for raw_source in raw_sources:
        if not isinstance(raw_source, str) or not raw_source.strip():
            continue
        try:
            expanded_source = expand_skill_source(raw_source)
        except ValueError as exc:
            logger.warning("Skipping statistics skill source source=%s reason=%s", raw_source, exc)
            continue

        source_dir = Path(expanded_source).resolve()
        try:
            registry = load_skill_registry(source_dir / "skills.json")
        except (OSError, ValueError) as exc:
            logger.warning("Skipping statistics skill registry path=%s reason=%s", source_dir, exc)
            registry = []
        registry_by_name = {_string(item.get("nameEn")): item for item in registry if _string(item.get("nameEn"))}
        skill_names = list(registry_by_name)
        try:
            source_children = list(source_dir.iterdir()) if source_dir.is_dir() else []
        except OSError as exc:
            logger.warning("Skipping statistics skill source listing path=%s reason=%s", source_dir, exc)
            source_children = []
        for child in source_children:
            if child.is_dir() and (child / "SKILL.md").is_file() and child.name not in registry_by_name:
                skill_names.append(child.name)

        for name in skill_names:
            registry_item = registry_by_name.get(name, {})
            if exclude_builtin and bool_or_false(registry_item.get("builtIn")):
                continue
            skill_dir = source_dir / name
            normalized_skill_path = _normalize_path_text(str(skill_dir.resolve()))
            if normalized_skill_path in seen_paths:
                continue
            seen_paths.add(normalized_skill_path)
            raw_alias = _normalize_path_text(f"{raw_source.rstrip('/\\')}/{name}")
            aliases = {
                normalized_skill_path,
                _expand_known_path_variables(raw_alias),
                raw_alias,
            }
            try:
                relative_alias = skill_dir.resolve().relative_to(Path.cwd().resolve())
            except ValueError:
                pass
            else:
                aliases.add(_normalize_path_text(str(relative_alias)))
            skills.append(
                SkillResource(
                    id=_string(registry_item.get("id")),
                    name=name,
                    path_aliases=tuple(sorted((alias.rstrip("/") for alias in aliases if alias), key=len, reverse=True)),
                )
            )

    return skills


def _normalize_path_text(value: str) -> str:
    return value.strip().strip("\"'").replace("\\", "/").rstrip("/")


def _expand_known_path_variables(value: str) -> str:
    project_root = str(Path(__file__).resolve().parents[1]).replace("\\", "/")
    home = str(Path.home()).replace("\\", "/")
    replacements = {
        "${PROJECT_ROOT}": project_root,
        "$PROJECT_ROOT": project_root,
        "${HOME}": home,
        "$HOME": home,
    }
    expanded = value
    for placeholder, replacement in replacements.items():
        expanded = expanded.replace(placeholder, replacement)
    if expanded == "~" or expanded.startswith("~/"):
        expanded = home + expanded[1:]
    return expanded


def _contains_path(text: str, path: str) -> bool:
    if not path:
        return False
    flags = re.IGNORECASE if os.name == "nt" or re.match(r"^[A-Za-z]:/", path) else 0
    pattern = rf"(?<![A-Za-z0-9_.-]){re.escape(path)}(?=$|{_PATH_FOLLOWING_CHARS})"
    return re.search(pattern, text, flags=flags) is not None


def get_resource_statistics(runtime_or_context: Any) -> ResourceStatisticsTracker | None:
    context = getattr(runtime_or_context, "context", runtime_or_context)
    tracker = getattr(context, _CONTEXT_ATTRIBUTE, None)
    return tracker if isinstance(tracker, ResourceStatisticsTracker) else None


def start_resource_statistics(runtime_or_context: Any, catalog: ResourceCatalog) -> ResourceStatisticsTracker | None:
    context = getattr(runtime_or_context, "context", runtime_or_context)
    if context is None:
        return None
    tracker = ResourceStatisticsTracker(catalog)
    setattr(context, _CONTEXT_ATTRIBUTE, tracker)
    return tracker


__all__ = [
    "RESOURCE_METADATA_KEY",
    "RESOURCE_STATISTICS_EXCLUDE_BUILTIN_ENV",
    "RESOURCE_TYPE_MCP",
    "KnowledgeResource",
    "ResourceCatalog",
    "ResourceStatisticsTracker",
    "SkillResource",
    "TokenUsage",
    "empty_resource_statistics",
    "get_resource_statistics",
    "start_resource_statistics",
]
