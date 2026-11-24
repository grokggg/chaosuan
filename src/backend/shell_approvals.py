"""Server-owned, in-process, single-use local shell approvals.

Only the chat request adapter may interpret user replies. Models never receive an
approval flag or a tool for approving commands. A lock serializes claims.
Pending approvals are lost on restart and are not shared across workers.
"""

from __future__ import annotations

import json
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from src.utils.workspace import validate_conversation_id, validate_user_id


@dataclass(frozen=True)
class ApprovalScope:
    user_id: str
    conversation_id: str
    store: ApprovalStore


CURRENT_APPROVAL_SCOPE: ContextVar[ApprovalScope | None] = ContextVar("shell_approval_scope", default=None)
GRAPH_APPROVAL_MODE: ContextVar[bool] = ContextVar("graph_shell_approval_mode", default=False)


@dataclass
class GraphApprovalResume:
    approval_id: str
    command: str
    used: bool = False


GRAPH_APPROVAL_RESUME: ContextVar[GraphApprovalResume | None] = ContextVar("graph_shell_approval_resume", default=None)


@dataclass(frozen=True)
class _PendingApproval:
    record_id: str
    payload: str
    expires: float


class ApprovalStore:
    def __init__(
        self,
        *,
        ttl: int = 600,
        max_pending: int = 1000,
        journal_dir: str | Path | None = None,
        require_journal: bool = False,
    ):
        if ttl <= 0 or max_pending <= 0:
            raise ValueError("Approval TTL and capacity must be positive")
        self.ttl = ttl
        self.max_pending = max_pending
        self.journal_dir = Path(journal_dir) if journal_dir is not None else None
        self.require_journal = require_journal
        self._records: dict[tuple[str, str], _PendingApproval] = {}
        self._protected_denials: dict[tuple[str, str], float] = {}
        self._lock = Lock()
        self._journal_lock = Lock()

    def _execution_journal_root(self) -> Path | None:
        if self.journal_dir is not None:
            return self.journal_dir
        if not self.require_journal:
            return None
        home_dir = os.getenv("HOME", "").strip()
        if not home_dir:
            raise OSError("HOME is required for the shell approval execution journal")
        return Path(home_dir) / ".data" / "user" / "shell-approval-executions"

    def record_execution(
        self,
        scope: ApprovalScope,
        record: dict[str, Any],
        *,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> Path | None:
        """Atomically persist command execution state before and after running it."""
        root = self._execution_journal_root()
        if root is None:
            return None
        if status not in {"executing", "completed"}:
            raise ValueError("invalid shell approval execution status")
        user_id = validate_user_id(scope.user_id)
        conversation_id = validate_conversation_id(scope.conversation_id)
        record_id = str(record.get("id") or "")
        if not record_id or any(char not in "0123456789abcdef" for char in record_id):
            raise ValueError("invalid shell approval record id")

        path = root / user_id / conversation_id / f"{record_id}.json"
        payload = {
            "approvalId": record_id,
            "userId": user_id,
            "conversationId": conversation_id,
            "status": status,
            "command": record.get("command"),
            "cwd": record.get("cwd"),
            "timeout": record.get("timeout"),
            "targets": record.get("targets", []),
            "updatedAt": datetime.now(UTC).isoformat(),
        }
        if result is not None:
            payload["result"] = result

        temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        with self._journal_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with temp_path.open("w", encoding="utf-8", newline="\n") as file:
                    json.dump(payload, file, ensure_ascii=False, indent=2)
                    file.write("\n")
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temp_path, path)
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
        return path

    def _prune(self) -> None:
        """Called under the lock; bounded lazy cleanup needs no background worker."""
        now = time.monotonic()
        expired = [key for key, record in self._records.items() if record.expires <= now]
        for key in expired:
            del self._records[key]
        expired_denials = [key for key, expires in self._protected_denials.items() if expires <= now]
        for key in expired_denials:
            del self._protected_denials[key]

    def record_protected_denial(self, scope: ApprovalScope) -> None:
        key = (scope.user_id, scope.conversation_id)
        with self._lock:
            self._prune()
            if key not in self._protected_denials and len(self._protected_denials) >= self.max_pending:
                oldest = min(self._protected_denials, key=self._protected_denials.__getitem__)
                del self._protected_denials[oldest]
            self._protected_denials[key] = time.monotonic() + self.ttl

    def has_protected_denial(self, scope: ApprovalScope) -> bool:
        with self._lock:
            self._prune()
            return (scope.user_id, scope.conversation_id) in self._protected_denials

    def pending(self, scope: ApprovalScope, payload: dict[str, Any], *, replace_existing: bool = True) -> str:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        key = (scope.user_id, scope.conversation_id)
        with self._lock:
            self._prune()
            current = self._records.get(key)
            if current is not None and current.payload == encoded:
                return current.record_id
            if current is not None and not replace_existing:
                raise ValueError("Another operation is already pending approval in this conversation")
            if current is None and len(self._records) >= self.max_pending:
                raise ValueError("Too many pending approvals; cancel an existing request or retry after expiry")
            record_id = uuid4().hex
            self._records[key] = _PendingApproval(record_id, encoded, time.monotonic() + self.ttl)
            return record_id

    def list_pending(self, scope: ApprovalScope) -> list[dict[str, Any]]:
        key = (scope.user_id, scope.conversation_id)
        with self._lock:
            self._prune()
            record = self._records.get(key)
            return [] if record is None else [{**json.loads(record.payload), "id": record.record_id}]

    def claim(self, scope: ApprovalScope, record_id: str | None, approve: bool) -> tuple[dict | None, str]:
        key = (scope.user_id, scope.conversation_id)
        with self._lock:
            self._prune()
            record = self._records.get(key)
            if record is None or (record_id is not None and record.record_id != record_id):
                return (
                    None,
                    "没有匹配的有效待审批操作（可能已处理、过期或服务已重启），未执行任何命令。请重新提交具体操作。",
                )
            # Remove atomically before executing. No retained result/claimed records
            # are needed: an absent ID cannot execute again.
            del self._records[key]
            if not approve:
                return None, f"已取消审批 {record.record_id}，未执行命令。"
            return {**json.loads(record.payload), "id": record.record_id}, ""


