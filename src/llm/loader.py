from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.llm.chat_openai_custom import ChatOpenAICustom
from src.llm.retry import (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_MAX_DELAY_SECONDS,
    DEFAULT_MAX_RETRIES,
    validate_retry_config,
)
from src.logger import get_logger
from src.utils.workspace import PROJECT_ROOT

MODEL_CONFIG_PATH = Path(__file__).resolve().with_name("model.json")
logger = get_logger(__name__)

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class LLMModel:
    provider: str
    name: str
    internal: bool
    base_url: str
    api_key: str
    logo: str
    description: str
    reasoning: bool
    input: tuple[str, ...]
    context_window: int | None
    max_input_tokens: int | None
    args: dict[str, Any]
    raw: dict[str, Any]

    @property
    def ref(self) -> str:
        return f"{self.provider}/{self.name}"


@dataclass(frozen=True)
class LLMProvider:
    name: str
    base_url: str
    api_key: str
    logo: str
    models: tuple[LLMModel, ...]


_UNSUPPORTED_INPUTS_BY_MODEL = {
    "qwen3.7-max": {"image"},
}
_REQUEST_MODEL_NAME_BY_DISPLAY_NAME = {
    "SCNet-MAX": "gemini-3.5-flash",
}


def _model_supports_input(model: LLMModel, input_type: str) -> bool:
    expected = input_type.strip().lower()
    if not expected:
        return False

    model_name = model.name.strip().lower()
    if expected in _UNSUPPORTED_INPUTS_BY_MODEL.get(model_name, set()):
        return False

    return expected in {item.strip().lower() for item in model.input}


