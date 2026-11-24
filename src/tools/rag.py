from __future__ import annotations

import json
import os
import time
from typing import Annotated, Any

import requests
from langchain.tools import ToolRuntime, tool

from src.agents.context import AgentRuntimeContext
from src.logger import get_logger
from src.utils import AGENT_CONFIG_PATH, load_agent_config

logger = get_logger(__name__)

DEFAULT_TOP_N = 5
DEFAULT_SIMILARITY_THRESHOLD = 0.3
DEFAULT_VECTOR_SIMILARITY_WEIGHT = 0.7
DEFAULT_CROSS_LANGUAGES = ["English", "Chinese"]
REQUEST_TIMEOUT_SECONDS = 15
RAGFLOW_GATEWAY_PREFIX = "/ske/ragflow"
RAGFLOW_RETRIEVAL_PATH = "/api/v1/retrieval"
BASE_TOOL_DESCRIPTION = """Retrieve relevant content snippets from configured knowledge bases.
When the user input is related to any configured knowledge base, use this tool first to obtain supporting information before answering.
Note: if there is a knowledge base related to the user's question, you should try to call this tool to retrieve relevant knowledge as supporting context, even if you believe internal knowledge may be enough to answer.

Input parameters:
- question: Required. Retrieval query. Before calling the tool, rewrite the user's request into a concise sentence suitable for search. Prefer keywords and explicit domain terms, and remove punctuation, conversational filler, and tone words where possible.
- dataset_id: Required. Select one or more available knowledge base ids from the available knowledge base list below. Do not fabricate ids.
"""


def _get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_rag_base_url() -> str:
    return f"{_get_required_env('RAG_HOST').rstrip('/')}{RAGFLOW_GATEWAY_PREFIX}"


def _get_rag_retrieval_url() -> str:
    return _get_rag_base_url() + RAGFLOW_RETRIEVAL_PATH


def _load_agent_config() -> dict[str, Any]:
    try:
        return load_agent_config()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load agent config from %s: %s", AGENT_CONFIG_PATH, exc)
        return {}


def _load_datasets() -> list[dict[str, Any]]:
    agent_config = _load_agent_config()
    datasets = agent_config.get("dataset", [])
    if not isinstance(datasets, list):
        return []

    return [dataset for dataset in datasets if isinstance(dataset, dict)]


def _format_dataset_for_description(dataset: dict[str, Any]) -> str | None:
    name_cn = str(dataset.get("nameCn", "")).strip()
    name_en = str(dataset.get("nameEn", "")).strip()
    ids = dataset.get("dataset_id", dataset.get("dataset_ids"))
    desc = str(dataset.get("desc", "")).strip()

    if isinstance(ids, list):
        normalized_ids = [str(item).strip() for item in ids if str(item).strip()]
        ids_text = ", ".join(normalized_ids)
    else:
        ids_text = str(ids or "").strip()

    if not ids_text:
        return None

    label = name_cn or name_en or "unnamed"
    if desc:
        return f"- {label}: dataset_id={ids_text}; desc={desc}"
    return f"- {label}: dataset_id={ids_text}"


def _build_tool_description() -> str:
    datasets = _load_datasets()
    dataset_lines = [line for dataset in datasets if (line := _format_dataset_for_description(dataset)) is not None]
    if not dataset_lines:
        return BASE_TOOL_DESCRIPTION + ("\nAvailable knowledge bases:\n- No configured knowledge bases found.")
    return BASE_TOOL_DESCRIPTION + ("\nAvailable knowledge bases:\n") + "\n".join(dataset_lines)


