from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, NotRequired
from zoneinfo import ZoneInfo

from langchain.agents.middleware.types import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain_core.messages import ContentBlock, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from src.agents.context import AgentRuntimeContext
from src.backend.shell_approvals import protected_denial_context
from src.constants import SCNET_CLUSTER
from src.logger import get_logger
from src.utils import (
    conversation_workspace,
    dict_string,
)

logger = get_logger(__name__)

WORKSPACE_PROMPT = """

# 当前工作目录

当前时间是：

`{current_time}`

当前对话的工作目录是：

`{workspace}`

当前服务进程环境变量 `$HOME` 的实际值是：

`{home}`

请以此处直接读取的环境变量值为准，不要根据当前工作目录推断 `$HOME`。

请将此目录作为当前对话中新建或修改文件的默认位置。
{cluster_context}
"""


_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
UPLOADED_FILES_PROMPT_HEADER = "## 本轮用户上传的文件："
OSS_INPUT_TYPES = {"file", "image", "video", "audio"}
OSS_TEXT_MAX_CHARS_PER_ITEM = 10_000
OSS_TEXT_MAX_CHARS_TOTAL = 50_000


def _append_to_system_message(system_message: SystemMessage | None, text: str) -> SystemMessage:
    content_blocks: list[ContentBlock] = list(system_message.content_blocks) if system_message else []
    content_blocks.append({"type": "text", "text": f"\n\n{text}" if content_blocks else text})
    return SystemMessage(content_blocks=content_blocks)


class PromptContextState(AgentState[Any]):
    oss_files: NotRequired[dict[str, str]]
    active_system_prompt_modules: NotRequired[list[str]]
    report_messages: NotRequired[list[str]]


def _nonempty_uploaded_items(context: AgentRuntimeContext) -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    for item in context.inputs or []:
        if not isinstance(item, dict) or item.get("type") not in {*OSS_INPUT_TYPES, "efile"}:
            continue
        resource = item.get("resource")
        if not isinstance(resource, dict):
            continue
        kind = str(item["type"])
        if kind == "efile" and (dict_string(resource, "name") or dict_string(resource, "url")):
            items.append((kind, resource))
        elif kind in OSS_INPUT_TYPES and (dict_string(resource, "name") or dict_string(resource, "url")):
            items.append((kind, resource))
    return items


def _format_efile_item(item: dict[str, Any]) -> str:
    path = dict_string(item, "url")
    mime_type = dict_string(item, "mimeType")
    lines = [
        "- 文件名：" + dict_string(item, "name"),
        "  用户上传文件路径：" + path,
        "  文件所在集群 ID：" + dict_string(item, "clusterId"),
        "  文件类型：" + mime_type,
    ]
    return "\n".join(lines)


def _format_oss_item(kind: str, item: dict[str, Any], *, remaining_text_chars: int) -> tuple[str, int]:
    mime_type = dict_string(item, "mimeType")
    text = dict_string(item, "text")
    lines = [
        "- 文件名：" + dict_string(item, "name"),
        "  来源：用户上传的文件，已存储于对象存储",
        "  输入类型：" + kind,
        "  文件类型：" + mime_type,
        "  下载方式：可调用 download_oss_files 下载到当前工作目录",
    ]
    consumed_text_chars = 0
    if text:
        text_limit = min(OSS_TEXT_MAX_CHARS_PER_ITEM, max(remaining_text_chars, 0))
        included_text = text[:text_limit]
        consumed_text_chars = len(included_text)
        if included_text:
            lines.extend(["  文件解析文本：", included_text])
        else:
            lines.append(f"  文件解析文本：已省略（本轮累计已达到 {OSS_TEXT_MAX_CHARS_TOTAL} 字符上限）")
        if consumed_text_chars < len(text) and included_text:
            lines.append(
                "  文件解析文本已截断"
                f"（单文件最多保留 {OSS_TEXT_MAX_CHARS_PER_ITEM} 字符，"
                f"本轮累计最多保留 {OSS_TEXT_MAX_CHARS_TOTAL} 字符）"
            )
    else:
        lines.append("  文件内容：尚未解析，请先下载后再读取")
    return "\n".join(lines), consumed_text_chars


def _merge_oss_files(state: AgentState, uploaded_items: list[tuple[str, dict[str, Any]]]) -> dict[str, str]:
    existing = state.get("oss_files")
    merged = dict(existing) if isinstance(existing, dict) else {}
    for kind, item in uploaded_items:
        if kind not in OSS_INPUT_TYPES:
            continue
        name = dict_string(item, "name")
        url = dict_string(item, "url")
        if name and url:
            merged[name] = url
    return merged


def _oss_files_changed(state: AgentState, oss_files: dict[str, str]) -> bool:
    existing = state.get("oss_files")
    return oss_files != existing if isinstance(existing, dict) else bool(oss_files)


def _clear_uploaded_items(context: AgentRuntimeContext) -> None:
    context.inputs = None


