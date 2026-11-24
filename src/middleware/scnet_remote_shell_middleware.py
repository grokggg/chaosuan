from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.logger import get_logger
from src.middleware.tool_handoff_middleware import extract_job_terminal_data

logger = get_logger(__name__)

_TARGET_TOOL_NAME = "scnet_remote_shell_execute"
_SCNET_EXPORT_PREFIX = "export SCNET=TRUE && "
_SBATCH_COMMAND_PATTERN = re.compile(r"(?:^|&&|\|\||[;|&()\n])\s*sbatch(?=\s|$)")
_SCNET_EXPORT_PATTERN = re.compile(r"^\s*export\s+SCNET=TRUE\s*&&")
_MAX_RESULT_CHARS = 10_000
_TERMINAL_JOB_INSTRUCTION = (
    "The job has already reached a terminal state. Do not stop for asynchronous monitoring; "
    "continue the remaining workflow, including required post-processing and report generation."
)


def _prepare_sbatch_command(request: ToolCallRequest) -> ToolCallRequest:
    tool_call = request.tool_call
    if tool_call.get("name") != _TARGET_TOOL_NAME:
        return request

    args = tool_call.get("args")
    if not isinstance(args, dict):
        return request
    command = args.get("command")
    if (
        not isinstance(command, str)
        or not _SBATCH_COMMAND_PATTERN.search(command)
        or _SCNET_EXPORT_PATTERN.match(command)
    ):
        return request

    return request.override(
        tool_call={
            **tool_call,
            "args": {
                **args,
                "command": f"{_SCNET_EXPORT_PREFIX}{command}",
            },
        }
    )


def _truncate_tool_message(message: ToolMessage) -> ToolMessage:
    content = message.content
    if not isinstance(content, str) or len(content) <= _MAX_RESULT_CHARS:
        return message

    original_length = len(content)
    notice = (
        f"[工具结果已截断：原始结果共 {original_length} 个字符，"
        f"当前仅保留前 {_MAX_RESULT_CHARS} 个字符。请缩小查询范围、限制输出行数]"
    )
    logger.warning(
        "Tool result truncated tool=%s original_chars=%d retained_chars=%d",
        _TARGET_TOOL_NAME,
        original_length,
        _MAX_RESULT_CHARS,
    )
    return message.model_copy(update={"content": f"{content[:_MAX_RESULT_CHARS]}\n\n{notice}"})


def _normalize_terminal_job_message(message: ToolMessage) -> ToolMessage:
    content = message.content
    if not isinstance(content, str):
        return message

    try:
        payload = json.loads(content.strip())
    except (json.JSONDecodeError, TypeError):
        return message
    if not isinstance(payload, dict):
        return message

    data = extract_job_terminal_data(payload)
    if data is None:
        return message

    data["agentAction"] = "continue_response"
    data["agentInstruction"] = _TERMINAL_JOB_INSTRUCTION
    return message.model_copy(update={"content": json.dumps(payload, ensure_ascii=False)})


def _process_tool_message(message: ToolMessage) -> ToolMessage:
    return _truncate_tool_message(_normalize_terminal_job_message(message))


def _process_result(result: ToolMessage | Command) -> ToolMessage | Command:
    if isinstance(result, ToolMessage):
        return _process_tool_message(result)

    update = result.update
    if not isinstance(update, dict):
        return result
    messages = update.get("messages")
    if not isinstance(messages, list | tuple):
        return result

    processed_messages = [
        _process_tool_message(message) if isinstance(message, ToolMessage) else message
        for message in messages
    ]
    return Command(
        graph=result.graph,
        update={**update, "messages": processed_messages},
        resume=result.resume,
        goto=result.goto,
    )


class ScnetRemoteShellMiddleware(AgentMiddleware):
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        prepared_request = _prepare_sbatch_command(request)
        result = handler(prepared_request)
        if request.tool_call.get("name") != _TARGET_TOOL_NAME:
            return result
        return _process_result(result)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        prepared_request = _prepare_sbatch_command(request)
        result = await handler(prepared_request)
        if request.tool_call.get("name") != _TARGET_TOOL_NAME:
            return result
        return _process_result(result)


__all__ = ["ScnetRemoteShellMiddleware"]
