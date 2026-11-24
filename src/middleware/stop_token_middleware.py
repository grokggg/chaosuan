from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState, hook_config
from langgraph.runtime import Runtime

from src.agents.context import AgentRuntimeContext
from src.api.stop_tokens import consume_graph_stop
from src.logger import get_logger

logger = get_logger(__name__)


def _runtime_conversation_id(runtime: Runtime) -> str | None:
    context = runtime.context
    if isinstance(context, AgentRuntimeContext):
        return context.conversation_id
    return None


class StopTokenMiddleware(AgentMiddleware):
    name = "StopTokenMiddleware"

    def _consume_stop(self, runtime: Runtime, *, phase: str) -> dict[str, Any] | None:
        conversation_id = _runtime_conversation_id(runtime)
        if not conversation_id:
            return None
        if not consume_graph_stop(conversation_id):
            return None

        logger.info("Graph stop token consumed before continuing conversation_id=%s phase=%s", conversation_id, phase)
        return {"jump_to": "end"}

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._consume_stop(runtime, phase="before_model")

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._consume_stop(runtime, phase="before_model")

    @hook_config(can_jump_to=["end"])
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._consume_stop(runtime, phase="after_model")

    @hook_config(can_jump_to=["end"])
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._consume_stop(runtime, phase="after_model")


__all__ = ["StopTokenMiddleware"]
