from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Collection
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

TOOLS_DIR = Path(__file__).resolve().parent
TOOLS_PACKAGE = "src.tools"
DEFERRED_TOOLS_DIR = TOOLS_DIR / "deferred"
DEFERRED_TOOLS_PACKAGE = f"{TOOLS_PACKAGE}.deferred"
SCIENCE_TOOLS_DIR = TOOLS_DIR / "science"
SCIENCE_TOOLS_PACKAGE = f"{TOOLS_PACKAGE}.science"


def _module_names(directory: Path, package: str) -> list[str]:
    module_names: list[str] = []
    for path in sorted(directory.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module_names.append(f"{package}.{path.stem}")
    return module_names


def _include_science_tools(mode: Any) -> bool:
    normalized_mode = mode.strip().lower() if isinstance(mode, str) else ""
    return normalized_mode != "general"


def _iter_tool_modules(mode: Any = None) -> list[str]:
    module_names = _module_names(TOOLS_DIR, TOOLS_PACKAGE)
    module_names.extend(_module_names(DEFERRED_TOOLS_DIR, DEFERRED_TOOLS_PACKAGE))
    if _include_science_tools(mode):
        module_names.extend(_module_names(SCIENCE_TOOLS_DIR, SCIENCE_TOOLS_PACKAGE))
    return module_names


def _load_tool_module(
    module_name: str,
    reload_modules: Collection[str] | None,
):
    should_reload = module_name in sys.modules and (
        reload_modules is None or module_name in reload_modules
    )
    if should_reload:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def load_tools(
    mode: Any = None,
    *,
    reload_modules: Collection[str] | None = frozenset(),
) -> list[BaseTool]:
    """Load tools without importing user source again on normal agent startup.

    ``None`` is reserved for explicit hot-update paths that need every imported
    tool module to observe new process environment variables.
    """
    resolved_tools: list[BaseTool] = []
    for module_name in _iter_tool_modules(mode):
        module = _load_tool_module(module_name, reload_modules)
        for _, member in inspect.getmembers(module):
            if isinstance(member, BaseTool):
                resolved_tools.append(member)
    return resolved_tools


__all__ = ["load_tools"]
