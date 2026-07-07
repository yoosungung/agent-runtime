"""Hermes AIAgent LLM wiring — platform presets + DEFAULT_LLM_MODEL."""

from __future__ import annotations

import os
from dataclasses import dataclass

from runtime_common.providers.langgraph import (
    DEFAULT_LLM_MODEL_SPEC,
    export_llm_api_keys,
    resolve_model_spec,
)

HERMES_MIN_CONTEXT_LENGTH = 65_536

_OPENAI_DEFAULT_BASES = frozenset(
    {
        "https://api.openai.com/v1",
        "http://api.openai.com/v1",
    }
)


@dataclass(frozen=True)
class HermesLlmBinding:
    """Resolved model + credentials for hermes-agent ``AIAgent`` construction."""

    model: str
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    context_length: int | None = None


def _hermes_model_spec(cfg: dict) -> str | None:
    raw = (cfg.get("hermes") or {}).get("model")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def resolve_hermes_model_spec(cfg: dict) -> str:
    """Resolve colon-style model spec for Hermes (preset / explicit / platform default)."""
    explicit = _hermes_model_spec(cfg)
    if explicit:
        shim = {"langgraph": {"model": explicit}}
        return resolve_model_spec(shim)
    platform = os.environ.get("DEFAULT_LLM_MODEL", "").strip()
    if platform:
        return platform
    return DEFAULT_LLM_MODEL_SPEC


def to_hermes_model_format(spec: str) -> str:
    """Hermes-agent expects ``provider/model_id`` (slash), not LangChain colon form."""
    if "/" in spec:
        if ":" in spec:
            provider, _, rest = spec.partition(":")
            return f"{provider}/{rest}"
        return spec
    if ":" in spec:
        provider, _, model_id = spec.partition(":")
        return f"{provider}/{model_id}"
    return spec


def _preset_prefix_from_cfg(cfg: dict, spec: str) -> str | None:
    raw = _hermes_model_spec(cfg) or ""
    if raw.startswith("preset:"):
        name = raw[len("preset:") :].strip()
        return f"LLM_PRESET_{name}" if name else None
    if ":" not in spec:
        return None
    model_id = spec.split(":", 1)[1]
    for key, val in os.environ.items():
        if key.startswith("LLM_PRESET_") and key.endswith("_MODEL_ID") and val.strip() == model_id:
            return key[: -len("_MODEL_ID")]
    return None


def _hermes_context_length(preset_prefix: str | None) -> int | None:
    if not preset_prefix:
        return None
    raw = os.environ.get(f"{preset_prefix}_CONTEXT_WINDOW", "").strip()
    if not raw:
        return None
    return max(int(raw), HERMES_MIN_CONTEXT_LENGTH)


def _is_custom_openai_base(base_url: str) -> bool:
    return base_url.rstrip("/").lower() not in {b.lower() for b in _OPENAI_DEFAULT_BASES}


def _custom_binding(
    *,
    model_id: str,
    api_key: str,
    base_url: str,
    context_length: int | None,
) -> HermesLlmBinding:
    return HermesLlmBinding(
        model=f"custom/{model_id}",
        provider="custom",
        api_key=api_key,
        base_url=base_url,
        context_length=context_length or HERMES_MIN_CONTEXT_LENGTH,
    )


def resolve_hermes_llm_binding(cfg: dict) -> HermesLlmBinding:
    """Resolve Hermes model id and explicit credentials for ``AIAgent`` init."""
    export_llm_api_keys(cfg)
    spec = resolve_hermes_model_spec(cfg)
    preset_prefix = _preset_prefix_from_cfg(cfg, spec)
    mode = os.environ.get(f"{preset_prefix}_MODE", "").strip() if preset_prefix else ""
    context_length = _hermes_context_length(preset_prefix)

    api_key = os.environ.get("OPENAI_API_KEY", "").strip() or None
    base_url = os.environ.get("OPENAI_API_BASE", "").strip() or None
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None

    raw_model = _hermes_model_spec(cfg) or ""
    model_id_from_preset = (
        os.environ.get(f"{preset_prefix}_MODEL_ID", "").strip() if preset_prefix else ""
    )
    model_id_from_spec = spec.split(":", 1)[1] if ":" in spec else spec
    model_id = model_id_from_preset or model_id_from_spec

    if mode == "openai_compatible" and api_key and base_url:
        return _custom_binding(
            model_id=model_id,
            api_key=api_key,
            base_url=base_url,
            context_length=context_length,
        )

    if (
        api_key
        and base_url
        and _is_custom_openai_base(base_url)
        and not raw_model
    ):
        return _custom_binding(
            model_id=model_id,
            api_key=api_key,
            base_url=base_url,
            context_length=context_length,
        )

    hermes_model = to_hermes_model_format(spec)
    provider, _, _ = hermes_model.partition("/")

    if provider == "openai" and api_key:
        return HermesLlmBinding(
            model=hermes_model,
            provider="openai",
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1",
            context_length=context_length,
        )
    if provider == "anthropic" and anthropic_key:
        return HermesLlmBinding(
            model=hermes_model,
            provider="anthropic",
            api_key=anthropic_key,
            context_length=context_length,
        )

    return HermesLlmBinding(model=hermes_model)


def prepare_hermes_llm(cfg: dict) -> str:
    """Bind preset API keys from env and return resolved Hermes model id."""
    return resolve_hermes_llm_binding(cfg).model
