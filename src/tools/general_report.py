"""Metadata helper for non-scientific computation reports."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Any

from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import build_once_chat_openai
from src.logger import get_logger
from src.utils import load_agent_config, load_current_llm_config

logger = get_logger(__name__)

DEFAULT_REPORT_AUTHOR = "SCNet 智能体"


AUTHOR_SYSTEM_PROMPT = """你是报告作者名称规范化助手。

请判断候选报告作者名中是否已经包含"超算互联网"或"SCNet"标识。
如果已经包含，返回原作者名，不要改写。
如果不包含，在前面补充"SCNet "，并返回补充后的实际作者名。例如RNA差异分析助手 -> SCNet RNA差异分析助手

只返回最终实际使用的作者名，不要解释，不要添加引号、Markdown 或多余标点。
"""


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(part for part in parts if part)
    return str(content)


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:markdown|md)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else stripped


def _report_author_from_agent_config() -> str:
    try:
        config = load_agent_config()
    except Exception as exc:
        logger.warning("Failed to load agent config for general report author: %s", exc)
        return DEFAULT_REPORT_AUTHOR

    name = config.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else DEFAULT_REPORT_AUTHOR


def _ensure_scnet_report_author(author: str) -> str:
    normalized = author.strip() or DEFAULT_REPORT_AUTHOR
    if "超算互联网" in normalized or "scnet" in normalized.lower():
        return normalized
    return f"SCNet {normalized}"


async def _resolve_report_author() -> str:
    candidate_author = _report_author_from_agent_config()
    user_prompt = (
        "候选报告作者名：\n"
        f"{candidate_author}\n\n"
        "请按规则返回最终实际使用的作者名。"
    )
    try:
        llm = build_once_chat_openai(load_current_llm_config())
        response = await llm.ainvoke(
            [
                SystemMessage(content=AUTHOR_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )
        report_author = _strip_markdown_fence(_message_content_to_text(response.content)).strip()
        return _ensure_scnet_report_author(report_author)
    except Exception as exc:
        logger.warning("Failed to normalize general report author with model: %s", exc, exc_info=True)
        return _ensure_scnet_report_author(candidate_author)


def _is_absolute_path(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def _normalize_report_image_paths(report_image_paths: list[str]) -> list[str]:
    normalized_paths = [str(path).strip() for path in report_image_paths]
    empty_indexes = [index for index, path in enumerate(normalized_paths) if not path]
    if empty_indexes:
        logger.warning("Ignoring empty report image paths at indexes: %s", empty_indexes)

    relative_paths = [path for path in normalized_paths if path and not _is_absolute_path(path)]
    if relative_paths:
        logger.warning(
            "Ignoring relative report image paths or filenames; absolute full paths are required: %s",
            relative_paths,
        )
    return [path for path in normalized_paths if path and _is_absolute_path(path)]


@tool(
    "get_general_report_metadata",
    description=(
        "生成非科学计算报告前必须调用。调用时先汇总报告正文计划展示的全部图片，并通过 "
        "report_image_paths 传入每张图片的绝对完整路径；禁止传入相对路径或仅图片文件名，报告不展示图片时传空列表。"
        "空路径、相对路径或仅文件名会被记录到日志并从返回结果中忽略。"
        "工具返回 report_author、report_date 和 report_image_paths。作者与日期应直接用于报告标题下方；"
        "报告中的图片引用必须从返回的 report_image_paths 中选择并原样使用，不得缩短或改写路径。"
    ),
)
async def get_general_report_metadata(
    report_image_paths: Annotated[
        list[str],
        (
            "Absolute full paths of every image that will be displayed in the report. "
            "Relative paths, bare filenames, and empty entries are logged and omitted from the result. "
            "Pass an empty list when the report has no images."
        ),
    ],
) -> dict[str, str | list[str]]:
    """Return report metadata and echo the validated absolute report image paths."""

    normalized_image_paths = _normalize_report_image_paths(report_image_paths)
    return {
        "report_author": await _resolve_report_author(),
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "report_image_paths": normalized_image_paths,
    }


__all__ = ["get_general_report_metadata"]
