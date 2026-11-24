from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from src.agents.agent import _build_guarded_shell_backend
from src.agents.context import AgentRuntimeContext
from src.agents.manager import AGENTS
from src.api.agent_report import report_enabled
from src.api.request_monitor import finish_active_request, track_active_request
from src.api.routes.model import (
    PrivateResourcesUpdateRequest,
    UserAgentRestartRequest,
    UserChatCacheRequest,
    UserChatRequest,
    UserStopRequest,
)
from src.api.routes.utils.chat_errors import stream_error_text
from src.api.routes.utils.chat_inputs import (
    dump_request_inputs,
    load_request_context,
    request_message_payloads,
    request_resource_card_selections,
    request_user_text,
    resolved_request_user_id,
)
from src.api.routes.utils.chat_stream import resolve_configured_model_name, sse_message
from src.api.routes.utils.chat_stream_processor import ChatStreamProcessor
from src.api.routes.utils.restart import apply_private_resources_config, apply_restart_config
from src.api.routes.utils.session_title import generate_session_title
from src.api.routes.utils.sse_heartbeat import stream_with_heartbeat
from src.api.routes.utils.stream_part_ids import clear_stream_part_ids, next_stream_part_id
from src.api.routes.utils.stream_recovery import (
    discard_recovery_events,
    drain_recovery_events,
    enqueue_recovery_events,
)
from src.api.session_store import (
    append_session_message,
    append_session_message_with_handoff,
    delete_session,
    ensure_conversation_workspace,
    list_sessions,
    mark_next_user_message_hidden,
    normalize_message_time,
    read_session,
    session_needs_title,
    update_resource_card_interaction_selection,
    update_session_status,
    update_session_title,
)
from src.api.stop_tokens import clear_graph_stop, request_graph_stop
from src.backend.shell_approval_intent import (
    GraphApprovalDecision,
    answer_pending_approval_question,
    handle_natural_approval_reply,
)
from src.backend.shell_approvals import (
    CURRENT_APPROVAL_SCOPE,
    GRAPH_APPROVAL_MODE,
    GRAPH_APPROVAL_RESUME,
    GraphApprovalResume,
    create_scope,
)
from src.logger import get_logger, log_context
from src.memory.sse_cache import (
    append_sse_cache_event,
    begin_sse_cache,
    close_sse_cache,
    get_sse_cache_message_id,
    has_sse_cache,
    is_sse_cache_active,
    stream_sse_cache,
)
from src.statistics import empty_resource_statistics, get_resource_statistics
from src.utils import load_agent_config, load_current_llm_config, validate_user_id
from src.utils.conversation_progress import (
    CONVERSATION_STATUS_CANCELLED,
    CONVERSATION_STATUS_IN_PROGRESS,
)
from src.utils.retry_progress import RetryProgressResult, iter_with_retry_progress

router = APIRouter(prefix="/user/agent", tags=["user-agent"])
logger = get_logger(__name__)


_ACTIVE_STREAM_TASKS: dict[str, asyncio.Task[Any]] = {}
_STOP_REQUESTED_CONVERSATIONS: set[str] = set()
SESSION_STORAGE_WRITE_ERROR_TEXT = "会话存储不可写，当前存储错误"


# ── 演示用错误码触发器 ──────────────────────────────────────
# 用户消息以 #demo-xxx# 开头时，直接返回对应错误码，不调用 LLM
_DEMO_ERROR_TRIGGERS: dict[str, dict[str, str]] = {
    "#demo-mcp-timeout#": {
        "code": "MCP_TIMEOUT",
        "message": "MCP 服务调用失败，任务执行中断，请稍后重试。",
    },
    "#demo-mcp-connect#": {
        "code": "MCP_CONNECT_FAILED",
        "message": "MCP 服务调用失败，任务执行中断，请稍后重试。",
    },
    "#demo-model-auth#": {
        "code": "MODEL_AUTH_FAILED",
        "message": "模型服务无法调用，任务执行中断，请前往模型设置检查。",
    },
    "#demo-session-overflow#": {
        "code": "CHECKPOINT_STORAGE_ERROR",
        "message": "会话历史过长，当前对话已无法继续，请创建新对话。",
    },
    "#demo-stream-error#": {
        "code": "STREAM_EVENT_LOOP_DIED",
        "message": "服务内部异常，任务执行中断，请刷新页面重试。",
    },
    "#demo-skill-fail#": {
        "code": "SKILL_INSTALL_FAILED",
        "message": "技能下载失败，已保留原有技能，请检查仓库地址和权限。",
    },
    "#demo-system-error#": {
        "code": "SYSTEM_INTERNAL_ERROR",
        "message": "服务出现异常，任务执行中断，请稍后重试。",
    },
}


