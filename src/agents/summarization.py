from __future__ import annotations

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain_core.language_models import BaseChatModel

DEFAULT_TRIGGER_FRACTION = 0.75
DEFAULT_TRIGGER_TOKENS = 500_000
DEFAULT_KEEP_FRACTION = 0.05


def _has_context_window(model: BaseChatModel) -> bool:
    profile = model.profile
    return (
        isinstance(profile, dict)
        and isinstance(profile.get("max_input_tokens"), int)
        and not isinstance(profile.get("max_input_tokens"), bool)
        and profile["max_input_tokens"] > 0
    )


def build_summarization_middleware(
    model: BaseChatModel,
    backend: BackendProtocol,
    config: object,
) -> SummarizationMiddleware:
    """Map the project's JSON summarization policy to DeepAgents 0.7.11."""
    if not isinstance(config, dict):
        raise ValueError("context.summarization must be an object")

    raw_trigger = config.get("trigger", {})
    if not isinstance(raw_trigger, dict):
        raise ValueError("context.summarization.trigger must be an object")

    operator = raw_trigger.get("operator", "any")
    if operator not in {"any", "all"}:
        raise ValueError("context.summarization.trigger.operator must be 'any' or 'all'")

    fraction = raw_trigger.get("fraction", DEFAULT_TRIGGER_FRACTION)
    if isinstance(fraction, bool) or not isinstance(fraction, int | float) or not 0 < float(fraction) < 1:
        raise ValueError("context.summarization.trigger.fraction must be between 0 and 1")

    tokens = raw_trigger.get("tokens", DEFAULT_TRIGGER_TOKENS)
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
        raise ValueError("context.summarization.trigger.tokens must be a positive integer")

    keep = config.get("keep", DEFAULT_KEEP_FRACTION)
    if isinstance(keep, bool) or not isinstance(keep, int | float) or not 0 < float(keep) < 1:
        raise ValueError("context.summarization.keep must be between 0 and 1")
    if float(keep) >= float(fraction):
        raise ValueError("context.summarization.keep must be smaller than trigger.fraction")

    if not _has_context_window(model):
        raise ValueError("fraction-based summarization requires model.profile.max_input_tokens")

    conditions: list[tuple[str, float | int]] = [
        ("fraction", float(fraction)),
        ("tokens", tokens),
    ]
    trigger: dict[str, float | int] | list[tuple[str, float | int]]
    if operator == "all":
        trigger = dict(conditions)
    else:
        trigger = conditions

    keep_setting = ("fraction", float(keep))
    model_metadata = dict(model.metadata) if isinstance(model.metadata, dict) else {}
    summary_model = model.model_copy(
        update={"metadata": {**model_metadata, "lc_source": "summarization"}}
    )
    return SummarizationMiddleware(
        model=summary_model,
        backend=backend,
        trigger=trigger,
        keep=keep_setting,
        trim_tokens_to_summarize=None,
        truncate_args_settings={
            "trigger": ("fraction", float(fraction)),
            "keep": keep_setting,
        },
    )


__all__ = [
    "DEFAULT_KEEP_FRACTION",
    "DEFAULT_TRIGGER_FRACTION",
    "DEFAULT_TRIGGER_TOKENS",
    "build_summarization_middleware",
]
