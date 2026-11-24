from __future__ import annotations

from typing import Literal

from src.utils.config import load_agent_config

AgentLanguage = Literal["zh", "en"]


def normalize_agent_language(value: object) -> AgentLanguage:
    return "zh" if isinstance(value, str) and value.strip().lower() == "zh" else "en"


def current_agent_language() -> AgentLanguage:
    try:
        config = load_agent_config()
    except Exception:
        return "en"

    return normalize_agent_language(config.get("language"))


def localized_text(en: str, zh: str) -> str:
    return zh if current_agent_language() == "zh" else en


__all__ = ["AgentLanguage", "current_agent_language", "localized_text", "normalize_agent_language"]
