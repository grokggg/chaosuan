from importlib import import_module

from src.utils.config import (
    AGENT_CONFIG_PATH,
    PROMPT_PATH,
    load_agent_config,
    load_current_llm_config,
    load_json_file,
    resolve_agent_config_path,
    write_agent_config,
    write_json_file,
)
from src.utils.model import (
    UNSUPPORTED_IMAGE_MODEL_MESSAGE,
    require_current_model_supports_image,
)
from src.utils.streaming import CUSTOM_AI_MESSAGE_DELTA, log_ai_message, log_ai_message_stream
from src.utils.strings import bool_or_false, dict_string, string_or_empty
from src.utils.usage import (
    add_usage,
    extract_response_usage,
    first_int,
    int_or_none,
    log_usage,
    normalize_usage,
    text_tokens_from_usage,
)
from src.utils.workspace import (
    PROJECT_ROOT,
    conversation_workspace,
    ensure_conversation_workspace,
    ensure_workspace_root,
    validate_conversation_id,
    validate_user_id,
)

__all__ = [
    "AGENT_CONFIG_PATH",
    "IMAGE_FILE_EXTENSIONS",
    "MAX_IMAGE_BASE64_BYTES",
    "PROJECT_ROOT",
    "PROMPT_PATH",
    "TARGET_IMAGE_RAW_BYTES",
    "EncodedImage",
    "UNSUPPORTED_IMAGE_MODEL_MESSAGE",
    "conversation_workspace",
    "CUSTOM_AI_MESSAGE_DELTA",
    "add_usage",
    "bool_or_false",
    "dict_string",
    "encode_image_file",
    "ensure_conversation_workspace",
    "ensure_workspace_root",
    "extract_response_usage",
    "first_int",
    "int_or_none",
    "is_supported_image_path",
    "load_current_llm_config",
    "load_agent_config",
    "load_json_file",
    "log_ai_message",
    "log_ai_message_stream",
    "log_usage",
    "normalize_usage",
    "resolve_agent_config_path",
    "require_current_model_supports_image",
    "string_or_empty",
    "text_tokens_from_usage",
    "validate_conversation_id",
    "validate_user_id",
    "write_agent_config",
    "write_json_file",
]

_IMAGE_EXPORTS = frozenset(
    {
        "IMAGE_FILE_EXTENSIONS",
        "MAX_IMAGE_BASE64_BYTES",
        "TARGET_IMAGE_RAW_BYTES",
        "EncodedImage",
        "encode_image_file",
        "is_supported_image_path",
    }
)


def __getattr__(name: str) -> object:
    if name not in _IMAGE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    image_module = import_module("src.utils.image")
    value = getattr(image_module, name)
    globals()[name] = value
    return value
