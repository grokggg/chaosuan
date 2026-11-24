from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.utils.image_constants import IMAGE_FILE_EXTENSIONS, IMAGE_MIME_TYPES

MAX_IMAGE_BASE64_BYTES = 10 * 1024 * 1024
TARGET_IMAGE_RAW_BYTES = 7 * 1024 * 1024
JPEG_QUALITY_STEPS = (90, 82, 74, 66, 58)
RESIZE_STEPS = (1.0, 0.85, 0.7, 0.55, 0.4)


@dataclass(frozen=True)
class EncodedImage:
    path: Path
    mime_type: str
    base64_data: str
    was_compressed: bool = False

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64_data}"

    @property
    def base64_size(self) -> int:
        return len(self.base64_data.encode("ascii"))

    def to_content_block(self) -> dict[str, object]:
        return {"type": "image_url", "image_url": {"url": self.data_url}}


def is_supported_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_FILE_EXTENSIONS


def encode_image_file(path: str | Path) -> EncodedImage:
    image_path = Path(path).expanduser().resolve(strict=True)
    if not image_path.is_file():
        raise ValueError(f"image path is not a file: {image_path}")

    suffix = image_path.suffix.lower()
    mime_type = IMAGE_MIME_TYPES.get(suffix)
    if not mime_type:
        supported = ", ".join(sorted(IMAGE_FILE_EXTENSIONS))
        raise ValueError(f"unsupported image format: {suffix or '<none>'}. Supported formats: {supported}")

    raw_bytes = image_path.read_bytes()
    encoded = _to_base64(raw_bytes)
    if _within_base64_limit(encoded):
        return EncodedImage(path=image_path, mime_type=mime_type, base64_data=encoded)

    compressed = _try_compress_image(image_path)
    if compressed is not None:
        compressed_mime_type, compressed_bytes = compressed
        compressed_encoded = _to_base64(compressed_bytes)
        if _within_base64_limit(compressed_encoded):
            return EncodedImage(
                path=image_path,
                mime_type=compressed_mime_type,
                base64_data=compressed_encoded,
                was_compressed=True,
            )

    raise ValueError(
        f"image base64 payload exceeds {MAX_IMAGE_BASE64_BYTES} bytes after compression attempts: {image_path}"
    )


def _to_base64(raw_bytes: bytes) -> str:
    return base64.b64encode(raw_bytes).decode("ascii")


def _within_base64_limit(encoded: str) -> bool:
    return len(encoded.encode("ascii")) <= MAX_IMAGE_BASE64_BYTES


def _try_compress_image(path: Path) -> tuple[str, bytes] | None:
    try:
        with Image.open(path) as image:
            source = image.copy()
    except Exception as exc:
        raise ValueError(f"failed to open image for compression: {path}") from exc

    has_alpha = source.mode in {"RGBA", "LA"} or ("transparency" in source.info)
    if has_alpha:
        background = Image.new("RGB", source.size, (255, 255, 255))
        background.paste(source.convert("RGBA"), mask=source.convert("RGBA").split()[-1])
        source = background
    else:
        source = source.convert("RGB")

    for resize_scale in RESIZE_STEPS:
        candidate = source
        if resize_scale < 1.0:
            width = max(1, int(source.width * resize_scale))
            height = max(1, int(source.height * resize_scale))
            candidate = source.resize((width, height))

        for quality in JPEG_QUALITY_STEPS:
            output = BytesIO()
            candidate.save(output, format="JPEG", quality=quality, optimize=True)
            raw_bytes = output.getvalue()
            if len(raw_bytes) <= TARGET_IMAGE_RAW_BYTES and _within_base64_limit(_to_base64(raw_bytes)):
                return "image/jpeg", raw_bytes

    return None