class LLMRegistry:
    def __init__(self, providers: tuple[LLMProvider, ...], *, default_model_ref: str | None = None) -> None:
        if not providers:
            raise ValueError("model.json must define at least one provider")
        self.providers = providers
        self._models_by_ref = {model.ref: model for provider in providers for model in provider.models}
        self._models_by_name: dict[str, list[LLMModel]] = {}
        for model in self._models_by_ref.values():
            self._models_by_name.setdefault(model.name, []).append(model)
        self._default_model_ref = default_model_ref

    @property
    def default_model(self) -> LLMModel:
        if self._default_model_ref:
            return self._resolve_explicit(self._default_model_ref)
        return self.providers[0].models[0]

    @property
    def provider_names(self) -> list[str]:
        return [provider.name for provider in self.providers]

    @property
    def model_refs(self) -> list[str]:
        return list(self._models_by_ref)

    def _resolve_explicit(self, model_ref: str) -> LLMModel:
        selected = model_ref.strip()
        if selected in self._models_by_ref:
            return self._models_by_ref[selected]

        matches = self._models_by_name.get(selected, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            refs = ", ".join(model.ref for model in matches)
            raise ValueError(f"LLM model name '{selected}' is ambiguous, use one of: {refs}")

        raise ValueError(f"Unknown LLM model '{selected}', available models: {', '.join(self.model_refs)}")

    def resolve(self, model_ref: str | None) -> LLMModel:
        selected = (model_ref or "").strip()
        if not selected:
            return self.default_model

        return self._resolve_explicit(selected)

    def resolve_supporting_input(self, input_type: str, *, preferred_model_ref: str | None = None) -> LLMModel:
        expected = input_type.strip().lower()
        if not expected:
            raise ValueError("input_type must be a non-empty string")

        if preferred_model_ref:
            preferred_model = self.resolve(preferred_model_ref)
            if _model_supports_input(preferred_model, expected):
                return preferred_model

        for model in self._models_by_ref.values():
            if _model_supports_input(model, expected):
                return model

        raise ValueError(f"No LLM model supports input type '{input_type}'")


def _read_required_string(data: dict[str, Any], field: str, *, owner: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} field '{field}' must be a non-empty string")
    return value.strip()


def _resolve_env_placeholder(value: str, *, owner: str, field: str) -> str:
    stripped = value.strip()
    if not (stripped.startswith("${") and stripped.endswith("}")):
        return stripped

    env_name = stripped[2:-1].strip()
    if not env_name:
        raise ValueError(f"{owner} field '{field}' contains an empty environment variable placeholder")
    resolved = os.getenv(env_name, "").strip()
    if not resolved:
        raise ValueError(f"{owner} field '{field}' points to missing environment variable '{env_name}'")
    return resolved


def _read_config_string(data: dict[str, Any], field: str, *, owner: str) -> str:
    return _resolve_env_placeholder(_read_required_string(data, field, owner=owner), owner=owner, field=field)


def _read_optional_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    return value.strip() if isinstance(value, str) else ""


def _read_optional_bool(data: dict[str, Any], field: str, *, owner: str) -> bool:
    value = data.get(field, False)
    if not isinstance(value, bool):
        raise ValueError(f"{owner} field '{field}' must be a boolean")
    return value


def _normalize_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    chat_completions_suffix = "/chat/completions"
    if normalized.endswith(chat_completions_suffix):
        normalized = normalized[: -len(chat_completions_suffix)].rstrip("/")
    return normalized


def _request_model_name(model: LLMModel) -> str:
    model_name = model.name.strip()
    if model_name in _REQUEST_MODEL_NAME_BY_DISPLAY_NAME:
        return _REQUEST_MODEL_NAME_BY_DISPLAY_NAME[model_name]
    if model_name.lower().startswith("gpt-5.5-"):
        return "gpt-5.5"
    return model_name


def _default_model_ref_from_env() -> str | None:
    selected = os.getenv("UA_MODEL", "").strip()
    if not selected:
        return None

    provider_name, separator, model_name = selected.partition("/")
    selected_model_name = model_name if separator else provider_name
    display_name = next(
        (
            display_name
            for display_name, request_name in _REQUEST_MODEL_NAME_BY_DISPLAY_NAME.items()
            if selected_model_name == request_name
        ),
        None,
    )
    if display_name is None:
        return selected
    return f"{provider_name}/{display_name}" if separator else display_name


def _read_secret(data: dict[str, Any], *, owner: str) -> str:
    return _read_config_string(data, "apiKey", owner=owner)


def _read_optional_int(data: dict[str, Any], field: str, *, owner: str) -> int | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{owner} field '{field}' must be a non-negative integer")
    return value


def _read_input_types(data: dict[str, Any], *, owner: str) -> tuple[str, ...]:
    raw_input = data.get("input", [])
    if raw_input is None:
        return ()
    if not isinstance(raw_input, list) or not all(isinstance(item, str) and item.strip() for item in raw_input):
        raise ValueError(f"{owner} field 'input' must be a list of strings")
    return tuple(item.strip() for item in raw_input)


def _read_args(data: dict[str, Any], *, owner: str) -> dict[str, Any]:
    raw_args = data.get("args", {})
    if raw_args in (None, {}):
        return {}
    if not isinstance(raw_args, dict):
        raise ValueError(f"{owner} field 'args' must be an object")
    return dict(raw_args)


def _parse_provider(provider_name: str, provider_config: Any) -> LLMProvider:
    owner = f"provider '{provider_name}'"
    if not isinstance(provider_config, dict):
        raise ValueError(f"{owner} must be an object")

    base_url = _normalize_openai_base_url(_read_config_string(provider_config, "baseUrl", owner=owner))
    api_key = _read_secret(provider_config, owner=owner)
    provider_logo = _read_optional_string(provider_config, "logo")
    raw_models = provider_config.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ValueError(f"{owner} field 'models' must be a non-empty list")

    models: list[LLMModel] = []
    for index, raw_model in enumerate(raw_models):
        model_owner = f"{owner} model[{index}]"
        if not isinstance(raw_model, dict):
            raise ValueError(f"{model_owner} must be an object")
        name = _read_config_string(raw_model, "name", owner=model_owner)
        reasoning = raw_model.get("reasoning", False)
        if not isinstance(reasoning, bool):
            raise ValueError(f"{model_owner} field 'reasoning' must be a boolean")
        models.append(
            LLMModel(
                provider=provider_name,
                name=name,
                internal=_read_optional_bool(raw_model, "internal", owner=model_owner),
                base_url=base_url,
                api_key=api_key,
                logo=_read_optional_string(raw_model, "logo") or provider_logo,
                description=_read_optional_string(raw_model, "description"),
                reasoning=reasoning,
                input=_read_input_types(raw_model, owner=model_owner),
                context_window=_read_optional_int(raw_model, "contextWindow", owner=model_owner),
                max_input_tokens=_read_optional_int(raw_model, "maxInputTokens", owner=model_owner),
                args=_read_args(raw_model, owner=model_owner),
                raw=dict(raw_model),
            )
        )

    return LLMProvider(name=provider_name, base_url=base_url, api_key=api_key, logo=provider_logo, models=tuple(models))


@lru_cache(maxsize=1)
def load_llm_registry(config_path: str | Path = MODEL_CONFIG_PATH) -> LLMRegistry:
    path = Path(config_path)
    with path.open(encoding="utf-8") as file:
        raw_config = json.load(file)

    providers_config = raw_config.get("providers") if isinstance(raw_config, dict) else None
    if not isinstance(providers_config, dict) or not providers_config:
        raise ValueError("model.json field 'providers' must be a non-empty object")

    providers = tuple(_parse_provider(name, config) for name, config in providers_config.items())
    default_model_ref = _default_model_ref_from_env()
    registry = LLMRegistry(providers, default_model_ref=default_model_ref)
    logger.info(
        "Loaded LLM providers=%s models=%s default_model=%s",
        registry.provider_names,
        registry.model_refs,
        registry.default_model.ref,
    )
    return registry


def clear_llm_registry_cache() -> None:
    load_llm_registry.cache_clear()
    logger.info("Cleared LLM registry cache")


def _selected_model_ref(llm_config: dict[str, Any] | None) -> str | None:
    if not llm_config:
        return None
    model = llm_config.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return None


def resolve_model_ref(llm_config: dict[str, Any] | None = None) -> str:
    registry = load_llm_registry()
    return registry.resolve(_selected_model_ref(llm_config)).ref


def resolve_model(llm_config: dict[str, Any] | None = None) -> LLMModel:
    registry = load_llm_registry()
    return registry.resolve(_selected_model_ref(llm_config))


def resolve_model_supporting_input(input_type: str, llm_config: dict[str, Any] | None = None) -> LLMModel:
    registry = load_llm_registry()
    return registry.resolve_supporting_input(input_type, preferred_model_ref=_selected_model_ref(llm_config))


def model_supports_input(llm_config: dict[str, Any] | None, input_type: str) -> bool:
    model = resolve_model(llm_config)
    return _model_supports_input(model, input_type)


def require_model_supports_image(llm_config: dict[str, Any] | None = None) -> None:
    model = resolve_model(llm_config)
    if not _model_supports_input(model, "image"):
        raise ValueError(f"当前模型 {model.ref} 尚且不支持图片输入")


def get_default_model_ref() -> str:
    return load_llm_registry().default_model.ref


_DIRECT_CHAT_OPENAI_ARGS = {
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "max_tokens",
    "max_completion_tokens",
    "reasoning_effort",
    "reasoning",
    "verbosity",
    "seed",
    "logprobs",
    "top_logprobs",
    "logit_bias",
    "n",
}
_EXTRA_BODY_ARG_KEYS = {"enable_thinking"}
_LLM_CONFIG_METADATA_KEYS = {"model", "logo"}
_BACKEND_ONLY_LLM_CONFIG_KEYS = {
    "max_retries",
    "base_delay_seconds",
    "max_delay_seconds",
    "maxRetries",
    "baseDelaySeconds",
    "maxDelaySeconds",
}
_MODEL_ARG_GATED_KEYS = {"temperature", "top_p", "frequency_penalty"}
_THINKING_INTENSITY_ARG_KEYS = {"reasoning_effort"}
_GPT_THINKING_ARGS = {"reasoning_effort": "medium"}
_QWEN38_MAX_MODEL_NAME = "qwen3.8-max"
_QWEN38_DEFAULT_REASONING_EFFORT = "medium"
_STREAM_CHUNK_TIMEOUT_ENV = "LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S"
_DEFAULT_STREAM_CHUNK_TIMEOUT_S = 300.0


def _get_model_logo(model: LLMModel) -> str:
    return model.logo


def _omitted_request_args(model: LLMModel) -> set[str]:
    model_name = _request_model_name(model).strip().lower()
    if model_name.startswith(("gpt", "claude")):
        return {"enable_thinking", "temperature", "top_p"}
    if model_name.startswith("gemini"):
        return {"enable_thinking"}
    if model_name.startswith("glm-5.2"):
        return {"enable_thinking"}
    return set()


def _thinking_request_args(model: LLMModel, enable_thinking: Any) -> dict[str, Any]:
    model_name = _request_model_name(model).strip().lower()
    if enable_thinking is not True:
        return {}

    if model_name.startswith(("gpt", "gemini", "claude", "glm-5.2")):
        return dict(_GPT_THINKING_ARGS)
    return {}


def sanitize_llm_args_for_model(model: LLMModel, args: dict[str, Any]) -> dict[str, Any]:
    allowed_model_args = set(model.args)
    return {
        key: value
        for key, value in args.items()
        if key not in _MODEL_ARG_GATED_KEYS or key in allowed_model_args
    }


def _drop_thinking_intensity_args_if_disabled(*mappings: dict[str, Any]) -> None:
    """Drop thinking-intensity controls paired with an explicit disable flag.

    ``reasoning_effort: "none"`` is itself a disable signal used by providers
    such as DeepSeek, so keep it even when ``enable_thinking`` is false.
    """
    if not any(mapping.get("enable_thinking") is False for mapping in mappings):
        return
    for mapping in mappings:
        for key in _THINKING_INTENSITY_ARG_KEYS:
            if str(mapping.get(key, "")).strip().lower() == "none":
                continue
            mapping.pop(key, None)


def _request_llm_args_for_model(model: LLMModel, args: dict[str, Any]) -> dict[str, Any]:
    request_args = dict(args)
    nested_request_args: list[dict[str, Any]] = []
    for key in ("extra_body", "model_kwargs"):
        raw_mapping = request_args.get(key)
        if isinstance(raw_mapping, dict):
            copied_mapping = dict(raw_mapping)
            request_args[key] = copied_mapping
            nested_request_args.append(copied_mapping)
    _drop_thinking_intensity_args_if_disabled(request_args, *nested_request_args)

    enable_thinking = request_args.get("enable_thinking")
    omitted_args = _omitted_request_args(model)
    for key in omitted_args:
        request_args.pop(key, None)

    for mapping_key in ("extra_body", "model_kwargs"):
        raw_mapping = request_args.get(mapping_key)
        if not isinstance(raw_mapping, dict):
            continue
        updated_mapping = dict(raw_mapping)
        for key in omitted_args:
            updated_mapping.pop(key, None)
        if updated_mapping:
            request_args[mapping_key] = updated_mapping
        else:
            request_args.pop(mapping_key, None)
    request_args.update(_thinking_request_args(model, enable_thinking))
    return request_args


def sanitize_llm_config_with_model(llm_config: dict[str, Any]) -> bool:
    if not isinstance(llm_config, dict):
        raise ValueError("agent.json field 'llm' must be an object")

    model = load_llm_registry().resolve(_selected_model_ref(llm_config))
    metadata = {key: value for key, value in llm_config.items() if key in _LLM_CONFIG_METADATA_KEYS}
    args = {
        key: value
        for key, value in llm_config.items()
        if key not in _LLM_CONFIG_METADATA_KEYS and key not in _BACKEND_ONLY_LLM_CONFIG_KEYS
    }
    sanitized_args = sanitize_llm_args_for_model(model, args)
    updated = {**metadata, **sanitized_args}
    if llm_config == updated:
        return False
    llm_config.clear()
    llm_config.update(updated)
    return True


def sync_llm_config_with_model_args(llm_config: dict[str, Any], *, force: bool = False) -> bool:
    if not isinstance(llm_config, dict):
        raise ValueError("agent.json field 'llm' must be an object")

    model = load_llm_registry().resolve(_selected_model_ref(llm_config))
    synced: dict[str, Any] = {
        "model": model.ref,
        "logo": _get_model_logo(model),
        **{
            key: value
            for key, value in model.args.items()
            if key not in _LLM_CONFIG_METADATA_KEYS and key not in _BACKEND_ONLY_LLM_CONFIG_KEYS
        },
    }
    if llm_config == synced:
        return False
    llm_config.clear()
    llm_config.update(synced)
    return True


def _effective_llm_args(model: LLMModel, llm_config: dict[str, Any] | None) -> dict[str, Any]:
    effective = {
        key: value
        for key, value in model.args.items()
        if key not in _LLM_CONFIG_METADATA_KEYS and key not in _BACKEND_ONLY_LLM_CONFIG_KEYS
    }
    if llm_config:
        effective.update(
            sanitize_llm_args_for_model(
                model,
                {
                    key: value
                    for key, value in llm_config.items()
                    if key not in _LLM_CONFIG_METADATA_KEYS and key not in _BACKEND_ONLY_LLM_CONFIG_KEYS
                },
            )
        )
    return _request_llm_args_for_model(model, effective)


def _merge_optional_mapping(raw_value: Any, *, field_name: str) -> dict[str, Any]:
    if raw_value in (None, {}):
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"agent.json field 'llm.{field_name}' must be an object")
    return dict(raw_value)


