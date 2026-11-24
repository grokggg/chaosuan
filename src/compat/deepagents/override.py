"""Install version-pinned, project-owned DeepAgents modules before imports.

Only graph, memory and filesystem modules are redirected; every other upstream
module is left untouched. No installed package or wheel is modified. Set
``SAG_MAKER_DEEPAGENTS_OVERRIDE=0`` before Python starts for an A/B baseline.
"""

from __future__ import annotations

import os
import sys
from importlib.abc import MetaPathFinder
from importlib.metadata import version
from importlib.util import spec_from_file_location
from pathlib import Path

SUPPORTED_DEEPAGENTS_VERSION = "0.7.11"
_ENV_NAME = "SAG_MAKER_DEEPAGENTS_OVERRIDE"
_OVERRIDE_DIR = Path(__file__).resolve().parent
_OVERRIDES = {
    "deepagents.graph": _OVERRIDE_DIR / "graph.py",
    "deepagents.middleware.memory": _OVERRIDE_DIR / "memory.py",
    "deepagents.middleware.filesystem": _OVERRIDE_DIR / "filesystem.py",
}


class _ProjectDeepAgentsFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        replacement = _OVERRIDES.get(fullname)
        if replacement is None:
            return None
        installed = version("deepagents")
        if installed != SUPPORTED_DEEPAGENTS_VERSION:
            raise ImportError(
                f"Project DeepAgents overrides require {SUPPORTED_DEEPAGENTS_VERSION}, "
                f"but {installed} is installed. Review the local copies before upgrading, "
                f"or set {_ENV_NAME}=0 to use the unmodified upstream implementation."
            )
        return spec_from_file_location(fullname, replacement)


_FINDER = _ProjectDeepAgentsFinder()


def install_deepagents_override() -> None:
    """Register once, without importing DeepAgents or any model provider."""
    setting = os.environ.get(_ENV_NAME, "1").strip().lower()
    if setting in {"0", "false", "no"}:
        return
    if setting not in {"1", "true", "yes"}:
        raise ValueError(f"{_ENV_NAME} must be 1/true/yes or 0/false/no")
    for module_name in _OVERRIDES:
        existing = sys.modules.get(module_name)
        if existing is not None and not getattr(existing, "__SAG_MAKER_DEEPAGENTS_OVERRIDE__", False):
            raise ImportError(
                f"{module_name} was imported before the project override. "
                "Start a fresh process and import src before deepagents, "
                f"or set {_ENV_NAME}=0 to use the upstream implementation."
            )
    if _FINDER not in sys.meta_path:
        sys.meta_path.insert(0, _FINDER)
