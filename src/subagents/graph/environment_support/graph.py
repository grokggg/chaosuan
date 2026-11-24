from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph

from src.llm import build_once_chat_openai, resolve_model_ref
from src.logger import get_logger
from src.utils import extract_response_usage, load_current_llm_config, log_usage

logger = get_logger(__name__)

ENVIRONMENTS_DIR = Path(__file__).resolve().parent
PROMPT_DIR = ENVIRONMENTS_DIR / "prompt"

Scene = Literal["bioinformatics", "materials_science", "unknown"]

SCENE_LABELS: dict[str, str] = {
    "bioinformatics": "生物信息学",
    "materials_science": "材料科学",
    "unknown": "未知",
}

NON_PRODUCTION_CLUSTER_IDS = frozenset({"200071", "200107", "200108"})

PRODUCTION_DEPENDENCY_FILES: dict[str, Path] = {
    "bioinformatics": PROMPT_DIR / "bioinformatics_dependency_prod.md",
    "materials_science": PROMPT_DIR / "materials_science_dependency_prod.md",
}

NON_PRODUCTION_DEPENDENCY_FILES: dict[str, Path] = {
    "bioinformatics": PROMPT_DIR / "bioinformatics_dependency.md",
    "materials_science": PROMPT_DIR / "materials_science_dependency.md",
}


class EnvironmentSupportState(TypedDict, total=False):
    messages: list[BaseMessage]
    scene: Scene
    loaded_prompt_path: str | None
    result: str


def _current_cluster_id() -> str:
    return os.getenv("CLUSTER_ID", "").strip()


def _dependency_files(cluster_id: str | int | None = None) -> dict[str, Path]:
    resolved_cluster_id = _current_cluster_id() if cluster_id is None else str(cluster_id).strip()
    if resolved_cluster_id in NON_PRODUCTION_CLUSTER_IDS:
        return NON_PRODUCTION_DEPENDENCY_FILES
    return PRODUCTION_DEPENDENCY_FILES


def _read_prompt(filename: str, *, dependency_files: dict[str, Path] | None = None) -> str:
    prompt = (PROMPT_DIR / filename).read_text(encoding="utf-8")
    resolved_dependency_files = dependency_files or _dependency_files()
    prompt_files = {
        "{{BIOINFORMATICS_DEPENDENCY_FILE}}": resolved_dependency_files["bioinformatics"],
        "{{MATERIALS_SCIENCE_DEPENDENCY_FILE}}": resolved_dependency_files["materials_science"],
    }
    for placeholder, dependency_file in prompt_files.items():
        prompt = prompt.replace(placeholder, str(dependency_file.resolve()))
    return prompt


def _message_text(message: BaseMessage) -> str:
    text = getattr(message, "text", None)
    if isinstance(text, str) and text:
        return text
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content)


def _latest_user_text(messages: list[BaseMessage]) -> str:
    if not messages:
        return ""
    return _message_text(messages[-1])


def _parse_scene(raw_content: object) -> Scene:
    raw_text = raw_content if isinstance(raw_content, str) else str(raw_content)
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        lowered = raw_text.strip().lower()
        for scene in ("bioinformatics", "materials_science", "unknown"):
            if scene in lowered:
                return scene
        return "unknown"

    scene = payload.get("scene") if isinstance(payload, dict) else None
    if scene in {"bioinformatics", "materials_science", "unknown"}:
        return scene
    return "unknown"


def _invoke_model(
    messages: list[BaseMessage],
    *,
    node: str,
    **metadata: Any,
) -> tuple[BaseMessage, str, float]:
    llm_config = load_current_llm_config()
    model_label = resolve_model_ref(llm_config)
    started_at = time.perf_counter()
    try:
        response = build_once_chat_openai(llm_config).invoke(messages)
        return response, model_label, time.perf_counter() - started_at
    except Exception as exc:
        logger.warning(
            "Environment support LLM call failed node=%s model=%s error=%s metadata=%s",
            node,
            model_label,
            exc,
            metadata,
            exc_info=True,
        )
        raise RuntimeError(
            f"Environment support LLM call failed model={model_label}: "
            f"{str(exc).strip() or exc.__class__.__name__}"
        ) from exc


