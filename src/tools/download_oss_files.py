from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any
from uuid import uuid4

import httpx
from langchain.tools import ToolRuntime, tool

from src.agents.context import AgentRuntimeContext
from src.logger import get_logger
from src.utils import ensure_conversation_workspace

DOWNLOAD_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
logger = get_logger(__name__)


def _safe_file_name(value: str) -> tuple[str | None, str | None]:
    name = str(value).strip()
    if not name:
        return None, "文件名不能为空"
    if PurePosixPath(name).name != name or PureWindowsPath(name).name != name or name in {".", ".."}:
        return None, "文件名必须是不包含目录的基础文件名"
    return name, None


async def _download_file(client: httpx.AsyncClient, url: str, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.part")
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    output.write(chunk)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _download_error(exc: Exception) -> str:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "下载超时"
    if isinstance(exc, httpx.TransportError):
        return f"网络请求失败（{type(exc).__name__}）"
    return str(exc)


@tool(
    "download_oss_files",
    description=(
        "Download one or more user-uploaded object-storage files by their exact file names into the current conversation workspace."
    ),
)
async def download_oss_files(
    file_names: Annotated[
        list[str],
        ("Exact object-storage file names to download. Multiple files may be provided."),
    ],
    runtime: ToolRuntime[AgentRuntimeContext, Any] = None,
) -> str:
    results: list[dict[str, Any]] = []
    try:
        context = runtime.context if runtime is not None else None
        conversation_id = context.conversation_id if isinstance(context, AgentRuntimeContext) else None
        if not conversation_id:
            logger.error("OSS file download rejected: missing conversation_id")
            return json.dumps(
                {
                    "results": [
                        {
                            "fileName": str(name),
                            "success": False,
                            "path": None,
                            "error": "缺少 conversationId，无法确定下载目录",
                        }
                        for name in file_names
                    ]
                },
                ensure_ascii=False,
            )

        state = runtime.state if runtime is not None else {}
        raw_oss_files = state.get("oss_files", {})
        oss_files = raw_oss_files if isinstance(raw_oss_files, dict) else {}
        workspace = ensure_conversation_workspace(conversation_id)
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            for raw_name in file_names:
                file_name, validation_error = _safe_file_name(raw_name)
                if validation_error or file_name is None:
                    results.append(
                        {"fileName": str(raw_name), "success": False, "path": None, "error": validation_error}
                    )
                    continue

                url = oss_files.get(file_name)
                if not isinstance(url, str) or not url:
                    results.append(
                        {
                            "fileName": file_name,
                            "success": False,
                            "path": None,
                            "error": "文件不在当前会话的对象存储文件列表中",
                        }
                    )
                    continue

                target = workspace / file_name
                await _download_file(client, url, target)
                results.append(
                    {
                        "fileName": file_name,
                        "success": True,
                        "path": str(target.resolve()),
                        "error": None,
                    }
                )
    except Exception as exc:
        error = _download_error(exc)
        logger.error(
            "OSS file download failed error_type=%s completed=%s total=%s",
            type(exc).__name__,
            len(results),
            len(file_names),
        )
        for raw_name in file_names[len(results) :]:
            results.append({"fileName": str(raw_name), "success": False, "path": None, "error": error})

    return json.dumps({"results": results}, ensure_ascii=False)


__all__ = ["download_oss_files"]
