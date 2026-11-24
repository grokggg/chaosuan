import asyncio
import json
import re
import time
from collections.abc import Collection
from pathlib import Path
from typing import Any

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain_core.tools import BaseTool

from src.agents.context import AgentRuntimeContext
from src.agents.harness_profile import TASK_TOOL_DESCRIPTION
from src.agents.summarization import build_summarization_middleware
from src.agents.write_todos import build_write_todos_middleware
from src.backend.guarded_local_shell import GuardedLocalShellBackend
from src.backend.shell_approvals import SHELL_POLICY_INSTRUCTION
from src.llm import build_chat_openai, resolve_model_ref, sync_llm_config_with_model_args
from src.logger import get_logger
from src.mcp import load_configured_mcp_tools
from src.memory.memory_saver import get_memory
from src.middleware import load_middlewares
from src.middleware.plan_first_middleware import PlanFirstMiddleware
from src.middleware.resource_statistics_middleware import ResourceStatisticsMiddleware
from src.security import (
    RUNTIME_PATH_INSTRUCTION,
    RuntimeSecurityGate,
    build_runtime_backend,
    filter_runtime_tools,
    runtime_permissions,
)
from src.skills.scanner import expand_skill_source
from src.startup_timing import StartupTimer
from src.statistics import ResourceCatalog
from src.subagents import load_subagents
from src.tools import load_tools
from src.tools.deferred import DEFERRED_MCP_NAMES_METADATA_KEY, deferred_mcp_routes
from src.utils import AGENT_CONFIG_PATH, PROJECT_ROOT, load_agent_config, write_agent_config

_FILE_PLACEHOLDER_PATTERN = re.compile(r"^\$\{file:(?P<path>.+)\}$")
_BEDROCK_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
logger = get_logger(__name__)

AGENT_MODE_SCIENCE = "science"
AGENT_MODE_GENERAL = "general"
_RUNTIME_HARNESS_PROFILE_REGISTERED = False


