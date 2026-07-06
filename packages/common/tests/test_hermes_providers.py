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
    assert model == "openai/meta-llama/Llama-3"
    assert os.environ["OPENAI_API_KEY"] == "sk-preset"
    assert os.environ["OPENAI_API_BASE"] == "http://llm.local/v1"


def test_export_llm_api_keys_reads_hermes_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRESET_HERMES_PRESET_MODE", "frontier")
    monkeypatch.setenv("LLM_PRESET_HERMES_PRESET_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_PRESET_HERMES_PRESET_API_KEY", "sk-ant")
    export_llm_api_keys({"hermes": {"model": "preset:HERMES_PRESET"}})
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant"
