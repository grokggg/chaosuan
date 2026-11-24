from __future__ import annotations

import errno
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from src.logger import get_logger
from src.skills.scanner import (
    default_skill_source,
    load_skill_registry,
    private_skill_source,
    write_skill_registry,
)
from src.utils import bool_or_false, string_or_empty

logger = get_logger(__name__)

GIT_CLONE_TIMEOUT_SECONDS = 180
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)[^/\s@]+@")
_SENSITIVE_PARAM_RE = re.compile(r"(?i)(token|key|secret|password)=([^&\s]+)")
_PERMISSION_ERRNOS = {errno.EACCES, errno.EPERM, errno.EROFS}
_PERMISSION_ERROR_MARKERS = ("permission denied", "operation not permitted", "read-only file system")
_GIT_LOCAL_WRITE_MARKERS = (
    "could not create work tree dir",
    "could not create leading directories",
    "cannot create directory",
    "unable to create file",
)


class SkillCloneTimeoutError(TimeoutError):
    def __init__(self, source: str, target_dir: Path, timeout_seconds: int) -> None:
        self.source = source
        self.target_dir = target_dir
        self.timeout_seconds = timeout_seconds
        super().__init__(f"skill clone timed out after {timeout_seconds} seconds: {target_dir.name}")


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return chain


def is_skill_permission_error(exc: BaseException) -> bool:
    """Return whether a skill operation failed because its target is not writable."""
    for item in _exception_chain(exc):
        if isinstance(item, OSError) and item.errno in _PERMISSION_ERRNOS:
            return True
        if isinstance(item, subprocess.CalledProcessError):
            output = f"{_short_process_output(item.stdout)}\n{_short_process_output(item.stderr)}".lower()
            command = item.cmd if isinstance(item.cmd, list | tuple) else []
            target = str(command[-1]).lower() if command else ""
            has_permission_marker = any(marker in output for marker in _PERMISSION_ERROR_MARKERS)
            has_local_target = bool(target and target in output)
            if has_permission_marker and (
                has_local_target or any(marker in output for marker in _GIT_LOCAL_WRITE_MARKERS)
            ):
                return True
            continue
        texts = [str(item)]
        if any(marker in text.lower() for text in texts for marker in _PERMISSION_ERROR_MARKERS):
            return True
    return False


def skill_install_error_message(exc: BaseException) -> str:
    """Build a concise, credential-safe tool error for a failed skill installation."""
    if isinstance(exc, SkillCloneTimeoutError):
        return (
            f"Cloning SCNet skill '{exc.target_dir.name}' exceeded {exc.timeout_seconds} seconds. "
            "The installation was stopped, partial files were cleaned up, and the agent was not restarted."
        )
    if is_skill_permission_error(exc):
        return "Skill installation failed because a required installation path is not writable."
    if isinstance(exc, subprocess.CalledProcessError):
        detail = _short_process_output(exc.stderr) or _short_process_output(exc.stdout)
        suffix = f": {detail}" if detail else ""
        return f"Skill repository clone failed with exit code {exc.returncode}{suffix}"
    if isinstance(exc, ValueError | OSError):
        return f"Skill installation failed: {_redact_sensitive_text(exc)}"
    return f"Skill installation failed with {type(exc).__name__}. Check the server logs for details."


def _short_process_output(value: str | bytes | None, *, limit: int = 500) -> str:
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    output = (value or "").strip()
    if len(output) > limit:
        output = f"{output[:limit]}...<truncated>"
    return _redact_sensitive_text(output)


def _redact_sensitive_text(value: Any) -> str:
    text = str(value or "")
    text = _URL_USERINFO_RE.sub(r"\1***@", text)
    return _SENSITIVE_PARAM_RE.sub(r"\1=***", text)


def _skill_name(raw_skill: dict[str, Any]) -> str:
    name = str(raw_skill.get("nameEn") or "").strip()
    if name:
        return name

    return ""


def _skill_dir(root_dir: Path, name: str) -> Path:
    resolved_root = root_dir.resolve()
    target_dir = (resolved_root / name).resolve()
    try:
        target_dir.relative_to(resolved_root)
    except ValueError:
        raise ValueError(f"invalid skill name: {name!r}") from None
    if target_dir == resolved_root:
        raise ValueError(f"invalid skill name: {name!r}")
    return target_dir


