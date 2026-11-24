from __future__ import annotations

import json
import logging
import os
import posixpath
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from deepagents.backends.composite import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import PERMISSION_DENIED, EditResult, WriteResult
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

from src.backend.guarded_local_shell import GuardedLocalShellBackend
from src.constants import SECURITY_PATH_POLICY

ALLOW = "ALLOW"
DENY = "DENY"
RUNTIME_DELETE_TOOLS = frozenset({"delete", "delete_file"})
RUNTIME_DENY = RUNTIME_DELETE_TOOLS

RUNTIME_PATH_INSTRUCTION = """
[Runtime filesystem paths]
The only path restrictions are: direct access to /public and
/public/home is denied, /opt/vibe-coding and its descendants are inaccessible,
and /public/software is read-only. Executing Python, scripts and scientific
software installed under /public/software is allowed, including in compound
commands. Shell checks reject recognizable writes to that path; inconclusive
checks are allowed. Physical project and workspace paths under
/public/home remain accessible through the default backend.

[Runtime deletion routing]
The delete and delete_file tools are blocked so that deletion is checked by the
local shell policy. If either tool returns DELETE_USE_EXECUTE, do not end the
request. Retry through execute. A direct rm or rmdir command with literal target
paths supports deletion approval when needed. Variable expansion, wildcards,
pipes, redirection and compound commands are also permitted under a best-effort
policy: recognizable forbidden operations are denied; inconclusive checks pass.
The execute backend decides whether deletion is allowed, denied, or requires
approval.
""".strip()
_PATH_ARGUMENT_KEYS = frozenset(
    {
        "path",
        "paths",
        "file_path",
        "file_paths",
        "output_dir",
        "output_path",
        "target_path",
        "destination",
        "directory",
        "cwd",
    }
)


def _policy_paths(policy_key: str) -> tuple[str, ...]:
    values = SECURITY_PATH_POLICY.get(policy_key, ())
    return tuple(
        dict.fromkeys(
            str(item).strip().replace("\\", "/").rstrip("/").lower()
            for item in values
            if str(item).strip()
        )
    )


_READ_ONLY_PATH_PREFIXES = _policy_paths("read_only_path_prefixes")
_NO_ACCESS_EXACT_HOST_PATHS = frozenset(_policy_paths("deny_exact_paths"))
_NO_ACCESS_HOST_PREFIXES = _policy_paths("deny_path_prefixes")
_PUBLIC_SOFTWARE_PREFIX = "/public/software"
_AUDIT_LOGGER: logging.Logger | None = None


@dataclass(frozen=True)
class SecurityDecision:
    allowed: bool
    policy_decision: str
    reason_code: str
    path_scope: str | None = None


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name") or "").strip()
    return str(getattr(tool, "name", getattr(tool, "__name__", ""))).strip()


def runtime_decision(tool_name: str) -> str:
    if str(tool_name or "").strip() in RUNTIME_DENY:
        return DENY
    return ALLOW


def filter_runtime_tools(tools: list[Any]) -> list[Any]:
    seen: set[str] = set()
    filtered: list[Any] = []
    for tool in tools:
        name = _tool_name(tool)
        if not name:
            raise ValueError("tool name must not be empty")
        if name in seen:
            raise ValueError(f"duplicate tool name: {name}")
        seen.add(name)
        filtered.append(tool)
    return filtered


class ReadOnlyFilesystemBackend(FilesystemBackend):
    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=PERMISSION_DENIED)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return EditResult(error=PERMISSION_DENIED)


def build_runtime_backend(
    shell_backend: GuardedLocalShellBackend,
    public_software_root: Path = Path(_PUBLIC_SOFTWARE_PREFIX),
) -> CompositeBackend:
    routes = {}
    for prefix in _READ_ONLY_PATH_PREFIXES:
        root = public_software_root if prefix == _PUBLIC_SOFTWARE_PREFIX else Path(prefix)
        routes[f"{prefix}/"] = ReadOnlyFilesystemBackend(root.resolve(), virtual_mode=True)
    return CompositeBackend(default=shell_backend, routes=routes)


