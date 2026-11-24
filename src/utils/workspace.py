from __future__ import annotations

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONVERSATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_conversation_id(conversation_id: str) -> str:
    if not conversation_id or not _CONVERSATION_ID_PATTERN.fullmatch(conversation_id):
        raise ValueError("invalid conversationId")
    return conversation_id


def validate_user_id(user_id: str) -> str:
    if not user_id or not _USER_ID_PATTERN.fullmatch(user_id):
        raise ValueError("invalid userId")
    return user_id


def conversation_workspace(conversation_id: str) -> Path:
    home = os.getenv("HOME")
    if not home:
        raise ValueError("HOME environment variable is required")
    return Path(home) / "workspace" / validate_conversation_id(conversation_id)


def ensure_workspace_root() -> Path:
    home = os.getenv("HOME")
    if not home:
        raise ValueError("HOME environment variable is required")
    workspace_root = Path(home) / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    return workspace_root


def ensure_conversation_workspace(conversation_id: str) -> Path:
    workspace = conversation_workspace(conversation_id)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


__all__ = [
    "PROJECT_ROOT",
    "conversation_workspace",
    "ensure_conversation_workspace",
    "ensure_workspace_root",
    "validate_conversation_id",
    "validate_user_id",
]
