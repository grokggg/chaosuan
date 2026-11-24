from src.utils.config import load_current_llm_config

UNSUPPORTED_IMAGE_MODEL_MESSAGE = "当前模型尚且不支持图片输入"


def require_current_model_supports_image() -> None:
    # Import lazily to avoid the src.llm -> src.utils.workspace -> src.utils
    # package initialization cycle.
    from src.llm import require_model_supports_image

    try:
        require_model_supports_image(load_current_llm_config())
    except ValueError as exc:
        message = str(exc)
        if "尚且不支持图片输入" in message:
            raise ValueError(UNSUPPORTED_IMAGE_MODEL_MESSAGE) from exc
        raise


__all__ = [
    "UNSUPPORTED_IMAGE_MODEL_MESSAGE",
    "load_current_llm_config",
    "require_current_model_supports_image",
]
