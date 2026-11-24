from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any

from langchain.tools import ToolRuntime, tool

from src.agents.context import AgentRuntimeContext
from src.utils import conversation_workspace

IMAGE_FILE_EXTENSIONS = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}


def _is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_FILE_EXTENSIONS


def _is_absolute_path(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def _preview_error(errors: list[str]) -> str:
    return json.dumps(
        {
            "status": "error",
            "errors": errors,
        },
        ensure_ascii=False,
    )


@tool(
    "preview_file",
    description=(
        "Emit a file preview event for a key result file. Use this for scientific computation "
        "markdown reports and for important final output files produced by other tasks. Do not "
        "use this for image files; use preview_assets for images. The path must be an absolute "
        "full path; relative paths are not supported."
    ),
)
async def preview_file(
    path: Annotated[
        str,
        ("Absolute full path of the generated non-image key result file to preview. Relative paths are not supported."),
    ],
    description: Annotated[
        str,
        ("Describe the purpose of the file being previewed in about 50 characters."),
    ],
) -> str:
    """Return the file metadata consumed by the preview handoff."""

    normalized_path = str(path).strip()
    errors: list[str] = []
    if not normalized_path:
        errors.append("path must not be empty")
    elif not _is_absolute_path(normalized_path):
        errors.append("path must be an absolute full path; relative paths are not supported")
    elif _is_image_path(normalized_path):
        errors.append("preview_file does not support image files; use preview_assets for images")
    if errors:
        return _preview_error(errors)

    result = {
        "filename": Path(normalized_path).name,
        "path": normalized_path,
    }
    if description and (normalized_description := str(description).strip()):
        result["description"] = normalized_description

    return json.dumps(result, ensure_ascii=False)


@tool(
    "preview_folder",
    description=(
        "Emit a working-directory preview event so the user can inspect files written in the task "
        "working directory. Use this at the end only if the task wrote or generated files in the "
        "working directory. Skip this for read-only research, investigation, or other tasks that did "
        "not write files in the working directory."
    ),
)
async def preview_folder(
    description: Annotated[
        str,
        (
            "User-facing description for the preview card. Describe the impact of opening this preview, "
            "using no more than 15 Chinese characters, for example: 查看此任务的全部文件."
        ),
    ],
    runtime: ToolRuntime[AgentRuntimeContext, Any] = None,
) -> str:
    """Return the folder metadata consumed by the preview handoff."""

    normalized_description = str(description).strip()
    errors: list[str] = []
    if not normalized_description:
        errors.append("description must not be empty")
    context = runtime.context if runtime is not None else None
    conversation_id = context.conversation_id if isinstance(context, AgentRuntimeContext) else None
    if not conversation_id:
        errors.append("conversationId is required to preview the working directory")
    if errors:
        return _preview_error(errors)

    try:
        normalized_path = str(conversation_workspace(conversation_id))
    except Exception:
        return _preview_error(["the conversation working directory could not be resolved"])

    return json.dumps(
        {
            "path": normalized_path,
            "description": normalized_description,
        },
        ensure_ascii=False,
    )


@tool(
    "preview_assets",
    description=(
        "Emit a preview event for generated image assets. Use this for scientific computation "
        "report images and for any other important image outputs that should be shown to the user. "
        "All paths must be absolute full paths; relative paths are not supported."
    ),
)
async def preview_assets(
    pathList: Annotated[
        list[str],
        ("Absolute full paths of generated image assets to preview. Relative paths are not supported."),
    ],
    description: Annotated[
        str,
        ("Describe the purpose of the image assets being previewed in about 50 characters."),
    ],
) -> str:
    """Return the image metadata consumed by the preview handoff."""

    if not isinstance(pathList, list):
        return _preview_error(["pathList must be a list"])

    normalized_paths = [str(path).strip() for path in pathList]
    normalized_paths = [path for path in normalized_paths if path]
    errors: list[str] = []
    if not normalized_paths:
        errors.append("pathList must contain at least one non-empty path")
    relative_paths = [path for path in normalized_paths if not _is_absolute_path(path)]
    if relative_paths:
        errors.append(f"all paths must be absolute full paths; relative paths are not supported: {relative_paths}")
    non_image_paths = [path for path in normalized_paths if not _is_image_path(path)]
    if non_image_paths:
        errors.append(f"preview_assets only supports image files: {non_image_paths}")
    if errors:
        return _preview_error(errors)

    result = {"pathList": normalized_paths}
    if description and (normalized_description := str(description).strip()):
        result["description"] = normalized_description

    return json.dumps(result, ensure_ascii=False)


__all__ = ["preview_file", "preview_folder", "preview_assets"]