def classify_scene(state: EnvironmentSupportState) -> EnvironmentSupportState:
    messages = state.get("messages", [])
    task_text = _latest_user_text(messages)
    logger.info(
        "Environment support classify_scene start message_count=%s task_chars=%s",
        len(messages),
        len(task_text),
    )
    response, model_label, elapsed_seconds = _invoke_model(
        [
            SystemMessage(content=_read_prompt("classify_scene.md")),
            HumanMessage(content=task_text),
        ],
        node="classify_scene",
        task_chars=len(task_text),
    )
    scene = _parse_scene(response.content)
    log_usage(
        logger,
        "Environment support LLM usage",
        extract_response_usage(response),
        elapsed_seconds=elapsed_seconds,
        node="classify_scene",
        model=model_label,
    )
    logger.info("Environment support classified scene=%s model=%s", scene, model_label)
    return {"scene": scene}


def _unsupported_result(scene: Scene, task_text: str) -> str:
    label = SCENE_LABELS.get(scene, scene)
    return (
        "## 环境支持判断\n\n"
        f"领域: {label} / {scene}\n"
        "依赖说明: 未配置\n"
        "总体结论: unknown\n\n"
        "## 支持的软件与路径\n\n"
        "| 工作流步骤 | 依赖项 | 判断 | 环境记录 | 路径 | 说明 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"| 当前输入 | {task_text[:120] or '未提供明确依赖'} | unknown | 未配置对应领域依赖说明 | - | 无法基于环境说明判断 |\n\n"
        "## 缺口与风险\n\n"
        "- 当前领域未配置依赖说明，或输入信息不足，无法确认 /public/software 是否支持。\n\n"
        "## 可执行建议\n\n"
        "- 补充该领域的环境依赖说明，或提供更明确的软件、包、数据库和版本信息后重新判断。"
    )


def answer_with_loaded_prompt(state: EnvironmentSupportState) -> EnvironmentSupportState:
    messages = state.get("messages", [])
    task_text = _latest_user_text(messages)
    scene = state.get("scene", "unknown")
    cluster_id = _current_cluster_id()
    dependency_files = _dependency_files(cluster_id)
    dependency_file = dependency_files.get(scene)
    logger.info(
        "Environment support answer_with_loaded_prompt start scene=%s cluster_id=%s "
        "message_count=%s task_chars=%s",
        scene,
        cluster_id or "<default>",
        len(messages),
        len(task_text),
    )

    if dependency_file is None:
        result = _unsupported_result(scene, task_text)
        logger.info("Environment support dependency unavailable scene=%s", scene)
        return {
            "loaded_prompt_path": None,
            "result": result,
            "messages": [*messages, AIMessage(content=result)],
        }

    dependency_text = dependency_file.read_text(encoding="utf-8")
    response, model_label, elapsed_seconds = _invoke_model(
        [
            SystemMessage(content=_read_prompt("environment_support.md", dependency_files=dependency_files)),
            HumanMessage(
                content=(
                    f"当前领域: {SCENE_LABELS.get(scene, scene)} / {scene}\n"
                    f"依赖说明文件: {dependency_file.resolve()}\n\n"
                    f"用户任务或工作流:\n{task_text}\n\n"
                    f"依赖说明内容:\n{dependency_text}"
                )
            ),
        ],
        node="answer_with_loaded_prompt",
        scene=scene,
        cluster_id=cluster_id,
        dependency_file=str(dependency_file),
    )
    log_usage(
        logger,
        "Environment support LLM usage",
        extract_response_usage(response),
        elapsed_seconds=elapsed_seconds,
        node="answer_with_loaded_prompt",
        model=model_label,
        scene=scene,
        cluster_id=cluster_id,
        dependency_file=str(dependency_file),
    )
    result = _message_text(response).rstrip()
    logger.info(
        "Environment support answered scene=%s dependency_file=%s result_chars=%s",
        scene,
        dependency_file,
        len(result),
    )
    return {
        "loaded_prompt_path": str(dependency_file.resolve()),
        "result": result,
        "messages": [*messages, AIMessage(content=result)],
    }


def build_environment_support_graph() -> Runnable:
    graph = StateGraph(EnvironmentSupportState)
    graph.add_node("classify_scene", classify_scene)
    graph.add_node("answer_with_loaded_prompt", answer_with_loaded_prompt)
    graph.add_edge(START, "classify_scene")
    graph.add_edge("classify_scene", "answer_with_loaded_prompt")
    graph.add_edge("answer_with_loaded_prompt", END)
    return graph.compile()


__all__ = ["build_environment_support_graph"]