def _apply_qwen38_reasoning_effort_fallback(
    model: LLMModel,
    kwargs: dict[str, Any],
    extra_body: dict[str, Any],
    model_kwargs: dict[str, Any],
) -> None:
    if _request_model_name(model).strip().lower() != _QWEN38_MAX_MODEL_NAME:
        return
    if extra_body.get("enable_thinking") is not True:
        return
    if any("reasoning_effort" in mapping for mapping in (kwargs, extra_body, model_kwargs)):
        return
    extra_body["reasoning_effort"] = _QWEN38_DEFAULT_REASONING_EFFORT


def _build_chat_openai_kwargs(
    model: LLMModel,
    llm_config: dict[str, Any] | None,
    *,
    include_stream_options: bool = True,
) -> dict[str, Any]:
    effective_args = _effective_llm_args(model, llm_config)
    kwargs: dict[str, Any] = {}
    extra_body = _merge_optional_mapping(effective_args.pop("extra_body", None), field_name="extra_body")
    model_kwargs = _merge_optional_mapping(effective_args.pop("model_kwargs", None), field_name="model_kwargs")
    stream_options = _merge_optional_mapping(effective_args.pop("stream_options", None), field_name="stream_options")
    if include_stream_options:
        stream_options["include_usage"] = True

    for key, value in effective_args.items():
        if key in _DIRECT_CHAT_OPENAI_ARGS:
            kwargs[key] = value
        elif key in _EXTRA_BODY_ARG_KEYS:
            extra_body[key] = value
        else:
            model_kwargs[key] = value

    _drop_thinking_intensity_args_if_disabled(kwargs, extra_body, model_kwargs)
    _apply_qwen38_reasoning_effort_fallback(model, kwargs, extra_body, model_kwargs)

    if include_stream_options:
        model_kwargs["stream_options"] = stream_options
    if extra_body:
        kwargs["extra_body"] = extra_body
    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs
    return kwargs


