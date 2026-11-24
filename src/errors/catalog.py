"""Unified backend error base for the template runtime.

This catalog is hand-maintained and MUST stay semantically aligned with the
matching table in ``sag-maker-vcagent/src/errors``. Same-named domain codes
must mean the same thing and share the same user-facing message, so that a
shared MCP/Model failure yields the same error code and same message in both
runtimes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# --- Error codes --------------------------------------------------------------

# MCP
MCP_TIMEOUT = "MCP_TIMEOUT"
MCP_CONNECT_FAILED = "MCP_CONNECT_FAILED"
MCP_CLIENT_LIFECYCLE_ERROR = "MCP_CLIENT_LIFECYCLE_ERROR"

# Skill
SKILL_SOURCE_REQUIRED = "SKILL_SOURCE_REQUIRED"
SKILL_INSTALL_FAILED = "SKILL_INSTALL_FAILED"
SKILL_VALIDATION_FAILED = "SKILL_VALIDATION_FAILED"

# Model
MODEL_AUTH_FAILED = "MODEL_AUTH_FAILED"
MODEL_RETRY_EXHAUSTED = "MODEL_RETRY_EXHAUSTED"

# Checkpoint / Storage
CHECKPOINT_STORAGE_ERROR = "CHECKPOINT_STORAGE_ERROR"

# Stream
STREAM_CLIENT_DISCONNECTED = "STREAM_CLIENT_DISCONNECTED"
STREAM_EVENT_LOOP_DIED = "STREAM_EVENT_LOOP_DIED"

# Builder / System
BUILDER_DEPENDENCY_SYNC_FAILED = "BUILDER_DEPENDENCY_SYNC_FAILED"
BUILDER_CONFIG_APPLY_FAILED = "BUILDER_CONFIG_APPLY_FAILED"
SYSTEM_INTERNAL_ERROR = "SYSTEM_INTERNAL_ERROR"


# --- Error sources -----------------------------------------------------------

SOURCE_MCP = "mcp"
SOURCE_SKILL = "skill"
SOURCE_MODEL = "model"
SOURCE_CHECKPOINT = "checkpoint"
SOURCE_STREAM = "stream"
SOURCE_BUILDER = "builder"
SOURCE_SYSTEM = "system"


# --- Retry classification ----------------------------------------------------

RETRYABLE_ERROR_CODES = frozenset(
    {
        BUILDER_DEPENDENCY_SYNC_FAILED,
        MCP_TIMEOUT,
        MCP_CONNECT_FAILED,
    }
)


# --- User-facing messages ----------------------------------------------------
#
# Same as vcagent — same code, same message, same retry semantics.

ERROR_MESSAGES: dict[str, str] = {
    # MCP
    MCP_TIMEOUT: "MCP 服务调用失败，任务执行中断，请稍后重试。",
    MCP_CONNECT_FAILED: "MCP 服务调用失败，任务执行中断，请稍后重试。",
    MCP_CLIENT_LIFECYCLE_ERROR: "MCP 服务调用失败，任务执行中断，请稍后重试。",
    # Skill
    SKILL_SOURCE_REQUIRED: "技能仓库地址为空，已保留原有技能，请补充后重试。",
    SKILL_INSTALL_FAILED: "技能下载失败，已保留原有技能，请检查仓库地址和权限。",
    SKILL_VALIDATION_FAILED: "技能文件校验未通过，已保留原有技能，请修正后重试。",
    # Model
    MODEL_AUTH_FAILED: "模型服务无法调用，任务执行中断，请前往模型设置检查。",
    MODEL_RETRY_EXHAUSTED: "服务出现异常，任务执行中断，请稍后重试。",
    # Checkpoint / Storage
    CHECKPOINT_STORAGE_ERROR: "会话内容已达上限，任务无法继续，请创建新对话。",
    # Stream
    STREAM_CLIENT_DISCONNECTED: "连接已断开，请刷新页面重新对话。",
    STREAM_EVENT_LOOP_DIED: "服务出现异常，任务执行中断，请稍后重试。",
    # Builder / System
    BUILDER_DEPENDENCY_SYNC_FAILED: "运行环境准备失败，已保留原有设置，请稍后重试。",
    BUILDER_CONFIG_APPLY_FAILED: "智能体修改未生效，已保留原有设置，请稍后重试。",
    SYSTEM_INTERNAL_ERROR: "服务出现异常，任务执行中断，请稍后重试。",
}

_FALLBACK_MESSAGE = ERROR_MESSAGES[SYSTEM_INTERNAL_ERROR]


def message_for(error_code: str) -> str:
    """Resolve a safe user-facing message for an error code."""
    return ERROR_MESSAGES.get(error_code, _FALLBACK_MESSAGE)


def is_retryable(error_code: str) -> bool:
    return error_code in RETRYABLE_ERROR_CODES


@dataclass(frozen=True)
class ErrorInfo:
    """Structured backend error kept internal; only ``message`` goes outward."""

    error_code: str
    message: str
    source: str
    stage: str
    retryable: bool
    context: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        error_code: str,
        *,
        source: str,
        stage: str,
        message: str | None = None,
        retryable: bool | None = None,
        context: Mapping[str, str] | None = None,
    ) -> ErrorInfo:
        return cls(
            error_code=error_code,
            message=message or message_for(error_code),
            source=source,
            stage=stage,
            retryable=is_retryable(error_code) if retryable is None else retryable,
            context=dict(context or {}),
        )
