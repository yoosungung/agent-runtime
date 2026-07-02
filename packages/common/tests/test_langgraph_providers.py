"""Tests for runtime_common.providers.langgraph."""

import os
from unittest.mock import MagicMock

import pytest

from runtime_common.providers import langgraph as lg
from runtime_common.providers import pg_infra


class _MapSecretResolver:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def resolve(self, ref: str) -> str:
        if ref not in self._values:
            raise KeyError(ref)
        return self._values[ref]


@pytest.fixture(autouse=True)
def _reset_pg_registry():
    pg_infra.reset_registry()
    yield
    pg_infra.reset_registry()


def test_build_checkpointer_default_is_postgres_and_uses_shared():
    shared = MagicMock()
    pg_infra.set_shared_checkpointer(shared)
    result = lg.build_checkpointer({}, _MapSecretResolver())
    assert result is shared


def test_build_checkpointer_none_opt_out():
    result = lg.build_checkpointer(
        {"langgraph": {"checkpointer": "none"}},
        _MapSecretResolver(),
    )
    assert result is None


def test_build_checkpointer_memory():
    pytest.importorskip("langgraph")
    result = lg.build_checkpointer(
        {"langgraph": {"checkpointer": "memory"}},
        _MapSecretResolver(),
    )
    assert result is not None


def test_build_checkpointer_postgres_requires_registry():
    with pytest.raises(RuntimeError, match="not initialized"):
        lg.build_checkpointer(
            {"langgraph": {"checkpointer": "postgres"}},
            _MapSecretResolver({"CHECKPOINTER_DSN": "postgresql://x"}),
        )


def test_resolve_model_spec_prefers_cfg_then_platform_env(monkeypatch):
    monkeypatch.delenv("DEFAULT_LLM_MODEL", raising=False)
    assert lg.resolve_model_spec({"langgraph": {"model": "openai:gpt-4o-mini"}}) == "openai:gpt-4o-mini"

    monkeypatch.setenv("DEFAULT_LLM_MODEL", "openai:gpt-5.4-nano")
    assert lg.resolve_model_spec({}) == "openai:gpt-5.4-nano"

    monkeypatch.delenv("DEFAULT_LLM_MODEL", raising=False)
    assert lg.resolve_model_spec({}) == lg.DEFAULT_LLM_MODEL_SPEC


def test_export_llm_api_keys_sets_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    lg.export_llm_api_keys({"openai_api_key": "sk-test"})
    assert os.environ["OPENAI_API_KEY"] == "sk-test"


def test_read_llm_preset_limits_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PRESET_SGLANG_GEMMA4_CONTEXT_WINDOW", "16384")
    monkeypatch.setenv("LLM_PRESET_SGLANG_GEMMA4_MAX_OUTPUT_TOKENS", "8192")

    assert lg.read_llm_preset_limits("SGLANG_GEMMA4") == (16384, 8192)


def test_read_llm_preset_limits_missing_returns_none(monkeypatch):
    monkeypatch.delenv("LLM_PRESET_MISSING_CONTEXT_WINDOW", raising=False)
    monkeypatch.delenv("LLM_PRESET_MISSING_MAX_OUTPUT_TOKENS", raising=False)

    assert lg.read_llm_preset_limits("MISSING") == (None, None)


def test_extract_preset_name():
    assert lg.extract_preset_name("preset:SGLANG_GEMMA4") == "SGLANG_GEMMA4"
    assert lg.extract_preset_name("openai:gpt-4o-mini") is None


def test_prepare_langgraph_llm_combines_export_and_resolve(monkeypatch):
    fake_model = object()
    mock_init = MagicMock(return_value=fake_model)
    monkeypatch.setattr(lg, "init_chat_model", mock_init)
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "openai:gpt-5.4-nano")

    model = lg.prepare_langgraph_llm({"anthropic_api_key": "sk-ant"})

    assert model is fake_model
    mock_init.assert_called_once_with("openai:gpt-5.4-nano", use_responses_api=False)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant"


def test_prepare_langgraph_llm_openai_spec_disables_responses_api(monkeypatch):
    fake_model = object()
    mock_init = MagicMock(return_value=fake_model)
    monkeypatch.setattr(lg, "init_chat_model", mock_init)

    model = lg.prepare_langgraph_llm({"langgraph": {"model": "openai:gpt-4o-mini"}})

    assert model is fake_model
    mock_init.assert_called_once_with("openai:gpt-4o-mini", use_responses_api=False)


def test_prepare_langgraph_llm_non_openai_returns_string_spec(monkeypatch):
    monkeypatch.delenv("DEFAULT_LLM_MODEL", raising=False)

    model = lg.prepare_langgraph_llm(
        {"langgraph": {"model": "anthropic:claude-sonnet-4-6"}},
    )

    assert model == "anthropic:claude-sonnet-4-6"


def test_resolve_model_spec_preset(monkeypatch):
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_MODE", "frontier")
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_MODEL_ID", "claude-3-5-sonnet")

    assert lg.resolve_model_spec({"langgraph": {"model": "preset:TEST_PRESET"}}) == "anthropic:claude-3-5-sonnet"


def test_resolve_model_spec_preset_openai_compatible(monkeypatch):
    monkeypatch.setenv("LLM_PRESET_TEST_COMPAT_MODE", "openai_compatible")
    monkeypatch.setenv("LLM_PRESET_TEST_COMPAT_MODEL_ID", "meta-llama/Llama-3")

    assert lg.resolve_model_spec({"langgraph": {"model": "preset:TEST_COMPAT"}}) == "openai:meta-llama/Llama-3"


def test_export_llm_api_keys_preset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_MODE", "frontier")
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_API_KEY", "sk-ant-preset-key")
    monkeypatch.setenv("LLM_PRESET_TEST_PRESET_API_BASE", "http://preset-base/v1")

    lg.export_llm_api_keys({"langgraph": {"model": "preset:TEST_PRESET"}})
    
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-preset-key"
    assert os.environ["OPENAI_API_BASE"] == "http://preset-base/v1"

