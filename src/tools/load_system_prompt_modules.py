"""Tool for progressively disclosing optional system prompt modules."""

from __future__ import annotations

import json
from typing import Annotated, Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.types import Command

from src.prompt.module_registry import PromptModuleId, normalize_prompt_module_ids, render_prompt_modules

_ROUTING_DESCRIPTION = """Load optional system instruction modules before handling the matching situation.

Available modules:
- agent_core_configuration: 智能体模型、MCP、技能规则，询问这些配置时加载。
- skill_search_installation: 技能的搜索与安装规则，涉及技能安装时加载。
- mcp_authentication_failures: MCP 认证错误的处理规则，MCP 返回认证错误时加载。
- environment_variable_updates: 环境变量更新规则，更新环境变量前加载。
- computation_environment_and_scripts: 科学计算环境判断与计算脚本编写规则，无可用 skills 且需要判断计算环境或自行编写计算脚本时加载。

Load all relevant modules in one call when several situations apply. Already loaded modules remain active and do not need to be loaded again."""


@tool("load_system_prompt_modules", description=_ROUTING_DESCRIPTION)
def load_system_prompt_modules(
    modules: Annotated[
        list[PromptModuleId],
        "需要加载的系统提示词模块 ID；同时涉及多个场景时一次传入全部模块。",
    ],
    runtime: ToolRuntime[Any, Any],
) -> Command:
    """Add selected prompt modules to checkpoint state and conversation messages."""

    existing = normalize_prompt_module_ids(runtime.state.get("active_system_prompt_modules", []))
    activated = normalize_prompt_module_ids([*existing, *modules])
    newly_activated = [module_id for module_id in activated if module_id not in existing]
    content = json.dumps(
        {
            "status": "success",
            "activatedModules": activated,
            "message": "Selected system prompt modules were added to the current conversation.",
        },
        ensure_ascii=False,
    )
    messages: list[ToolMessage | SystemMessage] = [
        ToolMessage(
            content=content,
            tool_call_id=runtime.tool_call_id or "",
        )
    ]
    prompt_content = render_prompt_modules(newly_activated)
    if prompt_content:
        messages.append(SystemMessage(content=prompt_content))
    return Command(
        update={
            "active_system_prompt_modules": activated,
            "messages": messages,
        }
    )


__all__ = ["load_system_prompt_modules"]