def _check_demo_error_trigger(request: UserChatRequest) -> dict[str, str] | None:
    user_text = request_user_text(request).strip()
    for prefix, error_info in _DEMO_ERROR_TRIGGERS.items():
        if user_text.startswith(prefix):
            return error_info
    return None
# ── 演示触发器结束 ────────────────────────────────────────


_SSE_LOG_TYPES = frozenset({"preview", "interaction"})


def _log_sse_payload(payload: dict[str, Any]) -> None:
    """Log card-bearing SSE events so card field loss can be traced end to end."""
    try:
        event_type = str(payload.get("type") or "")
        if event_type not in _SSE_LOG_TYPES:
            return
        resource = payload.get("resource")
        resource_keys = sorted(resource.keys()) if isinstance(resource, dict) else None
        logger.info(
            "SSE_CARD_EVENT type=%s id=%s resource_type=%s resource_keys=%s",
            event_type,
            payload.get("id"),
            resource.get("type") if isinstance(resource, dict) else None,
            resource_keys,
        )
        if str(os.getenv("SSE_DEBUG_DUMP") or "").strip() in {"1", "true", "yes"}:
            logger.info("SSE_CARD_FRAME %s", json.dumps(payload, ensure_ascii=False)[:8000])
    except Exception:
        logger.exception("Failed to log SSE card payload")


def _sse_json(
    payload: dict[str, Any],
    conversation_id: str,
    message_id: str | None = None,
) -> str:
    # Only the outer request's terminal event ends execution. Model-level
    # finish_reason values (including tool_calls) are not request completion.
    if payload.get("type") == "finish" and payload.get("finishReason") is not None:
        finish_active_request()
    payload = {**payload, "conversationId": conversation_id}
    if message_id is not None:
        payload["messageId"] = message_id
    _log_sse_payload(payload)
    return sse_message(json.dumps(payload, ensure_ascii=False))


def _new_stream_message_id() -> str:
    return f"{uuid4().int % 10**16:016d}"


def _without_statistics_messages(session: dict[str, Any]) -> dict[str, Any]:
    messages = session.get("messages")
    if not isinstance(messages, list):
        return session
    visible_messages = [
        message
        for message in messages
        if not isinstance(message, dict) or message.get("type") != "statistics"
    ]
    if len(visible_messages) == len(messages):
        return session
    visible_session = dict(session)
    visible_session["messages"] = visible_messages
    return visible_session


async def _consume_statistics_event(
    *,
    user_id: str,
    conversation_id: str,
    runtime_context: AgentRuntimeContext | None,
) -> dict[str, Any]:
    part_id = await next_stream_part_id(user_id, conversation_id, "statistics")
    tracker = get_resource_statistics(runtime_context) if runtime_context is not None else None
    statistics = tracker.consume_statistics() if tracker is not None else empty_resource_statistics()
    event = {
        "type": "statistics",
        "id": part_id,
        "statistics": statistics,
    }
    try:
        append_session_message(
            user_id,
            conversation_id,
            {"role": "assistant", **event},
        )
    except Exception:
        logger.exception("Failed to persist resource statistics event")
    return {
        **event,
        "statistics": [{"resources": statistics}],
    }


def _record_job_statistics(
    runtime_context: AgentRuntimeContext | None,
    event: dict[str, Any],
) -> None:
    if event.get("type") != "job-monitor":
        return
    tracker = get_resource_statistics(runtime_context) if runtime_context is not None else None
    if tracker is None:
        return
    try:
        tracker.record_job(
            job_id=str(event.get("jobId") or ""),
            cluster_id=str(event.get("clusterId") or ""),
        )
    except Exception:
        logger.exception(
            "Failed to record job resource statistics cluster_id=%s job_id=%s",
            event.get("clusterId"),
            event.get("jobId"),
        )


def _queue_interruption_recovery(
    processor: ChatStreamProcessor,
    conversation_id: str,
    message_id: str,
) -> None:
    enqueue_recovery_events(
        conversation_id,
        message_id,
        processor.finalize_interruption(),
    )


def _state_values(state: Any) -> dict[str, Any]:
    values = getattr(state, "values", None)
    if isinstance(values, dict):
        return values
    if isinstance(state, dict):
        raw_values = state.get("values", state)
        if isinstance(raw_values, dict):
            return raw_values
    return {}


async def _agent_astream(
    *,
    agent: Any,
    input_data: Any,
    config: dict[str, Any],
    runtime_context: AgentRuntimeContext,
) -> Any:
    async for part in agent.astream(
        input_data,
        config=config,
        context=runtime_context,
        stream_mode=["messages", "custom"],
        version="v2",
    ):
        yield part


