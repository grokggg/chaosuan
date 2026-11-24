"""Registry and renderer for on-demand system prompt modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

PromptModuleId = Literal[
    "agent_core_configuration",
    "skill_search_installation",
    "mcp_authentication_failures",
    "environment_variable_updates",
    "computation_environment_and_scripts",
]

_PROMPT_MODULE_DIR = Path(__file__).resolve().parent / "prompt_modules"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PromptModule:
    module_id: PromptModuleId
    filename: str
    description: str


PROMPT_MODULES: Final = (
    PromptModule(
        module_id="agent_core_configuration",
        filename="agent_core_configuration.md",
        description="智能体模型、MCP、技能规则，询问这些配置时加载",
    ),
    PromptModule(
        module_id="skill_search_installation",
        filename="skill_search_installation.md",
        description="技能的搜索与安装规则，涉及技能安装时加载",
    ),
    PromptModule(
        module_id="mcp_authentication_failures",
        filename="mcp_authentication_failures.md",
        description="MCP 认证错误的处理规则，MCP 返回认证错误时加载",
    ),
    PromptModule(
        module_id="environment_variable_updates",
        filename="environment_variable_updates.md",
        description="环境变量更新规则，更新环境变量前加载",
    ),
    PromptModule(
        module_id="computation_environment_and_scripts",
        filename="computation_environment_and_scripts.md",
        description="科学计算环境判断与计算脚本编写规则，无可用技能且需要判断环境或编写脚本时加载",
    ),
)


def _load_prompt_module_texts() -> dict[PromptModuleId, str]:
    texts: dict[PromptModuleId, str] = {}
    for module in PROMPT_MODULES:
        text = (_PROMPT_MODULE_DIR / module.filename).read_text(encoding="utf-8").strip()
        texts[module.module_id] = text.replace("${PROJECT_ROOT}", str(_PROJECT_ROOT))
    return texts


_PROMPT_MODULE_TEXTS = _load_prompt_module_texts()
PROMPT_MODULE_IDS: Final = tuple(module.module_id for module in PROMPT_MODULES)


def normalize_prompt_module_ids(values: object) -> list[PromptModuleId]:
    if not isinstance(values, list):
        return []
    requested = {value for value in values if isinstance(value, str) and value in PROMPT_MODULE_IDS}
    return [module_id for module_id in PROMPT_MODULE_IDS if module_id in requested]


def render_prompt_modules(values: object) -> str:
    return "\n\n".join(_PROMPT_MODULE_TEXTS[module_id] for module_id in normalize_prompt_module_ids(values))


__all__ = [
    "PROMPT_MODULE_IDS",
    "PROMPT_MODULES",
    "PromptModule",
    "PromptModuleId",
    "normalize_prompt_module_ids",
    "render_prompt_modules",
]