def _normalize_ids(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def _configured_dataset_ids() -> list[str]:
    dataset_ids: list[str] = []
    for dataset in _load_datasets():
        dataset_ids.extend(_normalize_ids(dataset.get("dataset_id", dataset.get("dataset_ids"))))
    return dataset_ids


def resolve_ragflow_skill_config(dataset_id: list[str] | str | None = None) -> dict[str, str]:
    resolved_dataset_ids = _normalize_ids(dataset_id) or _configured_dataset_ids()
    if not resolved_dataset_ids:
        raise RuntimeError("Missing required RAGFlow dataset id in agent.json dataset configuration")
    return {
        "ragflow_base_url": _get_rag_base_url(),
        "api_key": _get_required_env("RAG_AUTH"),
        "dataset_id": resolved_dataset_ids[0],
    }


def _build_contexts(chunks: list[dict[str, Any]], *, top_n: int) -> list[dict[str, str]]:
    contexts: list[dict[str, str]] = []
    for chunk in chunks[:top_n]:
        contexts.append(
            {
                "content": str(chunk.get("content", "")),
                "document_name": str(chunk.get("document_keyword", "")),
                "create_user": str(chunk.get("create_user", "")),
                "name_en": str(chunk.get("name_en", "")),
                "document_id": str(chunk.get("document_id", "")),
                "file_url": str(chunk.get("file_url", "")),
            }
        )
    return contexts


def _get_runtime_user_id(runtime: ToolRuntime[AgentRuntimeContext, Any] | None) -> str | None:
    if runtime is None:
        return None

    context = runtime.context
    if isinstance(context, AgentRuntimeContext):
        return context.user_id
    if isinstance(context, dict):
        user_id = context.get("user_id")
        return str(user_id) if user_id is not None else None
    return getattr(context, "user_id", None)


@tool("retrieve_knowledge_base", description=_build_tool_description())
def retrieve_knowledge_base(
    question: Annotated[
        str,
        ("Required retrieval query. Rewrite the user's request into a concise sentence suitable for search."),
    ],
    dataset_id: Annotated[
        list[str] | str,
        (
            "Required in actual use. Select available knowledge base ids from the available knowledge base list in the tool description."
        ),
    ],
    runtime: ToolRuntime[AgentRuntimeContext, Any] = None,
) -> list[dict[str, str]]:
    """从社区知识库中检索相关内容片段。"""
    access_token = _get_required_env("RAG_AUTH")
    retrieval_url = _get_rag_retrieval_url()
    top_n = DEFAULT_TOP_N
    similarity_threshold = DEFAULT_SIMILARITY_THRESHOLD
    vector_similarity_weight = DEFAULT_VECTOR_SIMILARITY_WEIGHT
    normalized_dataset_ids = _normalize_ids(dataset_id) or _configured_dataset_ids()
    if not normalized_dataset_ids:
        raise RuntimeError("Missing required knowledge-base dataset id in agent.json dataset configuration")
    normalized_top_n = max(1, int(top_n))
    user_id = _get_runtime_user_id(runtime)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": f"Bearer {access_token}",
    }
    payload = {
        "user_id": user_id,
        "similarity_threshold": similarity_threshold,
        "vector_similarity_weight": vector_similarity_weight,
        "use_kg": False,
        "question": question,
        "dataset_ids": normalized_dataset_ids,
        "knowledge_ids": normalized_dataset_ids,
        "page": 1,
        "page_size": normalized_top_n,
        "cross_languages": DEFAULT_CROSS_LANGUAGES,
    }

    def _do_request() -> list[dict[str, str]]:
        logger.info(
            "Retrieving community knowledge base url=%s question=%r dataset_ids=%s top_n=%s",
            retrieval_url,
            question,
            normalized_dataset_ids,
            normalized_top_n,
        )
        response = requests.post(retrieval_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        response_data = response.json()
        if isinstance(response_data, dict) and response_data.get("code") not in (None, 0):
            logger.warning("RAG retrieval returned error response=%s", response_data)
            return []
        chunks = response_data.get("data", {}).get("chunks", [])
        if not isinstance(chunks, list):
            logger.warning("Unexpected RAG response chunks type=%s", type(chunks).__name__)
            return []
        return _build_contexts(chunks, top_n=normalized_top_n)

    try:
        return _do_request()
    except Exception as exc:
        logger.warning("Community knowledge base retrieval failed, retrying once: %s", exc)
        try:
            time.sleep(1)
            return _do_request()
        except Exception as retry_exc:
            logger.warning("Community knowledge base retrieval failed after retry: %s", retry_exc)
            return []
