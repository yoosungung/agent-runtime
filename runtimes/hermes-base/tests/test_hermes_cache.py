"""Hermes agent cache tests with mock AIAgent."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_base.hermes_cache import build_hermes_agent, get_or_build_hermes_agent, hermes_instance_key
from hermes_base.profile_scope import get_active_home, profile_runtime_scope
from runtime_common.instance_cache import InstanceCache
from runtime_common.schemas import SourceMeta, UserMeta
from runtime_common.secrets import EnvSecretResolver


def test_profile_runtime_scope_sets_home(tmp_path: Path) -> None:
    home = tmp_path / "profiles" / "alice"
    home.mkdir(parents=True)
    assert get_active_home() is None
    with profile_runtime_scope(home):
        assert get_active_home() == home.resolve()
    assert get_active_home() is None


def test_build_hermes_agent_uses_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = MagicMock(return_value=object())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    cfg = {
        "hermes": {
            "soul": "hi",
            "mcp_servers": ["mcp-a"],
            "model": "openai/gpt-4o",
            "enabled_toolsets": ["web"],
        }
    }
    build_hermes_agent(cfg, EnvSecretResolver(), profile_home=tmp_path, agent_factory=factory)
    factory.assert_called_once()
    kwargs = factory.call_args.kwargs
    assert kwargs["model"] == "openai/gpt-4o"
    assert kwargs.get("provider") is None
    assert kwargs["quiet_mode"] is True
    assert kwargs["enabled_toolsets"] == ["web"]


def test_build_hermes_agent_explicit_openai_uses_bare_model_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = MagicMock(return_value=object())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    cfg = {
        "hermes": {
            "soul": "hi",
            "mcp_servers": ["mcp-a"],
            "model": "openai/gpt-4o",
        }
    }
    build_hermes_agent(cfg, EnvSecretResolver(), profile_home=tmp_path, agent_factory=factory)
    kwargs = factory.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["provider"] == "openai"


def test_build_hermes_agent_openai_compatible_passes_credentials(tmp_path: Path, monkeypatch) -> None:
    factory = MagicMock(return_value=object())
    monkeypatch.setenv("LLM_PRESET_SLM_MODE", "openai_compatible")
    monkeypatch.setenv("LLM_PRESET_SLM_MODEL_ID", "meta-llama/Llama-3")
    monkeypatch.setenv("LLM_PRESET_SLM_API_KEY", "sk-local")
    monkeypatch.setenv("LLM_PRESET_SLM_API_BASE", "http://llm.local/v1")
    cfg = {
        "hermes": {
            "soul": "hi",
            "mcp_servers": ["mcp-a"],
            "model": "preset:SLM",
        }
    }
    build_hermes_agent(cfg, EnvSecretResolver(), profile_home=tmp_path, agent_factory=factory)
    kwargs = factory.call_args.kwargs
    assert kwargs["model"] == "custom/meta-llama/Llama-3"
    assert kwargs["provider"] == "custom"
    assert kwargs["api_key"] == "sk-local"
    assert kwargs["base_url"] == "http://llm.local/v1"


def test_build_hermes_agent_uses_default_llm_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = MagicMock(return_value=object())
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "openai:gpt-5.4-nano")
    cfg = {
        "hermes": {
            "soul": "hi",
            "mcp_servers": ["mcp-a"],
        }
    }
    build_hermes_agent(cfg, EnvSecretResolver(), profile_home=tmp_path, agent_factory=factory)
    assert factory.call_args.kwargs["model"] == "gpt-5.4-nano"


def test_hermes_instance_key() -> None:
    source = SourceMeta(
        kind="agent",
        name="my-bot",
        version="v1",
        runtime_pool="agent:hermes",
        deploy_mode="hermes_general",
        config={},
    )
    assert hermes_instance_key(source) == "hermes:my-bot:v1"


@pytest.mark.asyncio()
async def test_get_or_build_caches_by_user(tmp_path: Path) -> None:
    calls = 0

    def factory(**kwargs: object) -> MagicMock:
        nonlocal calls
        calls += 1
        mock = MagicMock()
        mock.run_conversation = MagicMock(return_value={"final_response": "ok"})
        return mock

    source = SourceMeta(
        kind="agent",
        name="cached-bot",
        version="v1",
        runtime_pool="agent:hermes",
        deploy_mode="hermes_general",
        config={
            "hermes": {
                "soul": "s",
                "mcp_servers": ["x"],
            }
        },
    )
    user = UserMeta(
        principal_id="42",
        config={},
        secrets_ref=None,
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    cache = InstanceCache(max_entries=8)
    a1 = await get_or_build_hermes_agent(
        cache, source, user, EnvSecretResolver(), profile_home=tmp_path, user_id=42, agent_factory=factory
    )
    a2 = await get_or_build_hermes_agent(
        cache, source, user, EnvSecretResolver(), profile_home=tmp_path, user_id=42, agent_factory=factory
    )
    assert a1 is a2
    assert calls == 1
    await cache.clear()
