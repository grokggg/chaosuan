from __future__ import annotations

IMAGE_FILE_EXTENSIONS = frozenset({".bmp", ".jpe", ".jpeg", ".jpg", ".png"})
IMAGE_MIME_TYPES = {
    ".bmp": "image/bmp",
    ".jpe": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
}

__all__ = ["IMAGE_FILE_EXTENSIONS", "IMAGE_MIME_TYPES"]
