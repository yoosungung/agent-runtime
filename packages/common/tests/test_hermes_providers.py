"""Tests for Hermes LLM preset wiring."""

from __future__ import annotations

import os

import pytest

from runtime_common.providers import hermes as hp
from runtime_common.providers.langgraph import export_llm_api_keys


def test_resolve_hermes_model_spec_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_MODE", "frontier")
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_MODEL_ID", "gpt-4o-mini")
    cfg = {"hermes": {"model": "preset:GPT_MINI"}}
    assert hp.resolve_hermes_model_spec(cfg) == "openai:gpt-4o-mini"


def test_resolve_hermes_model_spec_falls_back_to_default_llm_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEFAULT_LLM_MODEL", raising=False)
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "anthropic:claude-sonnet-4-6")
    assert hp.resolve_hermes_model_spec({"hermes": {"model": ""}}) == "anthropic:claude-sonnet-4-6"
    assert hp.resolve_hermes_model_spec({"hermes": {}}) == "anthropic:claude-sonnet-4-6"


def test_to_hermes_model_format_converts_colon_spec() -> None:
    assert hp.to_hermes_model_format("openai:gpt-4o") == "openai/gpt-4o"
    assert hp.to_hermes_model_format("openai/gpt-4o") == "openai/gpt-4o"


def test_prepare_hermes_llm_exports_preset_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_MODE", "openai_compatible")
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_MODEL_ID", "meta-llama/Llama-3")
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_API_KEY", "sk-preset")
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_API_BASE", "http://llm.local/v1")
    cfg = {"hermes": {"model": "preset:TEST_PRESET"}}
    model = hp.prepare_hermes_llm(cfg)
    assert model == "custom/meta-llama/Llama-3"
    assert os.environ["OPENAI_API_KEY"] == "sk-preset"
    assert os.environ["OPENAI_API_BASE"] == "http://llm.local/v1"


def test_export_llm_api_keys_reads_hermes_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRESET_HERMES_PRESET_MODE", "frontier")
    monkeypatch.setenv("LLM_PRESET_HERMES_PRESET_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_PRESET_HERMES_PRESET_API_KEY", "sk-ant")
    export_llm_api_keys({"hermes": {"model": "preset:HERMES_PRESET"}})
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant"


def test_resolve_hermes_llm_binding_openai_compatible_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PRESET_GEMMA_MODE", "openai_compatible")
    monkeypatch.setenv("LLM_PRESET_GEMMA_MODEL_ID", "meta-llama/Llama-3")
    monkeypatch.setenv("LLM_PRESET_GEMMA_CONTEXT_WINDOW", "16000")
    monkeypatch.setenv("LLM_PRESET_GEMMA_API_KEY", "sk-local")
    monkeypatch.setenv("LLM_PRESET_GEMMA_API_BASE", "http://sglang.local/v1")
    binding = hp.resolve_hermes_llm_binding({"hermes": {"model": "preset:GEMMA"}})
    assert binding.model == "custom/meta-llama/Llama-3"
    assert binding.provider == "custom"
    assert binding.api_key == "sk-local"
    assert binding.base_url == "http://sglang.local/v1"
    assert binding.context_length == hp.HERMES_MIN_CONTEXT_LENGTH


def test_resolve_hermes_llm_binding_platform_default_custom_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "openai:meta-llama/Llama-3")
    monkeypatch.setenv("LLM_PRESET_GEMMA_MODEL_ID", "meta-llama/Llama-3")
    monkeypatch.setenv("LLM_PRESET_GEMMA_CONTEXT_WINDOW", "16000")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv("OPENAI_API_BASE", "http://sglang.local/v1")
    binding = hp.resolve_hermes_llm_binding({"hermes": {"model": ""}})
    assert binding.provider == "custom"
    assert binding.model == "custom/meta-llama/Llama-3"
    assert binding.context_length == hp.HERMES_MIN_CONTEXT_LENGTH


def test_resolve_hermes_llm_binding_frontier_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_MODE", "frontier")
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_MODEL_ID", "gpt-4o-mini")
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_API_KEY", "sk-openai")
    binding = hp.resolve_hermes_llm_binding({"hermes": {"model": "preset:GPT_MINI"}})
    assert binding.model == "openai/gpt-4o-mini"
    assert binding.provider == "openai"
    assert binding.api_key == "sk-openai"
    assert binding.base_url == "https://api.openai.com/v1"


def test_resolve_hermes_llm_binding_frontier_ignores_global_openai_api_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Frontier preset must not inherit pool-wide OPENAI_API_BASE from default self-hosted preset."""
    monkeypatch.setenv("OPENAI_API_BASE", "http://sglang-gemma4-12b.llm-serving.svc.cluster.local:30000/v1")
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_MODE", "frontier")
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_MODEL_ID", "gpt-5.4-mini")
    monkeypatch.setenv("LLM_PRESET_GPT_MINI_API_KEY", "sk-openai")
    binding = hp.resolve_hermes_llm_binding({"hermes": {"model": "preset:GPT_MINI"}})
    assert binding.model == "openai/gpt-5.4-mini"
    assert binding.provider == "openai"
    assert binding.base_url == "https://api.openai.com/v1"