def _build_model_profile(model: LLMModel) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "name": model.name,
        "text_inputs": "text" in {item.strip().lower() for item in model.input},
        "image_inputs": "image" in {item.strip().lower() for item in model.input},
        "tool_calling": True,
    }
    token_limit = model.max_input_tokens or model.context_window
    if token_limit is not None:
        profile["max_input_tokens"] = token_limit
    return profile


def _build_streaming_chat_openai(llm_config: dict[str, Any] | None = None) -> ChatOpenAICustom:
    if llm_config is not None and not isinstance(llm_config, dict):
        raise ValueError("agent.json field 'llm' must be an object")

    model = load_llm_registry().resolve(_selected_model_ref(llm_config))
    kwargs = _build_chat_openai_kwargs(model, llm_config)
    kwargs["streaming"] = True
    kwargs["max_retries"] = 0
    if _STREAM_CHUNK_TIMEOUT_ENV not in os.environ:
        kwargs["stream_chunk_timeout"] = _DEFAULT_STREAM_CHUNK_TIMEOUT_S

    logger.info(
        "Selected LLM model=%s provider=%s base_url=%s reasoning=%s context_window=%s max_input_tokens=%s args=%s",
        model.ref,
        model.provider,
        model.base_url,
        model.reasoning,
        model.context_window,
        model.max_input_tokens,
        sorted(kwargs),
    )
    chat = ChatOpenAICustom(
        model=_request_model_name(model),
        base_url=model.base_url,
        api_key=model.api_key,
        profile=_build_model_profile(model),
        **kwargs,
    )
    chat.configure_retry(**_retry_config(), model_label=model.ref)
    return chat


