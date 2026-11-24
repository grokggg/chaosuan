"""Local shell accident prevention, NOT an OS sandbox or an approval UI.

Currently enabled only in sag-maker-template.
Policy configuration is trusted deployment configuration, not tool arguments.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import posixpath
import re
import shlex
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from deepagents.backends.local_shell import LocalShellBackend
from deepagents.backends.protocol import ExecuteResponse
from langgraph.types import interrupt

from src.backend.shell_approvals import (
    CURRENT_APPROVAL_SCOPE,
    GRAPH_APPROVAL_MODE,
    GRAPH_APPROVAL_RESUME,
    ApprovalScope,
)
from src.constants import SECURITY_PATH_POLICY
from src.utils.workspace import PROJECT_ROOT

logger = logging.getLogger(__name__)
Action = Literal["allow", "ask", "deny"]
POLICY_VERSION = 14
DELETE_COMMANDS = {"rm", "rmdir", "unlink", "del", "erase", "remove-item"}
MOVE_COMMANDS = {"mv", "move", "move-item", "ren", "rename", "rename-item"}
SHELL_SYNTAX = "\n\r;&|<>`$%!*?[]{}()\\^"
PROJECT_DIR_NAME = "project"
PROTECTED_WORKSPACE_TOP_LEVEL = {
    ".bashrc",
    ".data",
    ".venv",
    "logs",
    "vibe-coding-skills",
}
PROTECTED_WORKSPACE_EXACT = {"workspace"}
PROTECTED_WORKSPACE_PATTERNS = {
    ".permissions-*.done",
    ".workspace-permissions-*.done",
}
PROTECTED_PROJECT_NAMES = {".git", ".data"}
PROTECTED_PROJECT_TOP_LEVEL = {".create", ".vibe-coding-bootstrap.done"}
GIT_QUERY_COMMANDS = {"status", "diff", "log", "show", "rev-parse", "ls-files"}


def _configured_policy_paths(policy_key: str) -> tuple[str, ...]:
    values = SECURITY_PATH_POLICY.get(policy_key, ())
    return tuple(
        dict.fromkeys(
            str(item).strip().replace("\\", "/").rstrip("/").lower()
            for item in values
            if str(item).strip()
        )
    )


NO_ACCESS_EXACT_PATHS = frozenset(_configured_policy_paths("deny_exact_paths"))
NO_ACCESS_PATH_PREFIXES = _configured_policy_paths("deny_path_prefixes")
READ_ONLY_PATH_PREFIXES = _configured_policy_paths("read_only_path_prefixes")


class ProtectedDeletionError(ValueError):
    """The target itself is protected, not merely difficult to inspect."""


@lru_cache(maxsize=1)
def _template_protected_paths() -> tuple[frozenset[str], frozenset[str]]:
    """Load protected directory names and root files from trusted configuration."""
    manifest = Path(__file__).with_name("template_protected_paths.json")
    try:
        paths = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Cannot load protected template path list") from exc
    if not isinstance(paths, dict) or set(paths) != {"directories", "files"}:
        raise RuntimeError("Protected template path list is invalid")
    directories = paths["directories"]
    files = paths["files"]
    if (
        not isinstance(directories, list)
        or not directories
        or not isinstance(files, list)
        or not files
        or any(not isinstance(name, str) or name in {"", ".", ".."} or "/" in name or "\\" in name for name in directories)
        or any(
            not isinstance(name, str)
            or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            for name in files
        )
    ):
        raise RuntimeError("Protected template path list is invalid")
    return frozenset(directories), frozenset(files)


def _raise_walk_error(error: OSError) -> None:
    raise error


def _protected_path_reason(path: Path, workspace_root: Path, project_root: Path) -> str | None:
    """Return why a path is platform-owned, or None for user-managed paths."""
    relative = path.relative_to(workspace_root)
    if path.is_relative_to(project_root):
        if path == project_root:
            return "Deleting the project root is forbidden."
        project_relative = path.relative_to(project_root)
        if project_relative.parts and project_relative.parts[0].lower() in PROTECTED_PROJECT_TOP_LEVEL:
            return "Deleting project runtime markers is forbidden."
        if any(part.lower() in PROTECTED_PROJECT_NAMES for part in project_relative.parts):
            return "Deleting project runtime or repository metadata is forbidden."
        protected_directories, protected_files = _template_protected_paths()
        if project_relative.parts[0] in protected_directories:
            return "Deleting protected project directories or their contents is forbidden."
        relative_name = project_relative.as_posix()
        if relative_name in protected_files or any(name.startswith(relative_name + "/") for name in protected_files):
            return "Deleting protected project files or directories containing them is forbidden."
        return None

    if not relative.parts:
        return "Deletion of the workspace root is disabled."
    top_level = relative.parts[0].lower()
    if len(relative.parts) == 1 and top_level in PROTECTED_WORKSPACE_EXACT:
        return "Deleting platform-managed workspace directories is forbidden."
    if top_level in PROTECTED_WORKSPACE_TOP_LEVEL or any(
        fnmatch.fnmatchcase(top_level, pattern) for pattern in PROTECTED_WORKSPACE_PATTERNS
    ):
        return "Deleting platform-managed workspace files is forbidden."
    return None


def _git_tracked_paths(project_root: Path) -> set[str]:
    """Return repository paths tracked by Git; fail closed when a repository cannot be queried."""
    if not (project_root / ".git").exists():
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "--no-pager", "ls-files", "-z", "--cached"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Cannot inspect Git tracked files: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Cannot inspect Git tracked files: {detail or 'git ls-files failed'}")
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    }


def _contains_git_tracked_path(path: Path, project_root: Path, tracked: set[str]) -> bool:
    if not path.is_relative_to(project_root):
        return False
    relative = path.relative_to(project_root).as_posix()
    prefix = relative.rstrip("/") + "/"
    return relative in tracked or any(item.startswith(prefix) for item in tracked)


# 从 git 后面的参数中找出“真正的 Git 子命令”。
def _git_subcommand(args: list[str]) -> str | None:
    """Return the direct Git subcommand while rejecting config-based dispatch."""
    index = 0
    options_with_value = {"-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix"}
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg == "-c" or arg.startswith("-c") or arg == "--config-env" or arg.startswith("--config-env="):
            return None
        if arg in options_with_value:
            index += 2
            continue
        if any(arg.startswith(f"{option}=") for option in options_with_value if option.startswith("--")):
            index += 1
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return arg
    return args[index] if index < len(args) else None


def _shell_commands(command: str) -> list[tuple[list[str], list[str]]] | None:
    """Extract simple commands and output paths, best effort; unknown syntax passes.

    Keep quoted operators inside words. This deliberately does not interpret
    expansions, inline scripts, heredocs or the full shell grammar.
    """
    token = re.compile(r'''(?:[^\s;&|<>()'"\\]|\\[\s\S]|'[^']*'|"(?:[^"\\]|\\[\s\S])*")+|[;&|<>()]+|\n''')
    commands: list[tuple[list[str], list[str]]] = []
    words: list[str] = []
    outputs: list[str] = []
    redirect: str | None = None
    offset = 0
    for match in token.finditer(command):
        if command[offset:match.start()].strip():
            return None
        offset = match.end()
        raw = match.group()
        if raw.startswith("#"):
            # Comments and heredocs are left to the shell rather than guessed at.
            return None
        if raw[0] in ";&|()\n":
            if words or outputs:
                commands.append((words, outputs))
            words, outputs, redirect = [], [], None
        elif raw[0] in "<>":
            if "<<" in raw:
                return None
            redirect = raw
        else:
            try:
                value = shlex.split(raw, posix=True)[0]
            except (ValueError, IndexError):
                return None
            if redirect is not None:
                if ">" in redirect:
                    outputs.append(value)
                redirect = None
            else:
                words.append(value)
    if command[offset:].strip():
        return None
    if words or outputs:
        commands.append((words, outputs))
    return commands


def _write_targets(words: list[str]) -> list[str]:
    """Recognize common literal writes without requiring an executable allowlist."""
    if not words:
        return []
    name = words[0].rsplit("/", 1)[-1].lower()
    args = words[1:]
    paths = [arg for arg in args if not arg.startswith("-")]
    if name in DELETE_COMMANDS | MOVE_COMMANDS | {"touch", "mkdir", "chmod", "chown", "chgrp", "truncate", "tee"}:
        return paths
    if name in {"cp", "install", "ln"}:
        for index, arg in enumerate(args):
            if arg in {"-t", "--target-directory"}:
                return args[index + 1:index + 2]
            if arg.startswith("--target-directory="):
                return [arg.split("=", 1)[1]]
        return paths[-1:] if len(paths) >= 2 else []
    if name in {"sed", "perl"} and any(arg.startswith("-i") or arg.startswith("--in-place") for arg in args):
        return paths
    return []


def _command_mentions_path(command: str, words: list[str] | None, path: str, *, descendants: bool) -> bool:
    """Match a literal POSIX path without confusing it with a longer sibling."""
    suffix = r"(?:/[^\s'\";&|<>`]*)?" if descendants else r"/?"
    boundary = r"(?=$|[\s'\";&|<>`])"
    pattern = rf"(?<![A-Za-z0-9_.-]){re.escape(path)}{suffix}{boundary}"
    if re.search(pattern, command, re.IGNORECASE):
        return True
    for word in words or []:
        if re.search(pattern, word, re.IGNORECASE):
            return True
        candidate = word.split("=", 1)[-1].replace("\\", "/")
        if not candidate.startswith("/"):
            continue
        normalized = f"/{posixpath.normpath(candidate).lstrip('/')}".lower()
        if normalized == path or (descendants and normalized.startswith(f"{path}/")):
            return True
    return False


def _runtime_path_decision(
    command: str, words: list[str] | None, commands: list[tuple[list[str], list[str]]] | None,
) -> Decision | None:
    """Deny explicit forbidden access and recognizable writes; uncertainty passes."""
    if any(_command_mentions_path(command, words, path, descendants=False) for path in NO_ACCESS_EXACT_PATHS):
        return Decision("deny", "path_access_denied", "Direct access to this runtime directory is forbidden.")
    if any(_command_mentions_path(command, words, path, descendants=True) for path in NO_ACCESS_PATH_PREFIXES):
        return Decision("deny", "path_access_denied", "Access to this runtime path is forbidden.")
    for command_words, outputs in commands or []:
        for target in [*outputs, *_write_targets(command_words)]:
            if any(_command_mentions_path("", [target], path, descendants=True) for path in READ_ONLY_PATH_PREFIXES):
                return Decision("deny", "read_only_path", "This command explicitly writes to a read-only runtime path.")
    return None


def _policy_roots(cwd: Path) -> tuple[Path, Path]:
    """Resolve the allowed workspace and the actual application project."""
    project_root = PROJECT_ROOT.resolve()
    home = os.environ.get("HOME", "").strip()
    if home:
        home_root = Path(home).resolve()
        if cwd.is_relative_to(home_root):
            if project_root != home_root and project_root.is_relative_to(home_root):
                return home_root, project_root
            return home_root, home_root / PROJECT_DIR_NAME
    if cwd.is_relative_to(project_root):
        # Local development may keep the source checkout outside $HOME.
        return project_root, project_root
    if home:
        raise ValueError("Shell working directory is outside the configured workspace and project.")
    return cwd, cwd / PROJECT_DIR_NAME


def _user_workspace_content(path: Path, workspace_root: Path, project_root: Path) -> bool:
    workspace = workspace_root / "workspace"
    return workspace_root != project_root and path != workspace and path.is_relative_to(workspace)


def _user_home_root(workspace_root: Path) -> Path | None:
    """Recognize the deployed instance layout without trusting a command argument."""
    instance_group = workspace_root.parent
    if instance_group.name != ".vibe-coding":
        return None
    if instance_group.parent.name == ".sag":
        return instance_group.parent.parent
    return instance_group.parent


def _user_home_destination(path: Path, workspace_root: Path) -> bool:
    home_root = _user_home_root(workspace_root)
    if home_root is None or not path.is_relative_to(home_root):
        return False
    return not any(path.is_relative_to(home_root / name) for name in (".sag", ".vibe-coding"))


def _deletion_targets(words: list[str]) -> list[str]:
    targets = []
    options = True
    for arg in words[1:]:
        if options and arg == "--":
            options = False
            continue
        if options and arg.startswith("-"):
            if arg in {"--recursive", "--force", "--dir", "--verbose"} or re.fullmatch(r"-[rfRdviI]+", arg):
                continue
            raise ValueError("Unsupported deletion option; cannot determine targets safely.")
        targets.append(arg)
    if not targets:
        raise ValueError("No explicit deletion targets.")
    return targets


def _user_workspace_deletion(words: list[str], cwd: Path) -> bool:
    """Allow literal user workspace targets without an approval round trip."""
    cwd = cwd.resolve()
    workspace_root, project_root = _policy_roots(cwd)
    for target in _deletion_targets(words):
        if "~" in target:
            return False
        raw = Path(os.path.abspath(cwd / target))
        if not _user_workspace_content(raw, workspace_root, project_root):
            return False
        if any(parent.is_symlink() for parent in raw.parents if parent != workspace_root):
            return False
    return True

# 对“直接删除命令”的目标进行完整检查，并生成审批快照。
# 快照记录路径、大小等。用户审批之后真正执行前，会重新生成一次快照并比较；如果文件已经变化，审批自动失效。
def deletion_snapshot(words: list[str], cwd: Path) -> list[dict[str, Any]]:
    """Protect platform/Git-owned paths and bind approvable deletions to a snapshot."""
    targets = _deletion_targets(words)
    cwd = cwd.resolve()
    workspace_root, project_root = _policy_roots(cwd)
    tracked = _git_tracked_paths(project_root)
    snapshot = []
    for target in targets:
        if "~" in target:
            raise ValueError("Use an explicit workspace path for deletion.")
        raw = cwd / target
        path = raw.resolve()
        if path == workspace_root or not path.is_relative_to(workspace_root):
            raise ProtectedDeletionError("Deletion of the workspace root or outside it is disabled.")
        protected_reason = _protected_path_reason(path, workspace_root, project_root)
        if protected_reason is not None:
            raise ProtectedDeletionError(protected_reason)
        if _contains_git_tracked_path(path, project_root, tracked):
            raise ProtectedDeletionError("Deleting Git-tracked project files or directories containing them is forbidden.")
        if any(parent.is_symlink() for parent in (raw, *raw.parents)):
            raise ValueError("Deletion through symbolic links requires manual handling.")
        entries = [path]
        if path.is_dir():
            for directory, dirs, files in os.walk(path, followlinks=False, onerror=_raise_walk_error):
                entries.extend(Path(directory) / name for name in sorted(dirs + files))
                if len(entries) > 10000:
                    raise ValueError("Directory is too large to inspect safely; deletion is disabled.")
        for entry in sorted(entries):
            protected_reason = _protected_path_reason(entry, workspace_root, project_root)
            if protected_reason is not None:
                raise ProtectedDeletionError(protected_reason)
            if entry.is_symlink():
                raise ValueError("Directories containing symbolic links cannot be approved for deletion.")
            try:
                stat = entry.stat()
            except FileNotFoundError:
                snapshot.append({"path": str(entry), "missing": True})
                continue
            snapshot.append(
                {
                    "path": str(entry),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime_ns,
                    "ctime": stat.st_ctime_ns,
                    "inode": stat.st_ino,
                    "mode": stat.st_mode,
                }
            )
    return snapshot


def _check_move_paths(words: list[str], cwd: Path, *, git_move: bool = False) -> None:
    """Inspect literal move sources and destination before allowing a move."""
    args = words[2:] if git_move else words[1:]
    paths: list[str] = []
    options = True
    for arg in args:
        if options and arg == "--":
            options = False
            continue
        if options and arg.startswith("-"):
            if arg in {"-f", "-i", "-n", "-v", "-T", "--force", "--interactive", "--no-clobber", "--verbose", "--no-target-directory"} or re.fullmatch(r"-[finvT]+", arg):
                continue
            raise ValueError("Unsupported move option; cannot determine targets safely.")
        paths.append(arg)
    if len(paths) < 2:
        raise ValueError("Move needs explicit source and destination paths.")
    cwd = cwd.resolve()
    workspace_root, project_root = _policy_roots(cwd)
    tracked = _git_tracked_paths(project_root)
    workspace_sources = all(
        _user_workspace_content((cwd / target).resolve(), workspace_root, project_root)
        for target in paths[:-1]
    )
    for index, target in enumerate(paths):
        if "~" in target or any(char in target for char in "*?[]{}"):
            raise ValueError("Move paths must be literal workspace paths.")
        raw = cwd / target
        if any(parent.is_symlink() for parent in (raw, *raw.parents)):
            raise ValueError("Moving through symbolic links requires manual handling.")
        path = raw.resolve()
        destination = index == len(paths) - 1
        if destination and not path.is_relative_to(workspace_root) and workspace_sources:
            if _user_home_destination(path, workspace_root):
                continue
        if destination and path.is_dir() and path.is_relative_to(workspace_root):
            # A directory destination receives the source; it is not replaced.
            continue
        if path == workspace_root or not path.is_relative_to(workspace_root):
            raise ProtectedDeletionError("Moving the workspace root or outside it is disabled.")
        reason = _protected_path_reason(path, workspace_root, project_root)
        if reason is not None:
            raise ProtectedDeletionError(reason.replace("Deleting", "Moving").replace("Deletion", "Moving"))
        if _contains_git_tracked_path(path, project_root, tracked):
            raise ProtectedDeletionError("Moving Git-tracked project files or directories containing them is forbidden.")


@dataclass(frozen=True)
class Decision:
    action: Action
    rule: str
    reason: str

# CommandPolicy 只负责“判断命令是否允许”，不真正执行命令。
class CommandPolicy:
    """Prevent recognizable destructive accidents without sandboxing commands."""

    def evaluate(self, command: str, cwd: Path) -> Decision:
        if not isinstance(command, str) or not command.strip():
            return Decision("deny", "invalid_command", "Command must be a non-empty string.")
        if "\x00" in command:
            return Decision("deny", "invalid_syntax", "Command contains an invalid character.")
        has_shell_syntax = any(char in command for char in SHELL_SYNTAX)
        words: list[str] | None = None
        try:
            words = shlex.split(command, posix=True)
        except ValueError:
            pass
        commands = _shell_commands(command)
        path_decision = _runtime_path_decision(command, words, commands)
        if path_decision is not None:
            return path_decision
        if has_shell_syntax:
            # Inspect recognizable literal operations in each command. Composite
            # commands cannot use a direct-deletion approval snapshot; anything
            # not explicitly denied passes through under the relaxed policy.
            current_cwd: Path | None = cwd
            for command_words, _outputs in commands or []:
                if not command_words:
                    continue
                if command_words[0] == "cd":
                    target = command_words[1] if len(command_words) == 2 else ""
                    if not target or any(char in target for char in SHELL_SYNTAX + "~"):
                        current_cwd = None
                    elif current_cwd is not None or Path(target).is_absolute():
                        try:
                            resolved = (Path(target) if current_cwd is None else current_cwd / target).resolve()
                            current_cwd = resolved if resolved.is_dir() else None
                        except (ValueError, OSError, RuntimeError):
                            current_cwd = None
                    continue
                decision = self._evaluate_words(command_words, current_cwd)
                if decision.action == "deny":
                    return decision
            return Decision("allow", "shell_command", "No recognizable forbidden operation in shell command.")
        if words is None:
            return Decision("allow", "unparsed_command", "Command parsing is inconclusive; defer to the shell.")
        if not words:
            return Decision("deny", "invalid_command", "Command must not be empty.")
        return self._evaluate_words(words, cwd)

    def _evaluate_words(self, words: list[str], cwd: Path | None) -> Decision:
        executable, *args = words
        name = executable.rsplit("/", 1)[-1].lower()
        git_subcommand = None
        if name == "git":
            git_subcommand = _git_subcommand(args)
            if git_subcommand in {"clean", "reset", "restore", "rm"}:
                return Decision("deny", "source_rewrite", "Git operations that discard source files are disabled.")
        if name in {"sudo", "su", "doas", "shutdown", "reboot", "mkfs", "dd", "kill", "killall", "pkill"}:
            return Decision("deny", "host_operation", "Host administration and process termination are disabled.")
        if cwd is None and (name in DELETE_COMMANDS | MOVE_COMMANDS or (name == "git" and git_subcommand == "mv")):
            return Decision("allow", "unknown_cwd", "Working directory is dynamic; file targets cannot be determined.")
        if name in DELETE_COMMANDS:
            if any(char in arg for arg in args for char in SHELL_SYNTAX + "~"):
                return Decision("allow", "delete_uninspectable", "Dynamic deletion targets are left to the shell.")
            try:
                if _user_workspace_deletion(words, cwd):
                    return Decision("allow", "workspace_delete", "User workspace content can be deleted directly.")
                deletion_snapshot(words, cwd)
            except ProtectedDeletionError as exc:
                return Decision("deny", "delete_protected", str(exc))
            except (ValueError, OSError, RuntimeError) as exc:
                return Decision("allow", "delete_uninspectable", str(exc))
            return Decision("ask", "delete", "Deletion requires review.")
        if name in MOVE_COMMANDS or (name == "git" and git_subcommand == "mv"):
            if any(char in arg for arg in args for char in SHELL_SYNTAX + "~"):
                return Decision("allow", "move_uninspectable", "Dynamic move targets are left to the shell.")
            try:
                _check_move_paths(words, cwd, git_move=name == "git")
            except ProtectedDeletionError as exc:
                return Decision("deny", "move_protected", str(exc))
            except (ValueError, OSError, RuntimeError) as exc:
                return Decision("allow", "move_uninspectable", str(exc))
            return Decision("allow", "move", "Move paths were checked.")
        # Harden recognized queries; other Git flags and aliases pass through.
        if executable == "git" and args:
            if args[0] in GIT_QUERY_COMMANDS:
                if all(
                    not arg.startswith("--")
                    or arg
                    in {
                        "--short",
                        "--porcelain",
                        "--branch",
                        "--stat",
                        "--name-only",
                        "--name-status",
                        "--oneline",
                        "--cached",
                        "--staged",
                        "--",
                    }
                    for arg in args[1:]
                ):
                    return Decision("allow", "git_query", "Known Git query.")
        return Decision("allow", "ordinary_command", "No recognizable direct destructive operation.")

# 负责把 CommandPolicy 的判定真正接到执行链路和审批链路上。
class GuardedLocalShellBackend(LocalShellBackend):
    def __init__(self, *args: Any, **kwargs: Any):
        self.policy = CommandPolicy()
        super().__init__(*args, **kwargs)

    def _approval_payload(self, command: str, timeout: int | None) -> dict[str, Any]:
        cwd = Path(self.cwd).resolve()
        words = shlex.split(command)
        targets = deletion_snapshot(words, cwd) if words[0].rsplit("/", 1)[-1].lower() in DELETE_COMMANDS else []
        return {
            "command": command,
            "cwd": str(cwd),
            "timeout": timeout if timeout is not None else self._default_timeout,
            "policy_version": POLICY_VERSION,
            "graph_approval": GRAPH_APPROVAL_MODE.get(),
            "targets": targets,
        }

    def _resume_approval(self, response: Any, record_id: str, scope: ApprovalScope) -> ExecuteResponse:
        if not isinstance(response, dict) or response.get("approval_id") != record_id:
            return ExecuteResponse(output="审批回复与待执行命令不匹配，未执行。", exit_code=126, truncated=False)
        if response.get("approve") is True:
            reply = self.apply_approval_decision(approve=True, record_id=record_id, scope=scope)
            success = reply.startswith(("删除操作已完成。", "命令执行已完成。"))
        else:
            reply = scope.store.claim(scope, record_id, False)[1]
            changed_request = response.get("changed_request")
            if isinstance(changed_request, str) and changed_request:
                reply += f" 用户修改了要求：{changed_request[:2000]}。请按新要求重新检查。"
            else:
                reply += " 用户取消了本次操作；不要继续依赖该删除结果的后续步骤。"
            success = False
        return ExecuteResponse(output=reply, exit_code=0 if success else 126, truncated=False)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        resume = GRAPH_APPROVAL_RESUME.get() if GRAPH_APPROVAL_MODE.get() else None
        if resume is not None and not resume.used and command == resume.command:
            resume.used = True
            scope = CURRENT_APPROVAL_SCOPE.get()
            pending = scope.store.list_pending(scope) if scope is not None else []
            if not pending or pending[0]["id"] != resume.approval_id:
                return ExecuteResponse(output="原审批已失效，未执行命令。", exit_code=126, truncated=False)
            response = interrupt({"approval_id": resume.approval_id, "command": command, "cwd": pending[0]["cwd"]})
            return self._resume_approval(response, resume.approval_id, scope)
        decision = self.policy.evaluate(command, Path(self.cwd).resolve())
        # Do not log raw commands: they can contain credentials.
        logger.info("local_shell_policy action=%s rule=%s", decision.action, decision.rule)
        if decision.action != "allow":
            status = "APPROVAL_REQUIRED" if decision.action == "ask" else "COMMAND_DENIED"
            detail = (
                "此命令已被拒绝，不能通过回复确认来执行；不要询问用户是否确认，"
                "也不要换用其他工具绕过检查。"
            )
            if decision.rule in {"delete_protected", "move_protected"}:
                detail += (
                    "只说明拒绝原因；本轮和后续追问都不要提供或询问"
                    "任何能变相移除同一受保护内容的操作。"
                )
            scope = CURRENT_APPROVAL_SCOPE.get()
            if decision.rule in {"delete_protected", "move_protected"} and scope is not None:
                scope.store.record_protected_denial(scope)
            if decision.action == "ask":
                detail = "No chat approval context is available. Command was NOT executed."
                if scope is not None:
                    try:
                        payload = self._approval_payload(command, timeout)
                        record_id = scope.store.pending(
                            scope, payload, replace_existing=not GRAPH_APPROVAL_MODE.get()
                        )
                        detail = json.dumps(
                            {
                                "approval_id": record_id,
                                "command": command,
                                "cwd": payload["cwd"],
                                "targets": [item["path"] for item in payload["targets"]],
                                "expires_in_seconds": scope.store.ttl,
                                "instruction": "未执行。请完整展示命令、目录、目标和编号，最后只提示用户回复确认或取消，不要给出示例回复；有歧义时需明确具体操作。",
                            },
                            ensure_ascii=False,
                        )
                        if GRAPH_APPROVAL_MODE.get():
                            response = interrupt({"approval_id": record_id, "command": command, "cwd": payload["cwd"]})
                            return self._resume_approval(response, record_id, scope)
                    except (ValueError, OSError, RuntimeError) as exc:
                        status = "COMMAND_DENIED"
                        detail = f"Cannot prepare an approval safely: {exc}"
            return ExecuteResponse(
                output=f"{status} [{decision.rule}]: {decision.reason} Command was NOT executed. " + detail,
                exit_code=126,
                truncated=False,
            )
        return self._run_checked(command, decision=decision, timeout=timeout)

    def _prepare_query(self, command: str, decision: Decision) -> str:
        if decision.rule != "git_query":
            return command
        words = shlex.split(command)
        if words[0] == "git" and decision.rule == "git_query":
            subcommand = words[1]
            # Avoid query commands launching a pager, diff driver or filesystem monitor.
            arguments = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "diff.external=", subcommand]
            if subcommand in {"diff", "log", "show"}:
                arguments.extend(["--no-ext-diff", "--no-textconv"])
            arguments.extend(words[2:])
            command = subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
        return command

    def _run_checked(self, command: str, *, decision: Decision, timeout: int | None = None) -> ExecuteResponse:
        command = self._prepare_query(command, decision)
        return super().execute(command, timeout=timeout)

    def apply_approval_decision(self, *, approve: bool, record_id: str | None, scope: ApprovalScope) -> str:
        """Consume a server-validated decision; never exposed as a model tool."""
        record, message = scope.store.claim(scope, record_id, approve)
        if record is None:
            return message
        try:
            command = record["command"]
            decision = self.policy.evaluate(command, Path(self.cwd).resolve())
            if decision.action == "deny":
                message = f"COMMAND_DENIED [{decision.rule}]: {decision.reason} 未执行。"
            elif self._approval_payload(command, record["timeout"]) != {
                key: value for key, value in record.items() if key != "id"
            }:
                message = "审批目标、工作目录或策略已变化，本次审批失效，未执行。请重新提交操作。"
            else:
                try:
                    scope.store.record_execution(scope, record, status="executing")
                except Exception as exc:
                    return f"无法创建审批执行记录，命令未执行：{type(exc).__name__}: {exc}。请检查存储后重新提交。"
                logger.info("local_shell_approval executing id=%s rule=%s", record["id"], decision.rule)
                result = self._run_checked(command, decision=decision, timeout=record["timeout"])
                audit_warning = ""
                try:
                    scope.store.record_execution(
                        scope,
                        record,
                        status="completed",
                        result={"exitCode": result.exit_code, "output": result.output, "truncated": result.truncated},
                    )
                except Exception as exc:
                    logger.exception("Failed to finalize shell approval execution journal id=%s", record["id"])
                    audit_warning = f"\n警告：执行结果日志更新失败（{type(exc).__name__}: {exc}），请先检查实际状态。"
                action = "删除操作" if decision.rule == "delete" else "命令执行"
                if result.exit_code == 0:
                    message = f"{action}已完成。"
                else:
                    detail = result.output.strip()
                    if detail and detail != "<no output>":
                        message = f"{action}未成功：{detail}"
                    else:
                        message = f"{action}未成功，请检查实际状态后再决定是否重试。"
                message += audit_warning
        except Exception as exc:
            message = f"审批处理失败：{type(exc).__name__}: {exc}。该审批已消费，不会自动重试；请先检查实际状态。"
        return message

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)
