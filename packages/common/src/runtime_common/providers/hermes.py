"""Hermes AIAgent LLM wiring — platform presets + DEFAULT_LLM_MODEL."""

from __future__ import annotations

import os

from runtime_common.providers.langgraph import (
    DEFAULT_LLM_MODEL_SPEC,
    export_llm_api_keys,
    resolve_model_spec,
)


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


def prepare_hermes_llm(cfg: dict) -> str:
    """Bind preset API keys from env and return resolved Hermes model id."""
    export_llm_api_keys(cfg)
    return to_hermes_model_format(resolve_hermes_model_spec(cfg))
