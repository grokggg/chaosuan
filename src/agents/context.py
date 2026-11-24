from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentRuntimeContext:
    cluster_id: str | None = None
    user_id: str | None = None
    username: str | None = None
    conversation_id: str | None = None
    extra: dict[str, Any] | None = None
    inputs: list[dict[str, Any]] | None = None
    uploaded_file_prompt: str | None = None

    @classmethod
    def from_environment(cls, *, conversation_id: str | None = None) -> AgentRuntimeContext:
        return cls(
            cluster_id=os.getenv("CLUSTER_ID") or None,
            user_id=os.getenv("USER_ID") or None,
            username=os.getenv("USER_NAME") or None,
            conversation_id=conversation_id,
        )


__all__ = ["AgentRuntimeContext"]
