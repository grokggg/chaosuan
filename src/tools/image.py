from __future__ import annotations

import os
from typing import Annotated, Any

from langchain.tools import tool
from langchain_core.messages import HumanMessage

from src.llm import build_once_chat_openai, resolve_model_ref
from src.logger import get_logger
from src.utils import UNSUPPORTED_IMAGE_MODEL_MESSAGE
from src.utils.image_constants import IMAGE_FILE_EXTENSIONS

logger = get_logger(__name__)
MULTIMODAL_MODEL_ENV = "UA_MULTIMODAL_MODEL"
READ_IMAGE_FALLBACK_MODEL = "qwen3.7-plus"

READ_IMAGE_PROMPT = """请阅读用户指定的图片，并根据用户的问题提取图片内容。

要求：
- 如果用户提出了具体问题，只回答与问题相关的图片信息。
- 如果用户没有提出具体问题，概括图片中的主要对象、文字、结构和可能有用的细节。
- 不要编造图片中不存在的信息。
- 回答紧扣关键信息，不超过400字。
"""

READ_IMAGE_TOOL_DESCRIPTION = (
    "Read an image from a local image path and analyze it with the currently supported vision-capable model. "
    "Use this for visual analysis tasks such as image understanding, screenshots, renderings, charts, and diagrams. "
    "Supported formats: .bmp, .jpe, .jpeg, .jpg, .png. GIF files are not supported; do not call this tool for .gif files."
)


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        return "\n".join(part for part in text_parts if part)
    return str(content)


@tool("read_image", description=READ_IMAGE_TOOL_DESCRIPTION)
def read_image(
    file_path: Annotated[
        str,
        (
            "Absolute path or resolvable local path of the image file. Supported formats: "
            + ", ".join(sorted(IMAGE_FILE_EXTENSIONS))
        ),
    ],
    question: Annotated[
        str,
        ("Optional question or analysis instruction about the image. Leave empty for a general image description."),
    ] = "",
) -> str:
    """读取本地图片文件，并请求当前支持视觉输入的模型进行分析。"""

    try:
        from src.utils.image import encode_image_file

        encoded_image = encode_image_file(file_path)
    except Exception as exc:
        logger.warning("Read image failed file_path=%s error=%s", file_path, exc)
        return f"图片读取失败：{exc}"

    user_text = READ_IMAGE_PROMPT
    if question.strip():
        user_text += "\n\n用户问题：\n" + question.strip()
    user_text += f"\n\n图片路径：{encoded_image.path}"
    if encoded_image.was_compressed:
        user_text += "\n图片因大小限制已压缩后发送给模型。"

    messages = [
        HumanMessage(
            content=[
                {"type": "text", "text": user_text},
                encoded_image.to_content_block(),
            ]
        )
    ]

    response = None
    attempt_errors: list[str] = []

    primary_model = os.getenv(MULTIMODAL_MODEL_ENV, "").strip()
    if not primary_model:
        attempt_errors.append(f"{MULTIMODAL_MODEL_ENV}: environment variable is not configured")
    else:
        try:
            llm = build_once_chat_openai(
                {"model": primary_model, "enable_thinking": False, "extra_body": {}},
                input_type="image",
                max_retries=0,
            )
            response = llm.invoke(messages)
        except Exception as exc:
            error_text = str(exc).strip() or exc.__class__.__name__
            attempt_errors.append(f"{primary_model}: {error_text}")
            logger.warning(
                "Read image model call failed file_path=%s model=%s error=%s",
                encoded_image.path,
                primary_model,
                exc,
            )

    if response is None and primary_model.rsplit("/", 1)[-1] != READ_IMAGE_FALLBACK_MODEL:
        try:
            resolve_model_ref({"model": READ_IMAGE_FALLBACK_MODEL})
        except Exception as exc:
            error_text = str(exc).strip() or exc.__class__.__name__
            attempt_errors.append(f"{READ_IMAGE_FALLBACK_MODEL}: {error_text}")
            logger.warning(
                "Read image fallback model is unavailable model=%s error=%s",
                READ_IMAGE_FALLBACK_MODEL,
                exc,
            )
        else:
            try:
                llm = build_once_chat_openai(
                    {"model": READ_IMAGE_FALLBACK_MODEL, "enable_thinking": False, "extra_body": {}},
                    input_type="image",
                    max_retries=0,
                )
                response = llm.invoke(messages)
            except Exception as exc:
                error_text = str(exc).strip() or exc.__class__.__name__
                attempt_errors.append(f"{READ_IMAGE_FALLBACK_MODEL}: {error_text}")
                logger.warning(
                    "Read image model call failed file_path=%s model=%s error=%s",
                    encoded_image.path,
                    READ_IMAGE_FALLBACK_MODEL,
                    exc,
                )

    if response is None:
        if attempt_errors and all("supports input type 'image'" in error for error in attempt_errors):
            return UNSUPPORTED_IMAGE_MODEL_MESSAGE
        return f"图片分析失败：{'；'.join(attempt_errors)}"

    answer = _message_content_to_text(response.content).strip()
    logger.info("Read image file_path=%s base64_size=%s", encoded_image.path, encoded_image.base64_size)
    return answer or "模型没有返回图片分析结果。"


__all__ = ["read_image"]
