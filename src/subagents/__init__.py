from __future__ import annotations

from typing import Any

from src.subagents.declarative import load_declarative_subagents
from src.subagents.graph import load_graph_subagents


def load_subagents() -> list[dict[str, Any]]:
    return [*load_declarative_subagents(), *load_graph_subagents()]


__all__ = ["load_declarative_subagents", "load_graph_subagents", "load_subagents"]
