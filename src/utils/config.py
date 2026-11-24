from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from src.utils.workspace import PROJECT_ROOT

AGENT_CONFIG_PATH = PROJECT_ROOT / "config" / "agent.json"
PROMPT_PATH = PROJECT_ROOT / "src" / "prompt" / "system_prompt.md"


def load_json_file(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json_file(path: str | Path, payload: Any) -> None:
    with Path(path).open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def resolve_agent_config_path(config_path: str | Path | None = None) -> Path:
    if config_path is None:
        return AGENT_CONFIG_PATH
    candidate = Path(config_path)
    return candidate if candidate.is_absolute() else (AGENT_CONFIG_PATH.parent / candidate).resolve()


def load_agent_config(config_path: str | Path | None = None) -> dict[str, Any]:
    payload = load_json_file(resolve_agent_config_path(config_path))
    if not isinstance(payload, dict):
        raise ValueError("agent.json must be an object")
    return payload


def write_agent_config(config: dict[str, Any], config_path: str | Path | None = None) -> None:
    path = resolve_agent_config_path(config_path)
    serialized = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    try:
        original_mode = path.stat().st_mode
    except FileNotFoundError:
        original_mode = None

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(serialized)
            file.flush()
            os.fsync(file.fileno())
        if original_mode is not None:
            os.chmod(temp_path, stat.S_IMODE(original_mode))
        os.replace(temp_path, path)
        from src.utils.todolists import clear_todolist_agent_namespace_cache

        clear_todolist_agent_namespace_cache()
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def load_current_llm_config() -> dict[str, Any] | None:
    if not AGENT_CONFIG_PATH.exists():
        return None
    config = load_agent_config()
    llm_config = config.get("llm")
    return llm_config if isinstance(llm_config, dict) else None


__all__ = [
    "AGENT_CONFIG_PATH",
    "PROMPT_PATH",
    "load_agent_config",
    "load_current_llm_config",
    "load_json_file",
    "resolve_agent_config_path",
    "write_agent_config",
    "write_json_file",
]