def _build_uploaded_files_content(context: AgentRuntimeContext) -> str:
    conversation_id = context.conversation_id
    if not conversation_id:
        return ""

    if context.uploaded_file_prompt is not None:
        return context.uploaded_file_prompt

    uploaded_items = _nonempty_uploaded_items(context)
    if not uploaded_items:
        _clear_uploaded_items(context)
        return ""

    efile_lines: list[str] = []
    oss_lines: dict[str, list[str]] = {kind: [] for kind in OSS_INPUT_TYPES}
    remaining_text_chars = OSS_TEXT_MAX_CHARS_TOTAL
    for kind, item in uploaded_items:
        if kind == "efile":
            efile_lines.append(_format_efile_item(item))
        elif kind in OSS_INPUT_TYPES:
            formatted_item, consumed_text_chars = _format_oss_item(
                kind,
                item,
                remaining_text_chars=remaining_text_chars,
            )
            oss_lines[kind].append(formatted_item)
            remaining_text_chars -= consumed_text_chars

    sections: list[str] = []
    if efile_lines:
        sections.append("## 上传的 efile 文件：\n" + "\n\n".join(efile_lines))
    for kind in ("file", "image", "video", "audio"):
        if oss_lines[kind]:
            sections.append(f"## 上传的 {kind} 文件：\n" + "\n\n".join(oss_lines[kind]))

    if not sections:
        _clear_uploaded_items(context)
        return ""

    context.uploaded_file_prompt = UPLOADED_FILES_PROMPT_HEADER + "\n\n" + "\n\n".join(sections)
    logger.info(
        "Uploaded files prompt built conversation_id=%s prompt=%s",
        conversation_id,
        context.uploaded_file_prompt,
    )
    _clear_uploaded_items(context)
    return context.uploaded_file_prompt


def _message_contains_uploaded_files_prompt(message: HumanMessage) -> bool:
    content = message.content
    if isinstance(content, str):
        return UPLOADED_FILES_PROMPT_HEADER in content
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str) and UPLOADED_FILES_PROMPT_HEADER in item:
                return True
            if isinstance(item, dict) and UPLOADED_FILES_PROMPT_HEADER in str(item.get("text") or ""):
                return True
    return False


def _append_to_human_message(
    message: HumanMessage,
    uploaded_files_prompt: str,
) -> HumanMessage:
    if _message_contains_uploaded_files_prompt(message):
        return message

    content = message.content
    if isinstance(content, str):
        text = f"{content.rstrip()}\n\n{uploaded_files_prompt}" if content.strip() else uploaded_files_prompt
        updated_content = text
    elif isinstance(content, list):
        updated_content = [*content, {"type": "text", "text": uploaded_files_prompt}]
    else:
        updated_content = uploaded_files_prompt
    return message.model_copy(update={"content": updated_content})


def _current_cluster_context() -> str:
    cluster_id = os.getenv("CLUSTER_ID", "").strip()
    if not cluster_id:
        return ""
    cluster_name = SCNET_CLUSTER.get(cluster_id)
    if not cluster_name:
        return f"""

当前工作集群 ID 是：

`{cluster_id}`

该集群 ID 未能匹配到集群名称。集群相关工具调用与内部流程必须使用上述集群 ID；在获得准确的集群名称前，不要自行编造名称。
"""
    return f"""

当前工作集群是：

- 集群 ID：`{cluster_id}`
- 集群名称：{cluster_name}

集群相关工具调用描述、计划与内部流程必须使用集群 ID `{cluster_id}`。面向用户表述时必须使用完整的集群名称“{cluster_name}”，不要使用集群 ID。例如，应表述为“查询{cluster_name}的队列”。完整名称中的区域名和地点名都必须保留，例如华东一区【昆山】，禁止省略地点名而只表述为“华东一区”。注意在计划中、工具描述中、流程中，保持相同的区域名，不要变化。
"""


def _current_time_context() -> str:
    return datetime.now(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def _current_home_context() -> str:
    return os.environ.get("HOME", "（未设置）")


class PromptContextMiddleware(AgentMiddleware[PromptContextState, Any, Any]):
    state_schema = PromptContextState

    def _uploaded_files_state_update(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        context = runtime.context
        if not isinstance(context, AgentRuntimeContext):
            return None

        uploaded_items = _nonempty_uploaded_items(context)
        oss_files = _merge_oss_files(state, uploaded_items)
        messages = list(state.get("messages", []))
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not isinstance(message, HumanMessage):
                continue
            if _message_contains_uploaded_files_prompt(message):
                return {"oss_files": oss_files} if _oss_files_changed(state, oss_files) else None
            uploaded_files_prompt = _build_uploaded_files_content(context)
            if not uploaded_files_prompt:
                return {"oss_files": oss_files} if _oss_files_changed(state, oss_files) else None
            updated_message = _append_to_human_message(message, uploaded_files_prompt)
            update: dict[str, Any] = {"messages": [updated_message]}
            if _oss_files_changed(state, oss_files):
                update["oss_files"] = oss_files
            return update
        return {"oss_files": oss_files} if _oss_files_changed(state, oss_files) else None

    def _with_prompt_context(self, request: ModelRequest) -> ModelRequest:
        context = request.runtime.context
        conversation_id = context.conversation_id if isinstance(context, AgentRuntimeContext) else None
        if not conversation_id:
            return request

        system_message = _append_to_system_message(
            request.system_message,
            WORKSPACE_PROMPT.format(
                current_time=_current_time_context(),
                workspace=conversation_workspace(conversation_id),
                home=_current_home_context(),
                cluster_context=_current_cluster_context(),
            ),
        )
        denial_context = protected_denial_context()
        if denial_context:
            system_message = _append_to_system_message(system_message, denial_context)
        return request.override(system_message=system_message)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(self._with_prompt_context(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._with_prompt_context(request))

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._uploaded_files_state_update(state, runtime)

    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._uploaded_files_state_update(state, runtime)


__all__ = ["OSS_INPUT_TYPES", "PromptContextMiddleware", "PromptContextState"]
