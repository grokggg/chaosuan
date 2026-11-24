"""Deferred environment-management tools."""

from __future__ import annotations

import os
import re
from typing import Annotated

from langchain.tools import tool

from src.tools.deferred import deferred

_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_environment_updates(variables: dict[str, str]) -> dict[str, str]:
    if not isinstance(variables, dict) or not variables:
        raise ValueError("variables must be a non-empty object")

    normalized: dict[str, str] = {}
    for name, value in variables.items():
        if not isinstance(name, str) or not _ENV_NAME_PATTERN.fullmatch(name):
            raise ValueError(f"invalid environment variable name: {name!r}")
        if value is None:
            raise ValueError(f"environment variable {name} value must not be null")
        normalized[name] = str(value)
    return normalized


@deferred("environment")
@tool(
    "update_environment_variables",
    description=(
        "Update one or more environment variables in the current Python process, "
        "then rebuild and warm up the cached agent. Use this when runtime credentials "
        "such as MCP_API_KEY need to take effect without restarting the process."
    ),
)
async def update_environment_variables(
    variables: Annotated[
        dict[str, str],
        ("Environment variables to set in the current Python process, for example {'MCP_API_KEY': '...'}"),
    ],
) -> str:
    """Update process environment variables and rebuild the cached agent."""

    updates = _validate_environment_updates(variables)
    for name, value in updates.items():
        os.environ[name] = value

    from src.agents.manager import AGENTS

    await AGENTS.reset(sync_llm_config=False, reload_tool_modules=None)

    names = ", ".join(sorted(updates))
    return f"Updated environment variables and restarted the agent successfully. Updated keys: {names}"


__all__ = ["update_environment_variables"]
