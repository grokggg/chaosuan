from __future__ import annotations

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile

_PROFILE_KEY = "openai"
_PROFILE_REGISTERED = False

TASK_TOOL_DESCRIPTION = """Delegate a task to one of the available specialized agents.

Available specialized agents:
{available_agents}

Use this tool only when the task matches an agent description. Provide all necessary context and the expected output."""


def register_project_harness_profile() -> None:
    """Register static DeepAgents behavior shared by all project models."""
    global _PROFILE_REGISTERED  # noqa: PLW0603
    if _PROFILE_REGISTERED:
        return

    register_harness_profile(
        _PROFILE_KEY,
        HarnessProfile(
            tool_description_overrides={"task": TASK_TOOL_DESCRIPTION},
            excluded_tools=frozenset({"delete"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
    _PROFILE_REGISTERED = True


__all__ = ["TASK_TOOL_DESCRIPTION", "register_project_harness_profile"]