async def _log_summarization_checkpoint(
    *,
    agent: Any,
    config: dict[str, Any],
    conversation_id: str,
    filtered_chunks: int,
) -> None:
    if filtered_chunks <= 0:
        return

    try:
        get_state = getattr(agent, "aget_state", None)
        if get_state is None:
            logger.warning(
                "Internal summarization stream chunks filtered conversation_id=%s chunks=%s checkpoint_state=unavailable",
                conversation_id,
                filtered_chunks,
            )
            return

        state = await get_state(config)
        event = _state_values(state).get("_summarization_event")
    except Exception:
        logger.exception(
            "Failed to inspect summarization checkpoint conversation_id=%s chunks=%s",
            conversation_id,
            filtered_chunks,
        )
        return

    if not isinstance(event, dict):
        logger.warning(
            "Internal summarization stream chunks filtered but _summarization_event is not visible in checkpoint "
            "conversation_id=%s chunks=%s",
            conversation_id,
            filtered_chunks,
        )
        return

    logger.info(
        "Internal summarization checkpoint visible conversation_id=%s chunks=%s cutoff_index=%s file_path=%s",
        conversation_id,
        filtered_chunks,
        event.get("cutoff_index"),
        event.get("file_path"),
    )


def _request_stream_stop(conversation_id: str) -> None:
    _STOP_REQUESTED_CONVERSATIONS.add(conversation_id)


def _clear_stream_stop(conversation_id: str) -> None:
    _STOP_REQUESTED_CONVERSATIONS.discard(conversation_id)


def _is_stream_stop_requested(conversation_id: str) -> bool:
    return conversation_id in _STOP_REQUESTED_CONVERSATIONS


def _is_conversation_stream_active(conversation_id: str) -> bool:
    return conversation_id in _ACTIVE_STREAM_TASKS or is_sse_cache_active(conversation_id)


def _hide_active_assistant_tail(session: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    if not _is_conversation_stream_active(conversation_id):
        return session

    messages = session.get("messages")
    if not isinstance(messages, list):
        return session

    last_user_index: int | None = None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, dict) and message.get("role") == "user":
            last_user_index = index
            break

    if last_user_index is None or last_user_index == len(messages) - 1:
        return session

    visible_session = dict(session)
    visible_session["messages"] = messages[: last_user_index + 1]
    return visible_session