def runtime_permissions() -> list[FilesystemPermission]:
    return [
        FilesystemPermission(
            operations=["write"],
            paths=[f"{prefix}/**" for prefix in _READ_ONLY_PATH_PREFIXES],
            mode="deny",
        ),
    ]


def _iter_path_values(value: Any, *, key: str | None = None):
    if key in _PATH_ARGUMENT_KEYS:
        if isinstance(value, str):
            yield value
            return
        if isinstance(value, list):
            yield from (item for item in value if isinstance(item, str))
            return
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _iter_path_values(child_value, key=str(child_key))


def _normalized_host_path(path: str) -> str | None:
    text = str(path or "").strip().strip('"').strip("'").replace("\\", "/")
    if not text.startswith("/"):
        return None
    return f"/{posixpath.normpath(text).lstrip('/')}".lower()


def _is_path_within(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _host_path_policy(path: str, *, write: bool) -> tuple[bool, str, str] | None:
    normalized = _normalized_host_path(path)
    if normalized is None:
        return None
    if any(_is_path_within(normalized, prefix) for prefix in _READ_ONLY_PATH_PREFIXES):
        if write:
            return False, "READ_ONLY_PATH", normalized
        return True, "POLICY_ALLOWED", normalized
    if normalized in _NO_ACCESS_EXACT_HOST_PATHS or any(
        _is_path_within(normalized, prefix) for prefix in _NO_ACCESS_HOST_PREFIXES
    ):
        return False, "PATH_ACCESS_DENIED", normalized
    return None


def _is_write_tool(tool_name: str) -> bool:
    return tool_name in {
        "write_file",
        "edit_file",
        "delete",
        "delete_file",
        "download_oss_files",
        "generate_computation_report",
    }


def evaluate_runtime_call(
    tool_name: str,
    args: dict[str, Any] | None,
    *,
    conversation_id: str | None,
) -> SecurityDecision:
    policy = runtime_decision(tool_name)
    if policy == DENY:
        reason_code = "DELETE_USE_EXECUTE" if tool_name in RUNTIME_DELETE_TOOLS else "UNKNOWN_TOOL"
        return SecurityDecision(False, DENY, "UNKNOWN_TOOL")

    path_scope = "filesystem"
    for raw_path in _iter_path_values(args or {}):
        host_policy = _host_path_policy(raw_path, write=_is_write_tool(tool_name))
        if host_policy is not None:
            allowed, reason_code, _normalized = host_policy
            if not allowed:
                return SecurityDecision(False, policy, reason_code)
            path_scope = "public_software"
            continue

    return SecurityDecision(True, policy, "POLICY_ALLOWED", path_scope)


def _context_value(runtime: Any, *names: str) -> str | None:
    context = getattr(runtime, "context", None)
    for name in names:
        value = context.get(name) if isinstance(context, dict) else getattr(context, name, None)
        if value not in {None, ""}:
            return str(value)
    return None


def build_audit_record(
    *,
    event: str,
    agent_profile: str,
    conversation_id: str | None = None,
    thread_id: str | None = None,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    interrupt_id: str | None = None,
    action_index: int | None = None,
    policy_decision: str | None = None,
    approval_decision: str | None = None,
    reason_code: str = "",
    path_scope: str | None = None,
    result: str = "",
    duration_ms: int | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event": event,
        "conversation_id": conversation_id,
        "thread_id": thread_id,
        "agent_profile": agent_profile,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "interrupt_id": interrupt_id,
        "action_index": action_index,
        "policy_decision": policy_decision,
        "approval_decision": approval_decision,
        "reason_code": reason_code,
        "path_scope": path_scope,
        "result": result,
        "duration_ms": duration_ms,
        "error_type": error_type,
    }


def _get_audit_logger() -> logging.Logger:
    global _AUDIT_LOGGER  # noqa: PLW0603
    if _AUDIT_LOGGER is not None:
        return _AUDIT_LOGGER
    logger = logging.getLogger("security_audit.runtime")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        log_dir = Path(os.getenv("SECURITY_AUDIT_DIR") or Path.home() / "logs" / "security")
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "runtime-security-audit.jsonl",
            maxBytes=100 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    _AUDIT_LOGGER = logger
    return logger


def audit_security(**fields: Any) -> dict[str, Any]:
    record = build_audit_record(agent_profile="runtime", **fields)
    _get_audit_logger().info(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return record


class RuntimeSecurityGate(AgentMiddleware):
    def _decision(self, request: Any) -> tuple[Any, dict[str, Any], SecurityDecision, str | None]:
        tool_call = dict(request.tool_call or {})
        tool_name = str(tool_call.get("name") or "")
        raw_args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
        conversation_id = _context_value(getattr(request, "runtime", None), "conversation_id", "conversationId")
        decision = evaluate_runtime_call(
            tool_name,
            raw_args,
            conversation_id=conversation_id,
        )
        return request, tool_call, decision, conversation_id

    @staticmethod
    def _denied_message(tool_call: dict[str, Any], decision: SecurityDecision) -> ToolMessage:
        if decision.reason_code == "DELETE_USE_EXECUTE":
            content = (
                "DELETE_USE_EXECUTE: The delete tool is intentionally blocked. "
                "Do not finish the request yet. Retry the requested deletion with the execute tool, "
                "using one direct rm or rmdir command and a literal target path. Do not use $HOME, ~, "
                "wildcards, variable expansion, command substitution, pipes, redirection, or compound commands. "
                "The execute backend will decide whether approval is required."
            )
        else:
            content = f"Tool call denied by security policy: {decision.reason_code}"
        return ToolMessage(
            content=content,
            name=str(tool_call.get("name") or "unknown_tool"),
            tool_call_id=str(tool_call.get("id") or ""),
            status="error",
        )

    def wrap_tool_call(self, request: Any, handler: Any):
        request, tool_call, decision, conversation_id = self._decision(request)
        common = {
            "conversation_id": conversation_id,
            "tool_name": str(tool_call.get("name") or ""),
            "tool_call_id": str(tool_call.get("id") or ""),
            "policy_decision": decision.policy_decision,
            "reason_code": decision.reason_code,
            "path_scope": decision.path_scope,
        }
        if not decision.allowed:
            audit_security(event="tool_denied", result="denied", **common)
            return self._denied_message(tool_call, decision)
        audit_security(event="tool_allowed", result="allowed", **common)
        started = time.monotonic()
        try:
            result = handler(request)
        except Exception as exc:
            audit_security(
                event="tool_finished",
                result="error",
                duration_ms=int((time.monotonic() - started) * 1000),
                error_type=type(exc).__name__,
                **common,
            )
            raise
        audit_security(
            event="tool_finished",
            result="success",
            duration_ms=int((time.monotonic() - started) * 1000),
            **common,
        )
        return result

    async def awrap_tool_call(self, request: Any, handler: Any):
        request, tool_call, decision, conversation_id = self._decision(request)
        common = {
            "conversation_id": conversation_id,
            "tool_name": str(tool_call.get("name") or ""),
            "tool_call_id": str(tool_call.get("id") or ""),
            "policy_decision": decision.policy_decision,
            "reason_code": decision.reason_code,
            "path_scope": decision.path_scope,
        }
        if not decision.allowed:
            audit_security(event="tool_denied", result="denied", **common)
            return self._denied_message(tool_call, decision)
        audit_security(event="tool_allowed", result="allowed", **common)
        started = time.monotonic()
        try:
            result = await handler(request)
        except Exception as exc:
            audit_security(
                event="tool_finished",
                result="error",
                duration_ms=int((time.monotonic() - started) * 1000),
                error_type=type(exc).__name__,
                **common,
            )
            raise
        audit_security(
            event="tool_finished",
            result="success",
            duration_ms=int((time.monotonic() - started) * 1000),
            **common,
        )
        return result


__all__ = [
    "ALLOW",
    "DENY",
    "RUNTIME_PATH_INSTRUCTION",
    "RuntimeSecurityGate",
    "SecurityDecision",
    "audit_security",
    "build_audit_record",
    "build_runtime_backend",
    "evaluate_runtime_call",
    "filter_runtime_tools",
    "runtime_decision",
    "runtime_permissions",
]
