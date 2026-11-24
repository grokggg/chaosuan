from __future__ import annotations

import importlib
import inspect
from pathlib import Path

from langchain.agents.middleware.types import AgentMiddleware

from src.logger import get_logger

logger = get_logger(__name__)
_MIDDLEWARES_DIR = Path(__file__).resolve().parent
_EXCLUDED_AUTOLOAD_MODULES: set[str] = {"resource_statistics_middleware", "plan_first_middleware"}
_MIDDLEWARE_PRIORITY = {
    "tool_description_param_middleware": 0,
}


def load_middlewares() -> list[AgentMiddleware]:
    middlewares: list[AgentMiddleware] = []
    package_name = __name__

    module_paths = sorted(
        _MIDDLEWARES_DIR.glob("*.py"),
        key=lambda path: (_MIDDLEWARE_PRIORITY.get(path.stem, 100), path.name),
    )
    for module_path in module_paths:
        if module_path.name == "__init__.py":
            continue
        if module_path.stem in _EXCLUDED_AUTOLOAD_MODULES:
            continue

        module_name = f"{package_name}.{module_path.stem}"
        module = importlib.import_module(module_name)

        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate is AgentMiddleware:
                continue
            if candidate.__module__ != module.__name__:
                continue
            if not issubclass(candidate, AgentMiddleware):
                continue

            logger.info("Loading middleware class=%s module=%s", candidate.__name__, module_name)
            middlewares.append(candidate())

    return middlewares


__all__ = ["load_middlewares"]