_APPROVAL_STORE = ApprovalStore(require_journal=True)


def create_scope(user_id: str, conversation_id: str) -> ApprovalScope:
    return ApprovalScope(user_id, conversation_id, _APPROVAL_STORE)


PROTECTED_DENIAL_CONTEXT = """A protected file operation was denied in this conversation.
If the user asks about that target again, answer their question normally while
maintaining the refusal. Explain the reason without proposing another operation
that would remove, empty, move, or disable the same protected content. Do not ask
the user to choose an alternative. Unrelated questions should be answered normally."""


def protected_denial_context() -> str:
    scope = CURRENT_APPROVAL_SCOPE.get()
    if scope is None or not scope.store.has_protected_denial(scope):
        return ""
    return PROTECTED_DENIAL_CONTEXT


SHELL_POLICY_INSTRUCTION = """
[Local shell policy and conversation approval]
For a user-requested local command, submit the exact command to execute for policy
checking first. Do not ask for confirmation on your own or promise execution after
confirmation. The backend is the authority for ALLOW / COMMAND_DENIED / APPROVAL_REQUIRED.
COMMAND_DENIED is final: explain the reason, never ask the user to override it and
never use a script, another tool, or another command form to bypass the restriction.
In particular, a compound deletion such as `pwd && rm -rf build` is denied, not
pending approval. Do not ask the user to confirm it; explain that they must submit
a separate, explicit deletion command for a new policy check.
Deleting the workspace directory itself, protected project directories or any
of their contents, listed project files, Git metadata, Git-tracked files,
or directories containing protected content is forbidden. User-owned files and
directories inside the workspace can be deleted or moved without approval.
They can be moved to the user's home directory outside the instance root.
In this deployment `$HOME` and `~` refer to the instance root; use the explicit
user home path and literal source file paths when moving workspace files.
Other explicit paths in the instance, including new untracked project files,
require approval before deletion.
Moving or renaming these protected paths is forbidden as well, including with
`mv`, `git mv`, `move`, and `rename` commands.
When a protected file operation is denied, briefly state the reason and stop.
Do not offer or ask the user to choose an alternative that removes the same content
or evades tracking, such as emptying or overwriting the file, renaming or moving it,
adding it to .gitignore, or running git rm --cached before deletion.
This applies to later follow-up questions in the same conversation, including
"what options do I have?" and requests for a compliant workaround. Repeat the
refusal without listing possible operations or inviting the user to choose one.
For APPROVAL_REQUIRED, display the returned command, cwd, targets, reason and approval
ID faithfully, then end your response with “请回复确认或取消。” Do not show example
reply phrases or imply that a fixed phrase is required. The user can approve or
cancel in natural language. They need not repeat an ID unless
the operation is ambiguous. Questions do not approve or cancel a pending operation.
Changes to the target or command require a new policy check and a new approval.
The server interprets the reply in context and resumes the saved tool call once;
you cannot approve it yourself. Ordinary chat confirmation without a pending server
record is not authorization. Do not repeat the command after server execution.
After a successful resumed tool result, continue the user's unfinished task.
If the operation was cancelled or failed, do not assume deletion succeeded or
continue steps that depend on it.
""".strip()
