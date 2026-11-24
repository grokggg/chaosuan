from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any, override
from uuid import uuid4

import httpx
from a2a.helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from google.protobuf import json_format

from a2a import types as a2a_types

CHAT_PATH = "/api/user/agent/chat"
DEFAULT_A2A_USER_ID = "a2a"
SAG_MAKER_EVENT_METADATA_KEY = "sagMakerEvent"
SAG_MAKER_EVENT_SEQUENCE_METADATA_KEY = "sagMakerEventSequence"


class SagMakerA2AExecutor(AgentExecutor):
    """A2A executor that adapts requests to the existing SAG Maker chat API."""

    def __init__(self, *, backend_url: str) -> None:
        self.backend_url = backend_url.rstrip("/")

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        if context.message is None:
            raise ValueError("A message is required")

        # 检查消息存在且文本非空
        query = context.get_user_input()
        if not query.strip():
            raise ValueError("Only non-empty text input is supported")

        # 创建或复用 A2A Task
        metadata = self._get_request_metadata(context)
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        # 初始化执行状态
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        artifact_id = uuid4().hex
        artifact_started = False
        pending_text: tuple[str, dict[str, Any] | None] | None = None
        backend_error: dict[str, Any] | None = None
        finish_reason: Any = None
        event_sequence = 0

        # 开始子智能体任务task
        await updater.start_work()

        # 调用 SAG Maker 后端 并遍历 SSE
        async for chunk in self._stream_backend_chat(
            query,
            metadata,
            conversation_id=task.context_id,
        ):
            chunk_event = chunk.get("event")
            chunk_metadata: dict[str, Any] | None = None

            # 为原始事件生成 metadata，文本输出转换为 A2A Artifact
            if chunk_event is not None:
                event_sequence += 1
                chunk_metadata = self._chunk_metadata(chunk, sequence=event_sequence)

            # 处理文本事件
            content = str(chunk.get("content") or "")
            if content and not chunk.get("error"):
                if pending_text is not None:
                    pending_content, pending_metadata = pending_text
                    await updater.add_artifact(
                        [new_text_part(pending_content, media_type="text/markdown")],
                        artifact_id=artifact_id,
                        name="response",
                        metadata=pending_metadata,
                        append=artifact_started,
                        last_chunk=False,
                    )
                    artifact_started = True
                pending_text = (content, chunk_metadata)

            # 判断文本 Artifact 是否结束
            event_type = chunk_event.get("type") if isinstance(chunk_event, dict) else None
            closes_text_artifact = event_type in {"finish", "error"} or bool(chunk.get("done"))

            # Artifact 结束，发送缓存在 pending_text 中的文本。
            if pending_text is not None and (not content or chunk.get("error") or closes_text_artifact):
                pending_content, pending_metadata = pending_text
                await updater.add_artifact(
                    [new_text_part(pending_content, media_type="text/markdown")],
                    artifact_id=artifact_id,
                    name="response",
                    metadata=pending_metadata,
                    append=artifact_started,
                    last_chunk=closes_text_artifact,
                )
                artifact_started = True
                pending_text = None

            # 记录错误和结束原因
            if chunk.get("error"):
                backend_error = chunk
            if chunk.get("finishReason") is not None:
                finish_reason = chunk.get("finishReason")

            # 推理、工具、文件预览、心跳等事件发送 TaskStatusUpdateEvent 事件
            if not chunk.get("done"):
                if chunk_metadata is not None and (not content or chunk.get("error")):
                    await updater.update_status(
                        a2a_types.TaskState.TASK_STATE_WORKING,
                        metadata=chunk_metadata,
                    )
                continue

            # 整合终态 metadata
            terminal_metadata = self._chunk_metadata(
                {
                    **chunk,
                    "error": bool(backend_error),
                    "content": str((backend_error or {}).get("content") or ""),
                    "finishReason": finish_reason,
                },
                sequence=event_sequence if chunk_event is not None else None,
            )

            # 有错误则标记 FAILED
            if backend_error:
                error_content = str(backend_error.get("content") or "SAG Maker backend request failed")
                error_message = updater.new_agent_message(
                    [new_text_part(error_content, media_type="text/plain")],
                    metadata=terminal_metadata,
                )
                await updater.update_status(
                    a2a_types.TaskState.TASK_STATE_FAILED,
                    message=error_message,
                    metadata=terminal_metadata,
                )
                return

            # 无错误则标记 COMPLETED
            await updater.update_status(
                a2a_types.TaskState.TASK_STATE_COMPLETED,
                metadata=terminal_metadata,
            )
            return

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if not context.task_id or not context.context_id:
            raise ValueError("Cancellation requires task and context IDs")
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()

    async def _stream_backend_chat(
        self,
        query: str,
        metadata: dict[str, Any] | None = None,
        *,
        conversation_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        # 构造 SAG Maker Chat API 请求
        url = f"{self.backend_url}{CHAT_PATH}"
        payload = self._build_chat_payload(query, metadata, conversation_id=conversation_id)

        # 使用 httpx 调用 /api/user/agent/chat
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", "ignore")
                        yield {
                            "content": f"[SAG Maker backend returned {response.status_code}] {body}",
                            "done": True,
                            "error": True,
                        }
                        return

                    # 逐行解析 SSE
                    async for line in response.aiter_lines():
                        event = self._parse_sse_line(line)
                        if event is None:
                            continue
                        yield event
                        if event.get("done"):
                            return

            yield {"content": "", "done": True}
        except Exception as exc:
            yield {
                "content": f"Failed to call SAG Maker backend: {exc}",
                "done": True,
                "error": True,
            }

    def _build_chat_payload(
        self,
        query: str,
        metadata: dict[str, Any] | None,
        *,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        metadata = metadata or {}
        resolved_conversation_id = (
            metadata.get("conversationId")
            or metadata.get("conversation_id")
            or metadata.get("threadId")
            or conversation_id
            or uuid4().hex
        )
        return {
            "userId": self._resolve_user_id(metadata),
            "conversationId": str(resolved_conversation_id),
            "inputs": [{"type": "text", "text": query}],
        }

    @staticmethod
    def _resolve_user_id(metadata: dict[str, Any]) -> str:
        raw_context = metadata.get("context")
        context = dict(raw_context) if isinstance(raw_context, dict) else {}
        user_id = metadata.get("userId") or metadata.get("user_id") or context.get("userId") or context.get("user_id")
        return str(user_id or DEFAULT_A2A_USER_ID).strip() or DEFAULT_A2A_USER_ID

    @staticmethod
    def _parse_sse_line(line: str) -> dict[str, Any] | None:
        if not line or not line.startswith("data:"):
            return None
        raw = line[5:].strip()
        if not raw:
            return None
        if raw == "[DONE]":
            return {"content": "", "done": True, "event": raw}

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {"content": raw, "done": False, "event": raw}

        if not isinstance(payload, dict):
            return {"content": "", "done": False, "event": payload}

        event_type = payload.get("type")
        if event_type == "text-delta":
            return {
                "content": str(payload.get("delta") or ""),
                "done": False,
                "event": payload,
            }
        if event_type == "error":
            return {
                "content": str(payload.get("errorText") or payload.get("message") or ""),
                "done": False,
                "error": True,
                "event": payload,
            }
        if event_type == "finish":
            return {
                "content": "",
                "done": False,
                "finishReason": payload.get("finishReason"),
                "event": payload,
            }

        # Compatibility with OpenAI-style chat completion chunks.
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            delta = choice.get("delta") if isinstance(choice, dict) else {}
            content = delta.get("content") if isinstance(delta, dict) else None
            finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
            if content:
                return {"content": str(content), "done": False, "event": payload}
            if finish_reason:
                return {
                    "content": "",
                    "done": False,
                    "finishReason": finish_reason,
                    "event": payload,
                }

        return {"content": "", "done": False, "event": payload}

    @staticmethod
    def _chunk_metadata(
        chunk: dict[str, Any],
        *,
        sequence: int | None = None,
    ) -> dict[str, Any] | None:
        metadata: dict[str, Any] = {}
        if chunk.get("event") is not None:
            metadata[SAG_MAKER_EVENT_METADATA_KEY] = chunk["event"]
            if sequence is not None:
                metadata[SAG_MAKER_EVENT_SEQUENCE_METADATA_KEY] = sequence
        if chunk.get("error"):
            metadata["error"] = True
            metadata["errorText"] = chunk.get("content", "")
        if chunk.get("finishReason"):
            metadata["finishReason"] = chunk.get("finishReason")
        return metadata or None

    @staticmethod
    def _get_request_metadata(context: RequestContext) -> dict[str, Any]:
        metadata: dict[str, Any] = dict(context.metadata)
        message = context.message
        if message is not None and message.HasField("metadata"):
            message_metadata = json_format.MessageToDict(message.metadata)
            if isinstance(message_metadata, dict):
                metadata.update(message_metadata)
        return metadata


__all__ = [
    "DEFAULT_A2A_USER_ID",
    "SAG_MAKER_EVENT_METADATA_KEY",
    "SAG_MAKER_EVENT_SEQUENCE_METADATA_KEY",
    "SagMakerA2AExecutor",
]
