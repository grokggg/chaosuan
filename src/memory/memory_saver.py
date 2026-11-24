import logging
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SqliteConfig:
    path: Path
    source: str


class MemorySaverType(StrEnum):
    SQLITE = "sqlite"
    INMEMORY = "inmemory"


def resolve_sqlite_config() -> SqliteConfig | None:
    home_dir = os.getenv("HOME", "").strip()
    if not home_dir:
        return None
    return SqliteConfig(
        path=Path(home_dir) / ".data" / "user" / "sqlite" / "checkpoints.sqlite",
        source="HOME/.data/user/sqlite",
    )


class MemoryManager:
    def __init__(self) -> None:
        self._checkpointer: BaseCheckpointSaver | None = None
        self._sqlite_conn: aiosqlite.Connection | None = None

    def _create_memory_saver(self, reason: str) -> MemorySaver:
        saver = MemorySaver()
        self._checkpointer = saver
        logger.warning("Using MemorySaver: %s", reason)
        return saver

    async def _create_sqlite_saver(self, config: SqliteConfig) -> BaseCheckpointSaver:
        try:
            config.path.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_conn = await aiosqlite.connect(str(config.path), timeout=10)
            saver = AsyncSqliteSaver(self._sqlite_conn)
            await saver.setup()
            self._checkpointer = saver
            logger.info("Initialized AsyncSqliteSaver from %s path=%s", config.source, config.path)
            return saver
        except Exception as exc:
            if self._sqlite_conn is not None:
                await self._sqlite_conn.close()
                self._sqlite_conn = None
            return self._create_memory_saver(f"sqlite init failed: {exc}, will fallback to MemorySaver")

    async def get_memory(self, saver: MemorySaverType = MemorySaverType.SQLITE) -> BaseCheckpointSaver:
        if self._checkpointer is not None:
            return self._checkpointer

        if saver is MemorySaverType.INMEMORY:
            return self._create_memory_saver("inmemory saver requested")

        sqlite_config = resolve_sqlite_config()
        if sqlite_config is None:
            return self._create_memory_saver("sqlite saver requested but HOME is missing")
        return await self._create_sqlite_saver(sqlite_config)


_memory_manager: MemoryManager | None = None


async def get_memory(saver: MemorySaverType = MemorySaverType.SQLITE) -> BaseCheckpointSaver:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return await _memory_manager.get_memory(saver=saver)


__all__ = [
    "SqliteConfig",
    "MemorySaverType",
    "get_memory",
    "resolve_sqlite_config",
    "MemoryManager",
]
