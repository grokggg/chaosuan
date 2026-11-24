from __future__ import annotations

from collections.abc import Collection
from pathlib import Path
from typing import Any

from src.agents.agent import AGENT_CONFIG_PATH, build_agent
from src.logger import get_logger

logger = get_logger(__name__)


class AgentManager:
    def __init__(self) -> None:
        self._agents: dict[str, Any] = {}
        self._default_key = str(AGENT_CONFIG_PATH)

    def _resolve_key(self, config_path: str | Path | None = None) -> str:
        if config_path is None:
            return self._default_key

        candidate = Path(config_path)
        if candidate.is_absolute():
            return str(candidate.resolve())
        return str((AGENT_CONFIG_PATH.parent / candidate).resolve())

    async def create(
        self,
        config_path: str | Path | None = None,
        *,
        refresh: bool = False,
        sync_llm_config: bool = True,
        reload_tool_modules: Collection[str] | None = frozenset(),
    ) -> Any:
        key = self._resolve_key(config_path)
        if not refresh and key in self._agents:
            logger.info("Reusing cached agent for key=%s", key)
            return self._agents[key]

        logger.info("Creating agent for key=%s refresh=%s", key, refresh)
        agent = await build_agent(
            config_path,
            sync_llm_config=sync_llm_config,
            reload_tool_modules=reload_tool_modules,
        )
        self._agents[key] = agent
        return agent

    async def get(
        self,
        config_path: str | Path | None = None,
        *,
        sync_llm_config: bool = True,
        reload_tool_modules: Collection[str] | None = frozenset(),
    ) -> Any:
        return await self.create(
            config_path,
            sync_llm_config=sync_llm_config,
            reload_tool_modules=reload_tool_modules,
        )

    async def reset(
        self,
        config_path: str | Path | None = None,
        *,
        sync_llm_config: bool = True,
        reload_tool_modules: Collection[str] | None = frozenset(),
    ) -> Any:
        key = self._resolve_key(config_path)
        logger.info("Resetting agent for key=%s", key)
        self._agents.pop(key, None)
        return await self.create(
            config_path,
            refresh=True,
            sync_llm_config=sync_llm_config,
            reload_tool_modules=reload_tool_modules,
        )

    def drop(self, config_path: str | Path | None = None) -> bool:
        key = self._resolve_key(config_path)
        removed = self._agents.pop(key, None) is not None
        logger.info("Dropped cached agent for key=%s removed=%s", key, removed)
        return removed

    def clear(self) -> None:
        logger.info("Clearing %s cached agents", len(self._agents))
        self._agents.clear()

    def list(self) -> list[str]:
        return list(self._agents.keys())

    def has_default(self) -> bool:
        return self._default_key in self._agents


AGENTS = AgentManager()


__all__ = ["AGENTS", "AgentManager"]
