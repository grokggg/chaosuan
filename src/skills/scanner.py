from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from src.utils import PROJECT_ROOT, bool_or_false, string_or_empty

SKILLS_DIR = (PROJECT_ROOT / "skills").resolve()
SKILLS_REGISTRY_PATH = SKILLS_DIR / "skills.json"
DEFAULT_SKILL_SOURCE = "${PROJECT_ROOT}/skills"
PRIVATE_SKILL_SOURCE = "$HOME/.data/skills"
_INTERNAL_PATH_VARIABLES = {"PROJECT_ROOT": str(PROJECT_ROOT)}
_ENV_VAR_PATTERN = re.compile(r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|\$(?P<plain>[A-Za-z_][A-Za-z0-9_]*)")


def expand_skill_source(raw_source: str) -> str:
    source = raw_source.strip()
    if "{INSTANCE_ID}" in source and "${INSTANCE_ID}" not in source:
        source = source.replace("{INSTANCE_ID}", "${INSTANCE_ID}")

    def replace_var(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain")
        value = _INTERNAL_PATH_VARIABLES.get(name or "") or os.environ.get(name or "")
        if not value and name == "HOME":
            value = str(Path.home())
        if not value:
            raise ValueError(f"skill source requires environment variable {name}")
        return value

    previous = None
    while previous != source:
        previous = source
        source = _ENV_VAR_PATTERN.sub(replace_var, source)
    return source


def default_skill_source() -> str:
    return expand_skill_source(DEFAULT_SKILL_SOURCE)


def private_skill_source() -> str:
    return expand_skill_source(PRIVATE_SKILL_SOURCE)


def load_skill_registry(path: Path = SKILLS_REGISTRY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    raw_skills = payload.get("skills", []) if isinstance(payload, dict) else []
    if not isinstance(raw_skills, list):
        raise ValueError("skills.json field 'skills' must be a list")

    skills: list[dict[str, Any]] = []
    for item in raw_skills:
        if not isinstance(item, dict):
            continue
        name_en = str(item.get("nameEn") or "").strip()
        if not name_en:
            continue
        skill = dict(item)
        skill["nameEn"] = name_en
        skill["nameCn"] = string_or_empty(skill.get("nameCn"))
        skill["id"] = string_or_empty(skill.get("id"))
        skill["visibility"] = string_or_empty(skill.get("visibility"))
        skill["desc"] = string_or_empty(skill.get("desc"))
        skill["httpUrlToRepo"] = string_or_empty(skill.get("httpUrlToRepo"))
        skill["tags"] = _normalize_tags(skill.get("tags"))
        skill["builtIn"] = bool_or_false(skill.get("builtIn"))
        skills.append(skill)
    return skills


def load_skill_registries(raw_sources: Any) -> list[dict[str, Any]]:
    """Load and combine skills.json files from configured skill sources."""
    if not isinstance(raw_sources, list):
        raise ValueError("agent.json field 'skills' must be a list")

    skills: list[dict[str, Any]] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, str) or not raw_source.strip():
            continue
        source_dir = Path(expand_skill_source(raw_source)).resolve()
        skills.extend(load_skill_registry(source_dir / "skills.json"))
    return skills


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


def write_skill_registry(skills: list[dict[str, Any]], path: Path = SKILLS_REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump({"skills": skills}, file, ensure_ascii=False, indent=2)
        file.write("\n")