async def _chat_sse_source(
    request: UserChatRequest,
    http_request: Request | None,
    message_id: str,
) -> Any:
    conversation_id = request.conversation_id
    with log_context(conversation_id=conversation_id), track_active_request(enabled=report_enabled()):
        logger.info("Starting chat stream inputs=%s", len(request.inputs))
        current_task = asyncio.current_task()
        if current_task is not None:
            _ACTIVE_STREAM_TASKS[conversation_id] = current_task

        shell_scope_token = None
        approval_recovery: tuple[str, str] | None = None
        processor: ChatStreamProcessor | None = None
        agent: Any = None
        config: dict[str, Any] | None = None
        runtime_context: AgentRuntimeContext | None = None
        user_id: str | None = None
        job_terminal_notice: dict[str, Any] | None = None
        statistics_sent = False
        request_time = normalize_message_time(request.time)
        stream_started = False

        async def consume_statistics_sse() -> str | None:
            nonlocal statistics_sent
            if statistics_sent:
                return None
            statistics_user_id = user_id or validate_user_id(resolved_request_user_id(request))
            event = await _consume_statistics_event(
                user_id=statistics_user_id,
                conversation_id=conversation_id,
                runtime_context=runtime_context,
            )
            statistics_sent = True
            return _sse_json(event, conversation_id, message_id)

        try:
            runtime_context = AgentRuntimeContext.from_environment(conversation_id=conversation_id)
            load_request_context(runtime_context, request)
            user_id = validate_user_id(str(runtime_context.user_id or ""))
            shell_scope = create_scope(user_id, conversation_id)
            shell_scope_token = CURRENT_APPROVAL_SCOPE.set(shell_scope)
            ensure_conversation_workspace(conversation_id)
            config = {"configurable": {"thread_id": f"{user_id}:{conversation_id}"}}
            input_data: dict[str, Any] = {"messages": request_message_payloads(request)}
            user = request_user_text(request)
            should_generate_title = session_needs_title(user_id, conversation_id)
            generated_title: str | None = None
            _, disabled_handoff = append_session_message_with_handoff(
                user_id,
                conversation_id,
                {
                    "role": "user",
                    "time": request_time,
                    "inputs": dump_request_inputs(request),
                },
            )
            if disabled_handoff is not None and disabled_handoff.get("type") == "job-monitor":
                cluster_id = str(disabled_handoff.get("clusterId") or "").strip()
                job_id = str(disabled_handoff.get("jobId") or "").strip()
                if cluster_id and job_id:
                    job_terminal_notice = {
                        "type": "job-terminal-notice",
                        "id": await next_stream_part_id(user_id, conversation_id, "job_terminal_notice"),
                        "clusterId": cluster_id,
                        "jobId": job_id,
                        "conversationId": conversation_id,
                    }
                    append_session_message(
                        user_id,
                        conversation_id,
                        {"role": "assistant", **job_terminal_notice},
                    )
                else:
                    logger.warning(
                        "Disabled job monitor is missing identifiers cluster_id=%s job_id=%s",
                        cluster_id,
                        job_id,
                    )

            if should_generate_title:
                generated_title = await generate_session_title(user)
                if generated_title:
                    update_session_title(user_id, conversation_id, generated_title)

            if _is_stream_stop_requested(conversation_id):
                logger.info("Chat stream stop requested before streaming started")
                stream_started = True
                yield _sse_json(
                    {"type": "start", "time": request_time},
                    conversation_id,
                    message_id,
                )
                if job_terminal_notice is not None:
                    yield _sse_json(job_terminal_notice, conversation_id, message_id)
                statistics_sse = await consume_statistics_sse()
                if statistics_sse is not None:
                    yield statistics_sse
                yield _sse_json(
                    {"type": "finish", "finishReason": "cancelled"},
                    conversation_id,
                    message_id,
                )
                yield sse_message("[DONE]")
                return

            processor = ChatStreamProcessor(
                user_id=user_id,
                conversation_id=conversation_id,
                model_name=resolve_configured_model_name(),
                part_id_factory=next_stream_part_id,
                session_message_writer=append_session_message,
                hide_next_user_message=mark_next_user_message_hidden,
            )
            stream_started = True
            yield _sse_json(
                {"type": "start", "time": request_time},
                conversation_id,
                message_id,
            )
            async for build_item in iter_with_retry_progress(AGENTS.get()):
                if isinstance(build_item, RetryProgressResult):
                    agent = build_item.value
                    continue
                async for retry_event in processor.handle_part(("custom", build_item)):
                    yield _sse_json(retry_event, conversation_id, message_id)
            if agent is None:
                raise RuntimeError("agent build completed without an agent")
            if job_terminal_notice is not None:
                yield _sse_json(job_terminal_notice, conversation_id, message_id)
            for recovery_event in drain_recovery_events(conversation_id):
                yield sse_message(json.dumps(recovery_event, ensure_ascii=False))
            if generated_title:
                title_gen_id = await next_stream_part_id(user_id, conversation_id, "title_gen")
                yield _sse_json(
                    {
                        "type": "title_gen",
                        "id": title_gen_id,
                        "title": generated_title,
                    },
                    conversation_id,
                    message_id,
                )

            try:
                # Only original, text-only user input can approve. Tool/model messages
                # never enter this path. Graph approvals resume the interrupted tool.
                approval_text = user if all(getattr(item, "type", None) == "text" for item in request.inputs) else ""
                recent_session = _without_statistics_messages(read_session(user_id, conversation_id) or {})
                recent_history = recent_session.get("messages", [])
                # 查询当前有没有待审批命令
                pending = shell_scope.store.list_pending(shell_scope)
                # 当前是否存在一个 由 LangGraph 执行流程产生的审批中断。
                graph_pending = bool(pending and pending[0].get("graph_approval"))
                approval_reply = await handle_natural_approval_reply(
                    approval_text, shell_scope, lambda: _build_guarded_shell_backend(load_agent_config()),
                    history=recent_history,
                    llm_config=load_current_llm_config(),
                    for_graph=graph_pending,
                )
                # 等待审批
                if graph_pending and approval_reply is None:
                    approval_reply = await answer_pending_approval_question(
                        approval_text,
                        shell_scope,
                        history=recent_history,
                        llm_config=load_current_llm_config(),
                    )
                # Command恢复agent流
                if isinstance(approval_reply, GraphApprovalDecision):
                    stream_input = Command(resume={
                        "approval_id": approval_reply.approval_id,
                        "approve": approval_reply.approve,
                        "changed_request": approval_reply.changed_request,
                    })
                else:
                    stream_input = input_data
                if isinstance(approval_reply, str):
                    text_id = await next_stream_part_id(user_id, conversation_id, "text")
                    approval_recovery = (text_id, approval_reply)
                    append_session_message(user_id, conversation_id, {
                        "role": "assistant", "id": text_id, "type": "text", "text": approval_reply,
                    })
                    # Keep graph history aligned with the deterministic server reply.
                    if not graph_pending:
                        try:
                            await agent.aupdate_state(config, {"messages": [
                                *input_data["messages"], {"role": "assistant", "content": approval_reply},
                            ]})
                        except Exception:
                            # The approval has already been consumed. A checkpoint
                            # outage must not hide the result or trigger an automatic retry.
                            logger.exception("Failed to save shell approval reply to graph history")
                    for event in (
                        {"type": "text-start", "id": text_id},
                        {"type": "text-delta", "id": text_id, "delta": approval_reply},
                        {"type": "text-end", "id": text_id},
                    ):
                        yield _sse_json(event, conversation_id, message_id)
                    statistics_sse = await consume_statistics_sse()
                    if statistics_sse is not None:
                        yield statistics_sse
                    yield _sse_json(
                        {"type": "finish", "finishReason": "stop"},
                        conversation_id,
                        message_id,
                    )
                    approval_recovery = None
                    yield sse_message("[DONE]")
                    return
                graph_mode_token = GRAPH_APPROVAL_MODE.set(True)
                graph_resume_token = (
                    GRAPH_APPROVAL_RESUME.set(GraphApprovalResume(approval_reply.approval_id, pending[0]["command"]))
                    if isinstance(approval_reply, GraphApprovalDecision) else None
                )
                try:
                    async for part in _agent_astream(
                        agent=agent,
                        input_data=stream_input,
                        config=config,
                        runtime_context=runtime_context,
                    ):
                        if _is_stream_stop_requested(conversation_id):
                            logger.info("Chat stream stop requested, ending stream")
                            for event in processor.close_content():
                                yield _sse_json(event, conversation_id, message_id)
                            processor.finish_reason = "cancelled"
                            statistics_sse = await consume_statistics_sse()
                            if statistics_sse is not None:
                                yield statistics_sse
                            yield _sse_json(
                                {"type": "finish", "finishReason": "cancelled"},
                                conversation_id,
                                message_id,
                            )
                            yield sse_message("[DONE]")
                            return
                        async for event in processor.handle_part(part):
                            _record_job_statistics(runtime_context, event)
                            yield _sse_json(event, conversation_id, message_id)
                finally:
                    if graph_resume_token is not None:
                        GRAPH_APPROVAL_RESUME.reset(graph_resume_token)
                    GRAPH_APPROVAL_MODE.reset(graph_mode_token)
                pending = shell_scope.store.list_pending(shell_scope)
                if pending and pending[0].get("graph_approval"):
                    record = pending[0]
                    for event in processor.finalize_approval_pause():
                        yield _sse_json(event, conversation_id, message_id)
                    approval_message = (
                        "此删除操作需要确认，尚未执行。\n"
                        f"命令：{record['command']}\n"
                        f"工作目录：{record['cwd']}\n"
                        f"目标：{', '.join(item['path'] for item in record['targets'])}\n"
                        "原因：删除需要审批。\n"
                        f"编号：{record['id']}\n请回复确认或取消。"
                    )
                    text_id = await next_stream_part_id(user_id, conversation_id, "text")
                    append_session_message(user_id, conversation_id, {
                        "role": "assistant", "id": text_id, "type": "text", "text": approval_message,
                    })
                    for event in (
                        {"type": "text-start", "id": text_id},
                        {"type": "text-delta", "id": text_id, "delta": approval_message},
                        {"type": "text-end", "id": text_id},
                    ):
                        yield _sse_json(event, conversation_id, message_id)
            except asyncio.CancelledError as exc:
                client_disconnected: bool | str = "unknown"
                if http_request is not None:
                    try:
                        client_disconnected = await http_request.is_disconnected()
                    except Exception as disconnect_exc:
                        client_disconnected = (
                            f"check_failed:{type(disconnect_exc).__name__}:{disconnect_exc}"
                        )
                stop_requested = _is_stream_stop_requested(conversation_id)
                cancel_source = str(exc.args[0]) if exc.args else ""
                if not cancel_source:
                    cancel_source = "user_stop_requested" if stop_requested else "unattributed"
                current_stream_task = asyncio.current_task()
                logger.warning(
                    "Chat stream cancelled cancel_source=%s stop_requested=%s "
                    "client_disconnected=%s finish_reason=%s task_name=%s cancelling=%s",
                    cancel_source,
                    stop_requested,
                    client_disconnected,
                    processor.finish_reason,
                    current_stream_task.get_name() if current_stream_task is not None else "unknown",
                    current_stream_task.cancelling() if current_stream_task is not None else "unknown",
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                if not stop_requested:
                    _queue_interruption_recovery(
                        processor,
                        conversation_id,
                        message_id,
                    )
                    # The transport is already unavailable, so this event cannot
                    # be delivered. Still consume and persist the snapshot for
                    # diagnostics and to keep the next run isolated.
                    try:
                        await consume_statistics_sse()
                    except Exception:
                        logger.exception("Failed to persist statistics for interrupted chat stream")
                    return
                for event in processor.close_content():
                    yield _sse_json(event, conversation_id, message_id)
                processor.finish_reason = "cancelled"
                statistics_sse = await consume_statistics_sse()
                if statistics_sse is not None:
                    yield statistics_sse
                yield _sse_json(
                    {"type": "finish", "finishReason": "cancelled"},
                    conversation_id,
                    message_id,
                )
                yield sse_message("[DONE]")
                return
            except Exception as exc:
                for event in processor.close_content():
                    yield _sse_json(event, conversation_id, message_id)
                async for event in processor.handle_error(exc):
                    yield _sse_json(event, conversation_id, message_id)
                processor.finish_reason = "error"
                for event in processor.finish_events():
                    yield _sse_json(event, conversation_id, message_id)
                statistics_sse = await consume_statistics_sse()
                if statistics_sse is not None:
                    yield statistics_sse
                yield _sse_json(
                    {"type": "finish", "finishReason": "error"},
                    conversation_id,
                    message_id,
                )
                yield sse_message("[DONE]")
                return
            finally:
                try:
                    processor.flush()
                except Exception:
                    logger.exception("Failed to flush buffered session content")
                await _log_summarization_checkpoint(
                    agent=agent,
                    config=config,
                    conversation_id=conversation_id,
                    filtered_chunks=processor.summarization_chunks_filtered,
                )

            for event in processor.finish_events():
                yield _sse_json(event, conversation_id, message_id)
            processor.complete_session()
            statistics_sse = await consume_statistics_sse()
            if statistics_sse is not None:
                yield statistics_sse
            yield _sse_json(
                {
                    "type": "finish",
                    "finishReason": (
                        "interaction"
                        if processor.finish_reason == "resource_cards"
                        else processor.finish_reason
                    ),
                },
                conversation_id,
                message_id,
            )
            logger.info("Chat stream finished finish_reason=%s", processor.finish_reason)
            yield sse_message("[DONE]")
        except OSError:
            logger.exception("Chat session storage is not writable")
            if not stream_started:
                stream_started = True
                yield _sse_json(
                    {"type": "start", "time": request_time},
                    conversation_id,
                    message_id,
                )
            if approval_recovery is not None:
                recovery_id, recovery_text = approval_recovery
                warning = "\n\n警告：命令处理结果未能写入会话存储；请保留以上结果，未核对实际状态前不要重试。"
                for event in (
                    {"type": "text-start", "id": recovery_id},
                    {"type": "text-delta", "id": recovery_id, "delta": recovery_text + warning},
                    {"type": "text-end", "id": recovery_id},
                ):
                    yield _sse_json(event, conversation_id, message_id)
            yield _sse_json(
                {
                    "type": "error",
                    "errorText": SESSION_STORAGE_WRITE_ERROR_TEXT,
                },
                conversation_id,
                message_id,
            )
            statistics_sse = await consume_statistics_sse()
            if statistics_sse is not None:
                yield statistics_sse
            yield _sse_json(
                {"type": "finish", "finishReason": "error"},
                conversation_id,
                message_id,
            )
            yield sse_message("[DONE]")
            return
        except Exception as exc:
            logger.exception("Chat stream initialization failed")
            if not stream_started:
                stream_started = True
                yield _sse_json(
                    {"type": "start", "time": request_time},
                    conversation_id,
                    message_id,
                )
            yield _sse_json(
                {"type": "error", "errorText": stream_error_text(exc)},
                conversation_id,
                message_id,
            )
            statistics_sse = await consume_statistics_sse()
            if statistics_sse is not None:
                yield statistics_sse
            yield _sse_json(
                {"type": "finish", "finishReason": "error"},
                conversation_id,
                message_id,
            )
            yield sse_message("[DONE]")
            return
        finally:
            if shell_scope_token is not None:
                CURRENT_APPROVAL_SCOPE.reset(shell_scope_token)
            if processor is not None:
                try:
                    processor.flush()
                except Exception:
                    logger.exception("Failed to flush buffered session content during cleanup")
            active_task = _ACTIVE_STREAM_TASKS.get(conversation_id)
            if active_task is current_task:
                _ACTIVE_STREAM_TASKS.pop(conversation_id, None)
            _clear_stream_stop(conversation_id)


async def _chat_sse_stream(
    request: UserChatRequest,
    http_request: Request | None = None,
    *,
    message_id: str | None = None,
) -> Any:
    resolved_message_id = message_id or _new_stream_message_id()
    async for event in _chat_sse_source(request, http_request, resolved_message_id):
        yield event


async def _cached_chat_sse_stream(
    request: UserChatRequest,
    http_request: Request | None = None,
    *,
    message_id: str | None = None,
) -> Any:
    resolved_message_id = message_id or _new_stream_message_id()

    # ── 演示用：按前缀触发指定错误码 ──────────────────────
    demo_error = _check_demo_error_trigger(request)
    if demo_error is not None:
        yield _sse_json({"type": "start", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, request.conversation_id, resolved_message_id)
        yield _sse_json(
            {"type": "error", "errorText": demo_error["message"], "errorCode": demo_error["code"]},
            request.conversation_id,
            resolved_message_id,
        )
        yield _sse_json({"type": "finish", "finishReason": "error"}, request.conversation_id, resolved_message_id)
        yield "data: [DONE]\n\n"
        return
    # ── 演示拦截结束 ────────────────────────────────────

    await begin_sse_cache(request.conversation_id, message_id=resolved_message_id)
    try:
        async for event in _chat_sse_stream(
            request,
            http_request,
            message_id=resolved_message_id,
        ):
            await append_sse_cache_event(request.conversation_id, event)
            yield event
    finally:
        await close_sse_cache(request.conversation_id)


@router.post("/chat")
async def user_chat(request: UserChatRequest, http_request: Request) -> StreamingResponse:
    user_id = validate_user_id(resolved_request_user_id(request))
    for interaction_id, selected_value in request_resource_card_selections(request):
        try:
            update_resource_card_interaction_selection(
                user_id,
                request.conversation_id,
                interaction_id,
                selected_value,
            )
        except Exception:
            logger.warning(
                "Failed to update resource card interaction selection; continuing chat "
                "interaction_id=%s selected_value=%s",
                interaction_id,
                selected_value,
                exc_info=True,
            )

    with log_context(conversation_id=request.conversation_id):
        request_log_payload = request.model_dump(by_alias=True, exclude_none=True)
        logger.info(
            "Received /api/user/agent/chat request body=%s",
            json.dumps(request_log_payload, ensure_ascii=False),
        )
        _clear_stream_stop(request.conversation_id)
        clear_graph_stop(request.conversation_id)
        update_session_status(
            user_id,
            request.conversation_id,
            CONVERSATION_STATUS_IN_PROGRESS,
        )

    message_id = _new_stream_message_id()
    return StreamingResponse(
        stream_with_heartbeat(
            _cached_chat_sse_stream(request, http_request, message_id=message_id),
            request.conversation_id,
            message_id=message_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/cache", response_model=None)
async def user_chat_cache(request: UserChatCacheRequest) -> StreamingResponse | dict[str, Any]:
    conversation_id = request.conversation_id
    if not has_sse_cache(conversation_id):
        return {"code": 0, "msg": "chat cache not found", "data": None}
    return StreamingResponse(
        stream_with_heartbeat(
            stream_sse_cache(conversation_id),
            conversation_id,
            message_id=get_sse_cache_message_id(conversation_id),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/stop")
async def user_stop(request: UserStopRequest) -> dict[str, Any]:
    user_id = validate_user_id(request.user_id)
    with log_context(conversation_id=request.conversation_id):
        logger.info(
            "Received /api/user/agent/stop request body=%s",
            json.dumps(request.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False),
        )
        update_session_status(
            user_id,
            request.conversation_id,
            CONVERSATION_STATUS_CANCELLED,
        )
        request_graph_stop(request.conversation_id)
        _request_stream_stop(request.conversation_id)
        task = _ACTIVE_STREAM_TASKS.get(request.conversation_id)
        stopped = task is not None and not task.done()
        if stopped:
            logger.info("Stopping chat stream")
            task.cancel("user_stop_requested")
        else:
            logger.info("No active chat stream task found; stop request recorded")

    status = "stopped" if stopped else "stop_requested"
    return {"code": 0, "msg": "success", "data": {"status": status}}


@router.get("/sessions")
async def user_sessions(user_id: str = Query(..., alias="userId")) -> dict[str, Any]:
    try:
        return {"code": 0, "msg": "success", "data": list_sessions(validate_user_id(user_id))}
    except Exception as exc:
        logger.exception("Failed to list chat sessions")
        return {"code": 1, "msg": str(exc), "data": None}


@router.get("/sessions/{conversation_id}")
async def user_session(conversation_id: str, user_id: str = Query(..., alias="userId")) -> dict[str, Any]:
    try:
        session = read_session(validate_user_id(user_id), conversation_id)
    except ValueError as exc:
        return {"code": 1, "msg": str(exc), "data": None}
    except Exception as exc:
        logger.exception("Failed to read chat session")
        return {"code": 1, "msg": str(exc), "data": None}
    if session is None:
        return {"code": 1, "msg": "conversation not found", "data": None}
    session = _hide_active_assistant_tail(session, conversation_id)
    session = _without_statistics_messages(session)
    session["status"] = session.get("status")
    return {"code": 0, "msg": "success", "data": session}


@router.delete("/sessions/{conversation_id}")
async def delete_user_session(conversation_id: str, user_id: str = Query(..., alias="userId")) -> dict[str, Any]:
    try:
        validated_user_id = validate_user_id(user_id)
        deleted = delete_session(validated_user_id, conversation_id)
    except ValueError as exc:
        return {"code": 1, "msg": str(exc), "data": {"deleted": False}}
    except Exception as exc:
        logger.exception("Failed to delete chat session")
        return {"code": 1, "msg": str(exc), "data": {"deleted": False}}
    if not deleted:
        return {"code": 1, "msg": "conversation not found", "data": {"deleted": False}}
    await clear_stream_part_ids(validated_user_id, conversation_id)
    discard_recovery_events(conversation_id)
    return {"code": 0, "msg": "success", "data": {"deleted": True}}


@router.put("/config")
async def user_agent_restart(request: UserAgentRestartRequest | None = None) -> dict[str, Any]:
    request = request or UserAgentRestartRequest()
    logger.info(
        "Config update request restart_only=%s skills=%s mcp=%s datasets=%s",
        request.restart_only,
        json.dumps(request.skills, ensure_ascii=False, default=str),
        json.dumps(request.mcp, ensure_ascii=False, default=str),
        json.dumps(request.datasets, ensure_ascii=False, default=str),
    )
    if not request.restart_only:
        try:
            apply_restart_config(request)
        except ValueError as exc:
            logger.warning("Invalid restart request model=%s error=%s", request.model, exc)
            return {"code": 1, "msg": str(exc), "data": {"agentRebuilt": False}}
        except Exception as exc:
            logger.exception("Failed to update restart configuration")
            return {"code": 1, "msg": str(exc), "data": {"agentRebuilt": False}}

    return await _rebuild_agent_after_config_update(
        operation="config",
        restart_only=request.restart_only,
    )


@router.put("/config/private")
async def update_private_resources(request: PrivateResourcesUpdateRequest) -> dict[str, Any]:
    logger.info(
        "Private config update request skills=%s mcp=%s datasets=%s",
        json.dumps(request.skills, ensure_ascii=False, default=str),
        json.dumps(request.mcp, ensure_ascii=False, default=str),
        json.dumps(request.datasets, ensure_ascii=False, default=str),
    )
    try:
        apply_private_resources_config(request)
    except ValueError as exc:
        logger.warning("Invalid private config update error=%s", exc)
        return {"code": 1, "msg": str(exc), "data": {"agentRebuilt": False}}
    except Exception as exc:
        logger.exception("Failed to update private resources")
        return {"code": 1, "msg": str(exc), "data": {"agentRebuilt": False}}

    return await _rebuild_agent_after_config_update(operation="private_config")


async def _rebuild_agent_after_config_update(
    *,
    operation: str,
    restart_only: bool = False,
) -> dict[str, Any]:

    cached_before = AGENTS.list()
    removed = AGENTS.drop()
    try:
        await AGENTS.get(sync_llm_config=False)
    except Exception as exc:
        logger.exception("Failed to rebuild agent after restart")
        return {
            "code": 1,
            "msg": f"agent restart rebuild failed: {exc}",
            "data": {"agentRebuilt": False},
        }

    from src.api.routes.general import reset_create_marker_cache

    reset_create_marker_cache()

    if not report_enabled():
        asyncio.create_task(_register_a2a_agent_card())

    logger.info(
        "Agent rebuild requested operation=%s restart_only=%s removed_agent_cache=%s cached_before=%s rebuilt=%s",
        operation,
        restart_only,
        removed,
        cached_before,
        True,
    )
    return {"code": 0, "msg": "success", "data": {"agentRebuilt": True}}


async def _register_a2a_agent_card() -> None:
    """非阻塞注册 A2A AgentCard 到 Nacos 注册中心。

    若 Nacos 中已存在同名 AgentCard 则更新，否则创建。
    """
    if report_enabled():
        return

    from src.a2a.a2a import agent_card_exists, register_agent_card

    try:
        exists = await agent_card_exists()
        ok = await register_agent_card(update=exists)
        action = "updated" if exists else "registered"
        if ok:
            logger.info("A2A agent card %s successfully", action)
        else:
            logger.warning("A2A agent card %s returned false", action)
    except Exception:
        logger.exception("A2A agent card registration threw unhandled error")


__all__ = ["router"]