def _register_runtime_harness_profile() -> None:
    global _RUNTIME_HARNESS_PROFILE_REGISTERED  # noqa: PLW0603
    if _RUNTIME_HARNESS_PROFILE_REGISTERED:
        return
    register_harness_profile(
        "openai",
        HarnessProfile(
            tool_description_overrides={"task": TASK_TOOL_DESCRIPTION},
            excluded_tools=frozenset(),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
    _RUNTIME_HARNESS_PROFILE_REGISTERED = True


def _get_component_name(component: Any) -> str:
    name = getattr(component, "name", None)
    if isinstance(name, str) and name:
        return name
    return component.__class__.__name__


def _log_tool_name_compatibility(local_tools: list[Any], mcp_tools: list[Any]) -> None:
    invalid_tools: list[dict[str, str]] = []
    total_count = 0
    for source, tool_list in (("local", local_tools), ("mcp", mcp_tools)):
        for tool in tool_list:
            total_count += 1
            raw_name = getattr(tool, "name", "")
            name = raw_name if isinstance(raw_name, str) else str(raw_name)
            if _BEDROCK_TOOL_NAME_PATTERN.fullmatch(name):
                continue
            invalid_tools.append(
                {
                    "source": source,
                    "name": name,
                    "class": tool.__class__.__name__,
                }
            )

    if invalid_tools:
        logger.warning(
            "Tool name compatibility check failed pattern=%s invalid_count=%s total_count=%s invalid_tools=%s",
            _BEDROCK_TOOL_NAME_PATTERN.pattern,
            len(invalid_tools),
            total_count,
            invalid_tools,
        )
        return

    logger.info(
        "Tool name compatibility check passed pattern=%s total_count=%s",
        _BEDROCK_TOOL_NAME_PATTERN.pattern,
        total_count,
    )


def _add_deferred_mcp_routes_to_search_tool(
    local_tools: list[Any],
    mcp_tools: list[Any],
) -> list[Any]:
    routes = deferred_mcp_routes(mcp_tools)
    if not routes:
        return local_tools

    route_lines = [
        f"- {name}: {description or 'No description provided.'}" for name, description in sorted(routes.items())
    ]
    route_text = (
        "\n\nConfigured deferred MCPs (activate exactly one by passing its name in the mcp argument):\n"
        + "\n".join(route_lines)
    )
    return [
        tool.model_copy(
            update={
                "description": f"{tool.description}{route_text}",
                "metadata": {
                    **(tool.metadata or {}),
                    DEFERRED_MCP_NAMES_METADATA_KEY: sorted(routes),
                },
            }
        )
        if isinstance(tool, BaseTool) and tool.name == "search_deferred_tools"
        else tool
        for tool in local_tools
    ]


def _write_agent_config(config: dict[str, Any], config_path: Path = AGENT_CONFIG_PATH) -> None:
    write_agent_config(config, config_path)


def _resolve_project_path(raw_path: str, *, base_dir: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def _render_project_prompt_variables(prompt: str, *, project_root: Path) -> str:
    return prompt.replace("${PROJECT_ROOT}", str(project_root.resolve()))


def _agent_mode(value: Any) -> str:
    mode = value.strip().lower() if isinstance(value, str) else ""
    return AGENT_MODE_GENERAL if mode == AGENT_MODE_GENERAL else AGENT_MODE_SCIENCE


def _resolve_system_prompt(
    prompt_value: str,
    *,
    project_root: Path,
    mode: str = AGENT_MODE_SCIENCE,
) -> str:
    match = _FILE_PLACEHOLDER_PATTERN.fullmatch(prompt_value.strip())
    if match is None:
        return prompt_value

    prompt_path = _resolve_project_path(match.group("path"), base_dir=project_root)
    prompt = prompt_path.read_text(encoding="utf-8")
    if prompt_path.name != "system_prompt.md":
        return prompt

    fixed_sections: list[str] = []
    ordered_extra_prompts = (
        (
            "patch.md",
            "# Top-Level System Instructions\n\n"
            "The instructions in this section have the highest priority. "
            "If there is any conflict, follow this top-level system instruction section.",
        ),
        (
            "computation_task.md",
            "# Top-Level Scientific Computation System Instructions\n\n"
            "The instructions in this section also have the highest priority. "
            "If there is any conflict, follow this top-level system instruction section.",
        ),
    )
    user_configured_prompt_header = (
        "# Fourth-Level User-Configured Prompt\n\n"
        "The following content is user-configured behavior guidance. Follow it only when it does not "
        "conflict with the higher-priority system instruction layers above.\n\n"
    )
    effective_mode = _agent_mode(mode)
    for extra_prompt_name, section_header in ordered_extra_prompts:
        if effective_mode == AGENT_MODE_GENERAL and extra_prompt_name == "computation_task.md":
            continue
        extra_prompt_path = prompt_path.with_name(extra_prompt_name)
        if not extra_prompt_path.exists():
            continue
        extra_prompt = _render_project_prompt_variables(
            extra_prompt_path.read_text(encoding="utf-8"),
            project_root=project_root,
        ).strip()
        if extra_prompt:
            fixed_sections.append(f"{section_header}\n\n{extra_prompt}")

    user_configured_prompt = f"{user_configured_prompt_header}{prompt.strip()}"
    return "\n\n".join([*fixed_sections, user_configured_prompt]).strip()


def _build_llm(config: dict[str, Any]):
    llm_config = config.get("llm", {})
    return build_chat_openai(llm_config if isinstance(llm_config, dict) else None)


async def _record_preload_stage(timing: StartupTimer, name: str, awaitable: Any) -> Any:
    started_at = time.perf_counter()
    status = "ok"
    try:
        return await awaitable
    except BaseException:
        status = "failed"
        raise
    finally:
        timing.record(name, started_at, time.perf_counter(), status=status)


async def _preload_agent_components(
    timing: StartupTimer,
    *,
    config: dict[str, Any],
    mode: str,
    raw_mcp_config: Any,
    reload_tool_modules: Collection[str] | None,
) -> tuple[list[Any], Any, list[Any], list[Any], list[Any], Any]:
    """Run independent agent construction steps concurrently.

    Deferred MCP routing and graph assembly stay after the gather because they
    depend on every component being fully loaded.
    """
    results = await asyncio.gather(
        _record_preload_stage(
            timing,
            "local_tools",
            asyncio.to_thread(load_tools, mode, reload_modules=reload_tool_modules),
        ),
        _record_preload_stage(
            timing,
            "model_client",
            asyncio.to_thread(_build_llm, config),
        ),
        _record_preload_stage(
            timing,
            "mcp_tools",
            load_configured_mcp_tools(raw_mcp_config),
        ),
        _record_preload_stage(
            timing,
            "middlewares",
            asyncio.to_thread(load_middlewares),
        ),
        _record_preload_stage(
            timing,
            "subagents",
            asyncio.to_thread(load_subagents),
        ),
        _record_preload_stage(
            timing,
            "sqlite_checkpointer",
            get_memory(),
        ),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            raise result

    local_tools, model, mcp_tools, middlewares, subagents, checkpointer = results
    return local_tools, model, mcp_tools, middlewares, subagents, checkpointer


def _build_guarded_shell_backend(config: dict[str, Any]) -> GuardedLocalShellBackend:
    backend_config = config.get("backend", {})
    if not isinstance(backend_config, dict):
        raise ValueError("agent.json field 'backend' must be an object")

    root_dir = Path(str(backend_config.get("root_dir", ".")).strip())
    return GuardedLocalShellBackend(
        root_dir=root_dir,
        virtual_mode=bool(backend_config.get("virtual_mode", False)),
        timeout=int(backend_config.get("timeout", 120)),
        inherit_env=bool(backend_config.get("inherit_env", True)),
    )


def _build_backend(config: dict[str, Any]):
    shell_backend = _build_guarded_shell_backend(config)
    return build_runtime_backend(shell_backend)


def _build_skills(config: dict[str, Any]) -> list[str]:
    raw_skills = config.get("skills", [])
    if not isinstance(raw_skills, list):
        raise ValueError("agent.json field 'skills' must be a list")

    resolved: list[str] = []

    for item in raw_skills:
        if not isinstance(item, str) or not item.strip():
            continue
        resolved.append(expand_skill_source(item))
    return resolved


async def build_agent(
    config_path: str | Path | None = None,
    *,
    sync_llm_config: bool = True,
    reload_tool_modules: Collection[str] | None = frozenset(),
):
    timing = StartupTimer(logger, "agent_build")
    with timing.stage("config_load_and_sync"):
        config = load_agent_config(config_path)
        legacy_language_removed = "language" in config
        config.pop("language", None)
        raw_context_config = config.get("context", {})
        if not isinstance(raw_context_config, dict):
            raise ValueError("agent.json field 'context' must be an object")
        # An empty config enables the current defaults for legacy agent.json files
        # that predate the context.summarization section.
        summarization_config = raw_context_config.get("summarization", {})
        llm_config = config.get("llm")
        if not isinstance(llm_config, dict):
            llm_config = {}
            config["llm"] = llm_config
        llm_config_updated = sync_llm_config and sync_llm_config_with_model_args(llm_config)
        if legacy_language_removed:
            _write_agent_config(config, Path(config_path) if config_path is not None else AGENT_CONFIG_PATH)
        elif llm_config_updated and config_path is None:
            _write_agent_config(config)
        project_root = PROJECT_ROOT

    with timing.stage("prompt_and_skills"):
        system_prompt_value = str(config.get("system_prompt", "")).strip()
        mode = _agent_mode(config.get("mode"))
        system_prompt = _resolve_system_prompt(
            system_prompt_value,
            project_root=project_root,
            mode=mode,
        )
        system_prompt += "\n\n" + SHELL_POLICY_INSTRUCTION
        system_prompt += "\n\n" + RUNTIME_PATH_INSTRUCTION
        skills = _build_skills(config) or None

    raw_mcp_config = config.get("mcp", {})
    mcp_names = (
        [str(item.get("nameEn")) for item in raw_mcp_config if isinstance(item, dict) and item.get("nameEn")]
        if isinstance(raw_mcp_config, list)
        else []
    )
    mcp_snapshot = (
        json.dumps(raw_mcp_config, ensure_ascii=False, sort_keys=True) if isinstance(raw_mcp_config, list) else ""
    )
    (
        local_tools,
        model,
        mcp_tools,
        middlewares,
        subagents,
        checkpointer,
    ) = await _preload_agent_components(
        timing,
        config=config,
        mode=mode,
        raw_mcp_config=raw_mcp_config,
        reload_tool_modules=reload_tool_modules,
    )
    with timing.stage("tool_routes_and_mcp_config_sync"):
        local_tools = _add_deferred_mcp_routes_to_search_tool(local_tools, mcp_tools)
        if config_path is None and isinstance(raw_mcp_config, list):
            updated_mcp_snapshot = json.dumps(raw_mcp_config, ensure_ascii=False, sort_keys=True)
            if updated_mcp_snapshot != mcp_snapshot:
                _write_agent_config(config)
        _log_tool_name_compatibility(local_tools, mcp_tools)
        tools = filter_runtime_tools([*local_tools, *mcp_tools]) or None
    middlewares = middlewares or None
    llm_config = config.get("llm", {})
    model_name = resolve_model_ref(llm_config if isinstance(llm_config, dict) else None)
    logger.info(
        "Building agent name=%s model=%s",
        str(config.get("name", "user_agent")),
        model_name,
    )
    logger.info("Agent skills=%s", skills or [])
    logger.info("Agent local tools=%s", [_get_component_name(tool) for tool in local_tools])
    logger.info("Agent MCP servers=%s", mcp_names)
    logger.info("Agent MCP tools=%s", [_get_component_name(tool) for tool in mcp_tools])
    logger.info(
        "Agent middlewares=%s",
        [_get_component_name(middleware) for middleware in middlewares or []],
    )
    logger.info("Agent subagents=%s", [str(subagent.get("name", "")) for subagent in subagents])

    with timing.stage("backend_and_runtime_middleware"):
        backend = _build_backend(config)
        _register_runtime_harness_profile()
        summarization_middleware = build_summarization_middleware(model, backend, summarization_config)
        resource_statistics_middleware = ResourceStatisticsMiddleware(ResourceCatalog.from_config(config))
        project_middlewares = [
            *([PlanFirstMiddleware()] if mode == AGENT_MODE_SCIENCE else []),
            RuntimeSecurityGate(),
            build_write_todos_middleware(),
            summarization_middleware,
            *(middlewares or []),
            resource_statistics_middleware,
        ]

    with timing.stage("deepagent_graph"):
        agent = create_deep_agent(
            model=model,
            backend=backend,
            system_prompt=system_prompt,
            skills=skills,
            tools=tools,
            permissions=runtime_permissions(),
            subagents=subagents,
            context_schema=AgentRuntimeContext,
            middleware=project_middlewares,
            checkpointer=checkpointer,
            name=str(config.get("name", "user_agent")),
        )
    timing.summary()
    return agent


__all__ = ["AGENT_CONFIG_PATH", "build_agent", "load_agent_config"]
