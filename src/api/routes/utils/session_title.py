from __future__ import annotations

import asyncio
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.agent import load_agent_config
from src.api.agent_report import report_enabled
from src.llm import build_once_chat_openai
from src.logger import get_logger

logger = get_logger(__name__)
SESSION_METADATA_MODEL_TIMEOUT_SECONDS = 30
_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_PUNCTUATION_PATTERN = re.compile(r"[`'\".,!?;:，。！？；：《》、（）()\[\]{}<>【】“”‘’…⋯\-_—/\\|]+")


def _clean_title(value: str) -> str:
    title = _THINK_PATTERN.sub("", value).strip()
    title = _PUNCTUATION_PATTERN.sub("", title)
    title = " ".join(title.split())
    return title[:15]


def _fallback_title_from_user(user: str) -> str | None:
    title = _THINK_PATTERN.sub("", user).strip()
    title = _PUNCTUATION_PATTERN.sub("", title)
    title = "".join(title.split())
    return title[:10] or None


def _title_messages(user: str, agent_description: str) -> list[SystemMessage | HumanMessage]:
    identity = agent_description.strip() or "通用智能体"
    return [
        SystemMessage(
            content=(
                "你是会话标题生成助手。\n"
                f"当前智能体身份说明：{identity}\n"
                "请基于用户的首条输入，生成一个合理、具体、便于用户识别的会话标题。\n"
                "只返回标题本身，不要引号、标点、Markdown 或解释。\n"
                "标题必须语义完整，禁止使用省略号或以未完成的语句结尾。\n"
                "如果用户的输入和当前智能体身份无关（例如问候、闲聊、常规文件解析），则标题也不要涵盖智能体身份，用户问题是第一位的\n"
                "尽量使用中文，标题不超过 15 个汉字。"
            )
        ),
        HumanMessage(content=user),
    ]


async def _generate_title_with_config(
    llm_config: dict[str, Any] | None,
    messages: list[SystemMessage | HumanMessage],
    *,
    model_label: str,
) -> str | None:
    llm = build_once_chat_openai(llm_config)
    try:
        response = await asyncio.wait_for(
            llm.ainvoke(messages),
            timeout=SESSION_METADATA_MODEL_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("Failed to generate session title with model=%s", model_label)
        return None

    title = _clean_title(_message_text(response.content))
    return title or None


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


async def generate_session_title(user: str) -> str | None:
    if not user.strip():
        return None

    if report_enabled():
        return _fallback_title_from_user(user)

    config = load_agent_config()
    llm_config = config.get("llm", {})
    agent_description = config.get("description")
    messages = _title_messages(user, agent_description if isinstance(agent_description, str) else "")
    primary_config = llm_config if isinstance(llm_config, dict) else None

    title = await _generate_title_with_config(primary_config, messages, model_label="primary")
    return title or _fallback_title_from_user(user)


__all__ = ["generate_session_title"]
