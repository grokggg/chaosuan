from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any

_LOADER_NAMES = ("load_graph_subagents", "load_subagents")


def _resolve_loader(module: Any) -> Callable[[], list[dict[str, Any]]] | None:
    for name in _LOADER_NAMES:
        loader = getattr(module, name, None)
        if callable(loader):
            return loader

    loaders = [
        value
        for name, value in vars(module).items()
        if name.startswith("load_") and name.endswith("_subagents") and callable(value)
    ]
    if len(loaders) == 1:
        return loaders[0]
    return None


def load_graph_subagents() -> list[dict[str, Any]]:
    subagents: list[dict[str, Any]] = []
    for module_info in pkgutil.iter_modules(__path__, prefix=f"{__name__}."):
        if not module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        loader = _resolve_loader(module)
        if loader is not None:
            subagents.extend(loader())
    return subagents


__all__ = ["load_graph_subagents"]
