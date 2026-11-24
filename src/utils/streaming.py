from __future__ import annotations

from langgraph.config import get_stream_writer

CUSTOM_AI_MESSAGE_DELTA = "ai_message_delta"
CUSTOM_JOB_MONITOR = "job_monitor"
CUSTOM_RESPONSE_FINISH_REASON = "response_finish_reason"
CUSTOM_TOOL_HANDOFF_FINISH = "tool_handoff_finish"
CUSTOM_TOOL_CALL_SYNC = "tool_call_sync"


def _split_stream_text(content: str) -> list[str]:
    text = str(content)
    if not text:
        return []

    if len(text) <= 16:
        width = len(text)
    elif len(text) <= 80:
        width = 8
    else:
        width = 12
    return [text[index : index + width] for index in range(0, len(text), width)]


def log_ai_message(content: str, *, visible: bool = True, **metadata: object) -> None:
    writer = get_stream_writer()
    writer(
        {
            "type": CUSTOM_AI_MESSAGE_DELTA,
            "content": str(content),
            "visible": visible,
            **metadata,
        }
    )


def log_ai_message_stream(content: str, *, visible: bool = True, **metadata: object) -> None:
    for chunk in _split_stream_text(content):
        log_ai_message(chunk, visible=visible, **metadata)


def emit_response_finish_reason(finish_reason: str) -> None:
    writer = get_stream_writer()
    writer(
        {
            "type": CUSTOM_RESPONSE_FINISH_REASON,
            "finishReason": finish_reason,
        }
    )


__all__ = [
    "CUSTOM_AI_MESSAGE_DELTA",
    "CUSTOM_JOB_MONITOR",
    "CUSTOM_RESPONSE_FINISH_REASON",
    "CUSTOM_TOOL_HANDOFF_FINISH",
    "CUSTOM_TOOL_CALL_SYNC",
    "emit_response_finish_reason",
    "log_ai_message",
    "log_ai_message_stream",
]
