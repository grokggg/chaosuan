from __future__ import annotations

import os
from datetime import datetime
from typing import Annotated, Any

import requests
from langchain.tools import tool

WEB_SEARCH_TIMEOUT_SECONDS = 15
WEB_SEARCH_DEFAULT_COUNT = 3
WEB_SEARCH_MAX_COUNT = 5
WEB_SEARCH_DEFAULT_FRESHNESS = "noLimit"


def _safe_text(value: Any, *, limit: int = 500) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}...(truncated)"


def _normalize_count(count: int | None) -> int:
    try:
        value = int(count if count is not None else WEB_SEARCH_DEFAULT_COUNT)
    except (TypeError, ValueError):
        value = WEB_SEARCH_DEFAULT_COUNT
    return max(1, min(value, WEB_SEARCH_MAX_COUNT))


@tool(
    "web_search",
    description=(
        "通过代理网络搜索服务检索互联网信息，尤其适用于新闻和时效性内容。查询语句的语言必须与用户输入语言一致，"
        "默认优先使用简体中文"
    ),
)
def web_search(
    query: Annotated[
        str,
        (
            "聚焦且自然的搜索查询语句。查询语言必须与用户输入语言一致，默认优先使用简体中文；"
        ),
    ],
    count: Annotated[
        int,
        ("返回的网络搜索结果数量，取值范围为 1 到 5。"),
    ] = WEB_SEARCH_DEFAULT_COUNT,
    freshness: Annotated[
        str,
        (
            "可选的搜索时间范围，推荐使用 noLimit。允许值包括 noLimit、oneDay、oneWeek、oneMonth、"
            "oneYear、YYYY-MM-DD..YYYY-MM-DD 或 YYYY-MM-DD。如果指定时间范围内没有相关页面，可能返回空结果。"
        ),
    ] = WEB_SEARCH_DEFAULT_FRESHNESS,
) -> str:
    """使用与用户输入语言一致的查询语句检索互联网信息。"""
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return "Web search skipped: query is empty."

    proxy_url = os.getenv("PROXY_URL", "").strip().rstrip("/")
    proxy_api_key = os.getenv("PROXY_API_KEY", "").strip()
    if not proxy_url:
        return "Web search failed: PROXY_URL is not configured."
    if not proxy_api_key:
        return "Web search failed: PROXY_API_KEY is not configured."

    safe_count = _normalize_count(count)
    safe_freshness = str(freshness or WEB_SEARCH_DEFAULT_FRESHNESS).strip() or WEB_SEARCH_DEFAULT_FRESHNESS
    try:
        response = requests.post(
            f"{proxy_url}/api/v1/web-search",
            json={
                "query": normalized_query,
                "summary": True,
                "count": safe_count,
                "page": 1,
                "freshness": safe_freshness,
            },
            headers={
                "Authorization": f"Bearer {proxy_api_key}",
                "Content-Type": "application/json",
            },
            timeout=WEB_SEARCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return f"Web search failed: query={normalized_query} error={exc}"

    if not isinstance(payload, dict) or payload.get("code") not in {200, "200"}:
        return f"Web search returned no valid result: query={normalized_query}"

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    web_pages = data.get("webPages")
    if isinstance(web_pages, dict):
        pages = web_pages.get("value") if isinstance(web_pages.get("value"), list) else []
    elif isinstance(web_pages, list):
        pages = web_pages
    else:
        pages = []

    summaries = []
    for index, page in enumerate(pages[:safe_count], 1):
        if not isinstance(page, dict):
            continue
        summary = _safe_text(page.get("summary"), limit=512)
        if summary:
            url = _safe_text(page.get("url"), limit=500)
            source = f"\n   Source: {url}" if url else ""
            summaries.append(f"{index}. {summary}{source}")

    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
    lines = [
        f"Web search query: {normalized_query}",
        f"Freshness: {safe_freshness}",
        f"Current time: {current_date}",
        "",
        "Web search summaries:",
        *summaries,
    ]
    if not summaries:
        lines.append("No usable web summaries were returned.")

    return "\n".join(lines)


__all__ = ["web_search"]
