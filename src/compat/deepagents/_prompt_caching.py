"""DeepAgents 0.7.11 prompt caching without Anthropic middleware.

Derived from DeepAgents (MIT); see ``LICENSE.txt``. Preserve optional
Bedrock/Fireworks caching behavior, but never import langchain-anthropic here.
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import Any, cast

from langchain.agents.middleware.types import AgentMiddleware

logger = logging.getLogger(__name__)


def _optional_caching_middleware(package: str, class_name: str) -> AgentMiddleware[Any, Any, Any] | None:
    module_name = f"{package}.middleware.prompt_caching"
    try:
        module = import_module(module_name)
    except ImportError as exc:
        if exc.name not in {package, f"{package}.middleware", module_name}:
            raise
        logger.debug("%s prompt caching middleware is unavailable.", package, exc_info=exc)
        return None
    middleware_cls = getattr(module, class_name)
    return cast("AgentMiddleware[Any, Any, Any]", middleware_cls(unsupported_model_behavior="ignore"))


def append_prompt_caching_middleware(middleware: list[AgentMiddleware[Any, Any, Any]]) -> None:
    """Keep other optional provider middleware; Anthropic is deliberately absent."""
    for package, class_name in (
        ("langchain_aws", "BedrockPromptCachingMiddleware"),
        ("langchain_fireworks", "FireworksPromptCachingMiddleware"),
    ):
        optional = _optional_caching_middleware(package, class_name)
        if optional is not None:
            middleware.append(optional)