def _clone_skill(source: str, target_dir: Path) -> None:
    safe_source = _redact_sensitive_text(source)
    logger.info("Cloning skill source=%s target=%s", safe_source, target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    git_env = os.environ.copy()
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    git_env["GCM_INTERACTIVE"] = "Never"
    try:
        subprocess.run(
            ["git", "-c", "credential.interactive=false", "clone", "--depth", "1", "--no-progress", source, str(target_dir)],
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=GIT_CLONE_TIMEOUT_SECONDS,
            env=git_env,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error(
            "Clone skill timed out source=%s target=%s timeout_seconds=%s stdout=%s stderr=%s",
            safe_source,
            target_dir,
            GIT_CLONE_TIMEOUT_SECONDS,
            _short_process_output(exc.stdout),
            _short_process_output(exc.stderr),
        )
        if target_dir.exists():
            shutil.rmtree(target_dir)
        raise SkillCloneTimeoutError(source, target_dir, GIT_CLONE_TIMEOUT_SECONDS) from exc
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Clone skill failed source=%s target=%s returncode=%s stdout=%s stderr=%s",
            safe_source,
            target_dir,
            exc.returncode,
            _short_process_output(exc.stdout),
            _short_process_output(exc.stderr),
        )
        if target_dir.exists():
            shutil.rmtree(target_dir)
        raise
    _remove_cloned_git_metadata(target_dir)
    logger.info("Clone skill succeeded source=%s target=%s", safe_source, target_dir)


def _remove_cloned_git_metadata(target_dir: Path) -> None:
    git_dir = (target_dir / ".git").resolve()
    resolved_target = target_dir.resolve()
    if not git_dir.exists():
        return
    if not git_dir.is_dir() or git_dir.parent != resolved_target:
        raise ValueError(f"unexpected cloned git metadata path: {git_dir}")
    logger.info("Removing cloned skill git metadata target=%s", git_dir)
    shutil.rmtree(git_dir)


def _copy_skill(source_dir: str, target_dir: Path) -> None:
    source_path = Path(source_dir)
    if not source_path.exists() or not source_path.is_dir():
        raise ValueError(f"skill source path is not a directory: {source_dir}")
    logger.info("Copying skill source=%s target=%s", _redact_sensitive_text(source_path), target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_path, target_dir)


def _is_git_source(source: str) -> bool:
    return (
        source.startswith(("http://", "https://", "ssh://", "git@"))
        or source.endswith(".git")
        or source.startswith("git://")
    )


def _install_skill_source(source: str, target_dir: Path) -> None:
    if target_dir.exists():
        logger.info("Skill install skipped because target already exists source=%s target=%s", source, target_dir)
        return
    if _is_git_source(source):
        _clone_skill(source, target_dir)
        return
    _copy_skill(source, target_dir)


def _remove_skill_dir(name: str, *, root_dir: Path) -> None:
    target_dir = _skill_dir(root_dir, name)
    if not target_dir.exists():
        return
    if not target_dir.is_dir():
        raise ValueError(f"skill path is not a directory: {target_dir}")
    logger.info("Removing skill directory=%s", target_dir)
    shutil.rmtree(target_dir)


def _skill_source(skill: dict[str, Any]) -> str:
    return str(skill.get("httpUrlToRepo") or "").strip()


def _skill_is_builtin(skill: dict[str, Any] | None) -> bool:
    return bool(skill and bool_or_false(skill.get("builtIn")))


def _preserve_builtin_records(
    registry_by_name: dict[str, dict[str, Any]],
    desired_by_name: dict[str, dict[str, Any]],
) -> None:
    """Built-in records are immutable: keep the current record even when a caller
    tries to replace it with a repository, and keep it registered when the caller
    sends only a subset of external skills."""
    for name, current in registry_by_name.items():
        if _skill_is_builtin(current):
            desired_by_name[name] = dict(current)


def _remove_deleted_skills(
    registry_by_name: dict[str, dict[str, Any]],
    desired_by_name: dict[str, dict[str, Any]],
    *,
    root_dir: Path,
) -> None:
    deleted_names = set(registry_by_name) - set(desired_by_name)
    for name in sorted(deleted_names):
        if _skill_is_builtin(registry_by_name[name]):
            continue
        _remove_skill_dir(name, root_dir=root_dir)


def _install_added_skills(
    desired_by_name: dict[str, dict[str, Any]],
    registry_by_name: dict[str, dict[str, Any]],
    *,
    root_dir: Path,
    log_prefix: str,
) -> None:
    added_names = set(desired_by_name) - set(registry_by_name)
    for name in sorted(added_names):
        skill = desired_by_name[name]
        if _skill_is_builtin(skill):
            target_dir = _skill_dir(root_dir, name)
            if not target_dir.is_dir():
                raise ValueError(f"built-in skill directory not found: {name}")
            continue
        source = _skill_source(skill)
        if not source:
            raise ValueError(f"new skill {name} requires httpUrlToRepo")
        target_dir = _skill_dir(root_dir, name)
        logger.info("Installing %s skill name=%s source=%s target=%s", log_prefix, name, _redact_sensitive_text(source), target_dir)
        try:
            _install_skill_source(source, target_dir)
        except Exception:
            logger.exception("Install %s skill failed name=%s source=%s target=%s", log_prefix, name, _redact_sensitive_text(source), target_dir)
            raise
        logger.info("Install %s skill succeeded name=%s source=%s target=%s", log_prefix, name, _redact_sensitive_text(source), target_dir)


def _normalize_requested_skill(raw_skill: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any] | None:
    name = _skill_name(raw_skill)
    if not name:
        return None

    skill = dict(current or {})
    skill.update(raw_skill)
    skill["nameEn"] = name
    skill["nameCn"] = string_or_empty(skill.get("nameCn"))
    skill["id"] = string_or_empty(skill.get("id"))
    skill["visibility"] = string_or_empty(skill.get("visibility"))
    skill["desc"] = string_or_empty(skill.get("desc"))
    skill["httpUrlToRepo"] = string_or_empty(skill.get("httpUrlToRepo"))
    skill["tags"] = _normalize_tags(skill.get("tags"))
    skill["builtIn"] = bool_or_false(skill.get("builtIn"))
    return skill


def _normalize_tags(raw_tags: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_tags, list):
        return []

    tags: list[dict[str, Any]] = []
    for item in raw_tags:
        if not isinstance(item, dict):
            continue
        tags.append(
            {
                "category": string_or_empty(item.get("category")),
                "nameCn": string_or_empty(item.get("nameCn")),
                "nameEn": string_or_empty(item.get("nameEn")),
                "name": string_or_empty(item.get("name")),
            }
        )
    return tags


def sync_configured_skills(requested_skills: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if requested_skills is None:
        return load_skill_registry()

    root_dir = Path(default_skill_source())
    registry = load_skill_registry()
    registry_by_name = {str(skill.get("nameEn")): skill for skill in registry if skill.get("nameEn")}

    desired_by_name: dict[str, dict[str, Any]] = {}
    for raw_skill in requested_skills:
        if not isinstance(raw_skill, dict):
            continue
        skill = _normalize_requested_skill(raw_skill, registry_by_name.get(str(raw_skill.get("nameEn"))))
        if skill is not None:
            desired_by_name[str(skill["nameEn"])] = skill

    _preserve_builtin_records(registry_by_name, desired_by_name)
    _remove_deleted_skills(registry_by_name, desired_by_name, root_dir=root_dir)
    _install_added_skills(desired_by_name, registry_by_name, root_dir=root_dir, log_prefix="added")

    desired_skills = list(desired_by_name.values())
    write_skill_registry(desired_skills)
    return desired_skills


def sync_private_configured_skills(requested_skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fully synchronize writable private skills while preserving project skills."""
    project_registry = load_skill_registry()
    project_by_name = {
        str(skill.get("nameEn")): skill
        for skill in project_registry
        if skill.get("nameEn")
    }

    private_root = Path(private_skill_source()).resolve()
    private_registry_path = private_root / "skills.json"
    private_registry = load_skill_registry(private_registry_path)

    private_by_name = {
        str(skill.get("nameEn")): skill
        for skill in private_registry
        if skill.get("nameEn")
    }

    desired_private_by_name: dict[str, dict[str, Any]] = {}
    for raw_skill in requested_skills:
        if not isinstance(raw_skill, dict):
            continue
        name = _skill_name(raw_skill)
        if not name:
            continue
        current = private_by_name.get(name) or project_by_name.get(name)
        skill = _normalize_requested_skill(raw_skill, current)
        if skill is None:
            continue
        if name in private_by_name or name not in project_by_name:
            desired_private_by_name[name] = skill

    # Private built-ins are immutable and cannot disappear when the caller sends a
    # partial external-skill selection.
    _preserve_builtin_records(private_by_name, desired_private_by_name)
    _remove_deleted_skills(private_by_name, desired_private_by_name, root_dir=private_root)
    _install_added_skills(desired_private_by_name, private_by_name, root_dir=private_root, log_prefix="added private")

    desired_private_skills = list(desired_private_by_name.values())
    write_skill_registry(desired_private_skills, private_registry_path)
    return [*project_registry, *desired_private_skills]


__all__ = [
    "GIT_CLONE_TIMEOUT_SECONDS",
    "SkillCloneTimeoutError",
    "is_skill_permission_error",
    "skill_install_error_message",
    "sync_configured_skills",
    "sync_private_configured_skills",
]
