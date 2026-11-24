"""Deferred SCNet catalog tools."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from langchain.tools import tool
from langchain_core.tools import ToolException
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from src.logger import get_logger
from src.skills import skill_install_error_message
from src.tools.deferred import deferred
from src.utils.language import localized_text as _t
from src.utils.scnet_catalog import (
    add_scnet_datasets_to_config,
    add_scnet_mcp_to_config,
    add_scnet_skills_to_config,
)

_SCNET_SKILL_INSTALL_LOCK = asyncio.Lock()
logger = get_logger(__name__)


class ScnetTagInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str = Field(default="", description=("Tag category from the SCNet search result."))
    nameCn: str = Field(default="", description=("Chinese tag name."))
    nameEn: str = Field(default="", description=("English tag name."))
    name: str = Field(default="", description=("Generic tag name when provided."))


class ScnetSkillInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    nameEn: str = Field(description=_t("Required. Skill English name, used as the local skill directory name.", "必填。技能英文名，用作本地技能目录名。"))
    httpUrlToRepo: str = Field(
        default="",
        description=_t(
            "Git repository URL for external skills; built-in skills do not require a repository URL.",
            "外部技能填写 Git 仓库 URL；内置技能不需要仓库地址。",
        ),
    )
    nameCn: str = Field(default="", description=_t("Skill Chinese name from the SCNet search result.", "SCNet 搜索结果中的技能中文名。"))
    id: str = Field(default="", description=_t("SCNet skill resource id when available.", "可用时填写 SCNet 技能资源 id。"))
    visibility: str = Field(default="", description=_t("Skill visibility, for example PUBLIC or PRIVATE.", "技能可见性，例如 PUBLIC 或 PRIVATE。"))
    desc: str = Field(default="", description=_t("Skill description from the SCNet search result.", "SCNet 搜索结果中的技能描述。"))
    avatarUrl: str = Field(default="", description=_t("Skill avatar URL when available.", "可用时填写技能头像 URL。"))
    tags: list[ScnetTagInput] = Field(default_factory=list, description=_t("Skill tags from the SCNet search result.", "SCNet 搜索结果中的技能标签。"))
    builtIn: bool = Field(default=False, description=_t("Whether this skill is built in.", "该技能是否为内置技能。"))


class ScnetMcpEnvInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(
        description=(
            "Environment variable placeholder name required by the MCP config, for example API_KEY. "
            "If this is the SCNet/supercomputing internet API KEY, it is already configured by default; "
            "do not ask the user for API KEY information."
        )
    )
    type: str = Field(default="string", description=("Environment variable value type."))
    default_value: Any = Field(default=None, description=("Default value from the SCNet search result, if any."))
    is_required: bool = Field(default=True, description=("Whether this environment variable is required."))
    description: str = Field(default="", description=("User-facing description for this environment variable."))
    link: str = Field(default="", description=("Help link for obtaining this credential, if provided."))


class ScnetMcpInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    nameEn: str = Field(description=("Required. MCP English name from the SCNet search result."))
    mcp_servers_config: str | dict[str, Any] = Field(
        description=("Required. MCP server config as a JSON string or object containing mcpServers."),
        validation_alias=AliasChoices("mcp_servers_config", "mcpServersConfig", "servers"),
    )
    nameCn: str = Field(default="", description=("MCP Chinese name from the SCNet search result."))
    id: str = Field(default="", description=("SCNet MCP resource id when available."))
    visibility: str = Field(default="", description=("MCP visibility, for example PUBLIC or PRIVATE."))
    desc: str = Field(default="", description=("MCP service description from the SCNet search result."))
    image_url: str = Field(
        default="",
        description=("MCP image URL when available."),
        validation_alias=AliasChoices("image_url", "imageUrl"),
    )
    tags: list[ScnetTagInput] = Field(default_factory=list, description=("MCP tags from the SCNet search result."))
    mcp_servers_config_env: list[ScnetMcpEnvInput] = Field(
        default_factory=list,
        description=(
            "Environment variable metadata required by mcp_servers_config. If the required credential is the "
            "SCNet/supercomputing internet API KEY, it is already configured by default; do not tell the user "
            "to provide API KEY information."
        ),
        validation_alias=AliasChoices("mcp_servers_config_env", "mcpServersConfigEnv"),
    )
    timeout: int | float = Field(default=30, description=("MCP connection timeout in seconds."))
    available: bool = Field(
        default=False,
        description=(
            "Always pass false when adding MCP services. Newly added MCP services are not loaded yet, so their "
            "add-time availability is false. To inspect the real availability after restart/loading, read "
            "config/agent.json."
        ),
    )
    builtIn: bool = Field(default=False, description=("Whether this MCP service is built in."))


class ScnetDatasetInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    nameCn: str = Field(default="", description=("Dataset Chinese name from the SCNet search result."))
    nameEn: str = Field(default="", description=("Dataset English name from the SCNet search result."))
    id: str = Field(default="", description=("SCNet dataset resource id when available."))
    dataset_id: str | None = Field(
        default=None,
        description=("Knowledge-base dataset id used by the retrieval tool."),
        validation_alias=AliasChoices("dataset_id", "datasetId"),
    )
    visibility: str = Field(default="", description=("Dataset visibility, for example PUBLIC or PRIVATE."))
    desc: str = Field(default="", description=("Dataset description from the SCNet search result."))
    image_url: str = Field(
        default="",
        description=("Dataset image URL when available."),
        validation_alias=AliasChoices("image_url", "imageUrl"),
    )
    tags: list[ScnetTagInput] = Field(default_factory=list, description=("Dataset tags from the SCNet search result."))
    builtIn: bool = Field(default=False, description=("Whether this dataset is built in."))


async def _restart_agent() -> None:
    from src.agents.manager import AGENTS

    await AGENTS.reset(sync_llm_config=False)


def _dump_items(items: list[BaseModel]) -> list[dict[str, Any]]:
    return [item.model_dump() for item in items]


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


@deferred("skill")
@tool(
    "add_scnet_skills",
    description=(
        "Add selected SCNet community Skills to this agent. This updates skills/skills.json, "
        "clones new skill repositories into the skills directory, updates agent.json, and restarts the agent. "
        "Use this after scnet_aihub_skills_search returns matching skills."
    ),
)
async def add_scnet_skills(
    skills: Annotated[
        list[ScnetSkillInput],
        _t(
            "Selected skills from SCNet search results. Pass nameEn for every item and httpUrlToRepo for external skills; preserve id, nameCn, desc, avatarUrl, and tags when available.",
            "SCNet 搜索结果中选定的技能。每一项都传入 nameEn，外部技能传入 httpUrlToRepo；可用时保留 id、nameCn、desc、avatarUrl 和 tags。",
        ),
    ],
) -> str:
    async with _SCNET_SKILL_INSTALL_LOCK:
        try:
            refreshed_skills = await asyncio.to_thread(add_scnet_skills_to_config, _dump_items(skills))
            await _restart_agent()
        except ToolException:
            raise
        except Exception as exc:
            logger.exception("SCNet skill installation failed and will be returned as a tool error")
            raise ToolException(skill_install_error_message(exc)) from exc
    return _json_result(
        {
            "status": "success",
            "message": "Added SCNet skills and restarted the agent.",
            "skills": refreshed_skills,
        }
    )


@deferred("mcp")
@tool(
    "add_scnet_mcp",
    description=(
        "Add selected SCNet community MCP services to agent.json and restart the agent. "
        "Use this after scnet_aihub_mcp_search returns matching MCP services. If the MCP config requires the "
        "SCNet/supercomputing internet API KEY, it is already configured by default; do not ask the user for "
        "API KEY information or mention that they need to provide it. Newly added MCP items should be added "
        "with available=false because they have not been loaded yet. To check the real post-load availability, "
        "read config/agent.json after the add/restart completes."
    ),
)
async def add_scnet_mcp(
    mcp: Annotated[
        list[ScnetMcpInput],
        (
            "Selected MCP services from SCNet search results. Pass nameEn and mcp_servers_config for every item; "
            "preserve mcp_servers_config_env, id, nameCn, desc, image_url, and tags when available. Set available "
            "to false for newly added MCP services; read config/agent.json for the real status after loading."
        ),
    ],
) -> str:
    configured_mcp = add_scnet_mcp_to_config(_dump_items(mcp))
    await _restart_agent()
    return _json_result(
        {
            "status": "success",
            "message": "Added SCNet MCP services and restarted the agent.",
            "mcp": configured_mcp,
        }
    )


@deferred("knowledge")
@tool(
    "add_scnet_knowledge_search",
    description=(
        "Add selected SCNet community knowledge bases/datasets to agent.json and restart the agent. "
        "Use this after scnet_aihub_knowledge_search returns matching datasets."
    ),
)
async def add_scnet_knowledge_search(
    datasets: Annotated[
        list[ScnetDatasetInput],
        (
            "Selected knowledge bases or datasets from SCNet search results. Pass id or nameEn/nameCn, and preserve dataset_id/datasetId, desc, image_url, and tags when available."
        ),
    ],
) -> str:
    configured_datasets = add_scnet_datasets_to_config(_dump_items(datasets))
    await _restart_agent()
    return _json_result(
        {
            "status": "success",
            "message": "Added SCNet knowledge bases and restarted the agent.",
            "dataset": configured_datasets,
        }
    )


__all__ = [
    "ScnetDatasetInput",
    "ScnetMcpEnvInput",
    "ScnetMcpInput",
    "ScnetSkillInput",
    "ScnetTagInput",
    "add_scnet_knowledge_search",
    "add_scnet_mcp",
    "add_scnet_skills",
]