def build_chat_openai(llm_config: dict[str, Any] | None = None) -> ChatOpenAICustom:
    model_ref = resolve_model_ref(llm_config)
    logger.info("Configured main agent model=%s with same-model retries", model_ref)
    return _build_streaming_chat_openai(llm_config)


def build_once_chat_openai(
    llm_config: dict[str, Any] | None = None,
    *,
    input_type: str | None = None,
    max_retries: int | None = None,
) -> ChatOpenAICustom:
    if llm_config is not None and not isinstance(llm_config, dict):
        raise ValueError("agent.json field 'llm' must be an object")

    registry = load_llm_registry()
    model = (
        registry.resolve_supporting_input(input_type, preferred_model_ref=_selected_model_ref(llm_config))
        if input_type is not None
        else registry.resolve(_selected_model_ref(llm_config))
    )
    kwargs = _build_chat_openai_kwargs(model, llm_config, include_stream_options=False)

    if not _request_model_name(model).strip().lower().startswith(("gpt", "claude", "gemini", "glm-5.2")):
        extra_body = kwargs.setdefault("extra_body", {})
        extra_body["enable_thinking"] = False
        model_kwargs = kwargs.get("model_kwargs")
        _drop_thinking_intensity_args_if_disabled(
            kwargs,
            extra_body,
            model_kwargs if isinstance(model_kwargs, dict) else {},
        )
    kwargs["streaming"] = False
    kwargs["stream_usage"] = False
    kwargs["disable_streaming"] = True
    retry_config = _retry_config()
    if max_retries is not None:
        retry_config["max_retries"], _, _ = validate_retry_config(
            max_retries,
            retry_config["base_delay_seconds"],
            retry_config["max_delay_seconds"],
        )
    # The custom wrapper owns retry timing; disable the SDK's independent retry loop.
    kwargs["max_retries"] = 0

    logger.info(
        "Selected non-streaming LLM model=%s provider=%s base_url=%s reasoning=%s context_window=%s max_input_tokens=%s args=%s",
        model.ref,
        model.provider,
        model.base_url,
        model.reasoning,
        model.context_window,
        model.max_input_tokens,
        sorted(kwargs),
    )
    chat = ChatOpenAICustom(
        model=_request_model_name(model),
        base_url=model.base_url,
        api_key=model.api_key,
        profile=_build_model_profile(model),
        **kwargs,
    )
    chat.configure_retry(**retry_config, model_label=model.ref)
    return chat


def _retry_config() -> dict[str, Any]:
    retries, base, maximum = validate_retry_config(
        DEFAULT_MAX_RETRIES,
        DEFAULT_BASE_DELAY_SECONDS,
        DEFAULT_MAX_DELAY_SECONDS,
    )
    return {
        "max_retries": retries,
        "base_delay_seconds": base,
        "max_delay_seconds": maximum,
    }
