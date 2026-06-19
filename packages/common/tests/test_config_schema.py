"""Tests for runtime_common.config_schema — general agent tier."""

import pytest
from pydantic import ValidationError

from runtime_common.config_schema import (
    GeneralAgentSourceConfig,
    GeneralAgentUserConfig,
    GeneralVfsConfig,
    SourceConfig,
    UserConfig,
)


def test_general_agent_source_config_minimal():
    cfg = GeneralAgentSourceConfig(
        system_prompt="You are helpful.",
        mcp_servers=["search-server"],
    )
    assert cfg.system_prompt == "You are helpful."
    assert cfg.mcp_servers == ["search-server"]
    assert cfg.vfs.enabled is True
    assert cfg.subagents is None


def test_general_agent_source_config_with_mcp_tools_cache():
    cfg = GeneralAgentSourceConfig(
        system_prompt="Research assistant.",
        mcp_servers=["search-server", "utility-server"],
        mcp_tools=[
            {"server": "search-server", "name": "naver_search", "description": "Search"},
        ],
    )
    assert len(cfg.mcp_tools) == 1
    assert cfg.mcp_tools[0].name == "naver_search"


def test_general_agent_source_config_requires_system_prompt():
    with pytest.raises(ValidationError):
        GeneralAgentSourceConfig(mcp_servers=["x"])


def test_general_agent_source_config_rejects_empty_mcp_servers():
    with pytest.raises(ValidationError):
        GeneralAgentSourceConfig(system_prompt="Hi", mcp_servers=[])


def test_general_vfs_config_disabled():
    cfg = GeneralVfsConfig(enabled=False)
    assert cfg.enabled is False


def test_general_agent_user_config_overrides():
    cfg = GeneralAgentUserConfig(
        system_prompt="Be formal.",
        langgraph={"model": "anthropic:claude-opus-4-7"},
    )
    assert cfg.system_prompt == "Be formal."
    assert cfg.langgraph is not None
    assert cfg.langgraph.model == "anthropic:claude-opus-4-7"


def test_source_config_includes_general_section():
    cfg = SourceConfig(
        general=GeneralAgentSourceConfig(
            system_prompt="Hi",
            mcp_servers=["s"],
        )
    )
    assert cfg.general.system_prompt == "Hi"


def test_user_config_includes_general_section():
    cfg = UserConfig(general=GeneralAgentUserConfig(system_prompt="Override"))
    assert cfg.general is not None
    assert cfg.general.system_prompt == "Override"
