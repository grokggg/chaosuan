from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_APP_LOGGER_NAME = "user_agent"
_DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] conversation_id=%(conversation_id)s - %(message)s"
_DEFAULT_LOG_MAX_BYTES = 100 * 1024 * 1024
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_CONVERSATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "conversation_id",
    default=None,
)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.conversation_id = _CONVERSATION_ID.get() or "-"
        return True


class UTF8ConsoleHandler(logging.StreamHandler):
    def __init__(self) -> None:
        if sys.platform.startswith("win") and hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
            except Exception:
                pass
        super().__init__(sys.stdout)


class ShanghaiFormatter(logging.Formatter):
    def converter(self, timestamp: float) -> Any:
        return datetime.fromtimestamp(timestamp, _SHANGHAI_TZ).timetuple()


class DailySizeCappedFileHandler(logging.Handler):
    terminator = "\n"

    def __init__(
        self,
        *,
        log_dir: Path,
        file_prefix: str,
        max_total_bytes: int,
        timezone: ZoneInfo,
    ) -> None:
        super().__init__()
        self.log_dir = log_dir
        self.file_prefix = file_prefix
        self.max_total_bytes = max(1, max_total_bytes)
        self.timezone = timezone
        self.stream = None
        self._current_path: Path | None = None
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self._open_for_record(record)
            if self.stream is None:
                return
            self.stream.write(message + self.terminator)
            self.flush()
            self._enforce_size_limit()
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        if self.stream is not None:
            self.stream.flush()

    def close(self) -> None:
        self._close_stream()
        super().close()

    def _open_for_record(self, record: logging.LogRecord) -> None:
        record_date = datetime.fromtimestamp(record.created, self.timezone).strftime("%Y-%m-%d")
        target_path = self.log_dir / f"{self.file_prefix}-{record_date}.log"
        if self._current_path == target_path and self.stream is not None:
            return

        self._close_stream()
        self._current_path = target_path
        self.stream = target_path.open("a", encoding="utf-8")

    def _close_stream(self) -> None:
        if self.stream is None:
            return
        try:
            self.stream.close()
        finally:
            self.stream = None

    def _iter_log_files(self) -> list[tuple[Path, int, int]]:
        files: list[tuple[Path, int, int]] = []
        for path in self.log_dir.glob(f"{self.file_prefix}-*.log"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append((path, stat.st_size, stat.st_mtime_ns))
        return sorted(files, key=lambda item: (item[0].name, item[2]))

    def _enforce_size_limit(self) -> None:
        files = self._iter_log_files()
        total_size = sum(size for _, size, _ in files)
        if total_size <= self.max_total_bytes:
            return

        while total_size > self.max_total_bytes and len(files) > 1:
            delete_index = self._oldest_inactive_index(files)
            if delete_index is None:
                break

            path, size, _ = files.pop(delete_index)
            try:
                path.unlink()
            except OSError:
                continue
            total_size -= size

        if total_size <= self.max_total_bytes:
            return

        files = self._iter_log_files()
        if not files:
            return
        path, size, _ = files[0]
        target_size = max(0, size - (total_size - self.max_total_bytes))
        self._trim_file_head(path, target_size)

    def _oldest_inactive_index(self, files: list[tuple[Path, int, int]]) -> int | None:
        if self._current_path is None:
            return 0
        for index, (path, _, _) in enumerate(files):
            if path != self._current_path:
                return index
        return None

    def _trim_file_head(self, path: Path, target_size: int) -> None:
        if target_size <= 0:
            tail = b""
        else:
            try:
                size = path.stat().st_size
            except OSError:
                return
            if size <= target_size:
                return
            with path.open("rb") as file:
                file.seek(size - target_size)
                tail = file.read()
            newline_index = tail.find(b"\n")
            if newline_index >= 0 and newline_index + 1 < len(tail):
                tail = tail[newline_index + 1 :]

        was_current = path == self._current_path
        if was_current:
            self._close_stream()
        try:
            with path.open("wb") as file:
                file.write(tail)
        finally:
            if was_current:
                self.stream = path.open("a", encoding="utf-8")


def _resolve_log_level(level: str | int | None = None) -> int:
    if isinstance(level, int):
        return level
    raw_level = (level or os.getenv("LOG_LEVEL") or os.getenv("log_level") or "INFO").upper()
    return getattr(logging, raw_level, logging.INFO)


def _build_formatter() -> logging.Formatter:
    return ShanghaiFormatter(
        fmt=os.getenv("LOG_FORMAT", _DEFAULT_FORMAT),
        datefmt=os.getenv("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S"),
    )


def _resolve_max_log_bytes() -> int:
    raw_value = os.getenv("LOG_MAX_BYTES") or os.getenv("log_max_bytes")
    if not raw_value:
        return _DEFAULT_LOG_MAX_BYTES
    try:
        return int(raw_value)
    except ValueError:
        return _DEFAULT_LOG_MAX_BYTES


def _build_file_handler(formatter: logging.Formatter) -> logging.Handler:
    log_dir = Path(os.getenv("LOG_DIR") or os.getenv("log_path") or Path.home() / "logs")
    file_prefix = os.getenv("LOG_FILE_PREFIX") or os.getenv("log_file_prefix") or _APP_LOGGER_NAME
    handler = DailySizeCappedFileHandler(
        log_dir=log_dir,
        file_prefix=file_prefix,
        max_total_bytes=_resolve_max_log_bytes(),
        timezone=_SHANGHAI_TZ,
    )
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter())
    return handler


def setup_logging(
    *,
    level: str | int | None = None,
    logger_name: str = _APP_LOGGER_NAME,
    include_console: bool = True,
    include_file: bool | None = None,
    force: bool = False,
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    if logger.handlers and not force:
        logger.setLevel(_resolve_log_level(level))
        return logger

    formatter = _build_formatter()
    handlers: list[logging.Handler] = []

    if include_console:
        console_handler = UTF8ConsoleHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(ContextFilter())
        handlers.append(console_handler)

    if include_file is not False:
        handlers.append(_build_file_handler(formatter))

    logger.handlers.clear()
    for handler in handlers:
        logger.addHandler(handler)

    logger.setLevel(_resolve_log_level(level))
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    root_logger = setup_logging()
    if not name:
        return root_logger
    return root_logger.getChild(name)


@contextlib.contextmanager
def log_context(
    *,
    conversation_id: str | None = None,
) -> Iterator[None]:
    tokens: list[tuple[contextvars.ContextVar[str | None], Any]] = []
    try:
        if conversation_id is not None:
            tokens.append((_CONVERSATION_ID, _CONVERSATION_ID.set(conversation_id)))
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


logger = setup_logging()


__all__ = [
    "ContextFilter",
    "DailySizeCappedFileHandler",
    "UTF8ConsoleHandler",
    "get_logger",
    "log_context",
    "logger",
    "setup_logging",
]
