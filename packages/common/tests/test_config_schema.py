"""Tests for runtime_common.config_schema — general agent tier."""

import pytest
from pydantic import ValidationError

from runtime_common.config_schema import (
    EmailSourceConfig,
    EmailUserConfig,
    FetchSourceConfig,
    GeneralAgentSourceConfig,
    GeneralAgentUserConfig,
    GeneralVfsConfig,
    NaverSourceConfig,
    OutlookSourceConfig,
    OutlookUserConfig,
    SearchSourceConfig,
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


def test_email_source_config_outlook_provider():
    cfg = EmailSourceConfig(provider="outlook", page_size=25)
    assert cfg.provider == "outlook"
    assert cfg.default_folder == "INBOX"


def test_outlook_source_config_requires_app_registration():
    cfg = OutlookSourceConfig(
        tenant_id="tenant-1",
        client_id="app-id",
        client_secret="secret",
        auth="oauth_refresh",
    )
    assert cfg.auth == "oauth_refresh"
    assert cfg.mailbox is None


def test_outlook_user_config_per_principal():
    cfg = OutlookUserConfig(
        mailbox="hong@company.com",
        refresh_token="rt-abc",
    )
    assert cfg.mailbox == "hong@company.com"
    assert cfg.refresh_token == "rt-abc"


def test_email_user_config_from_address():
    cfg = EmailUserConfig(from_address="hong@company.com")
    assert cfg.from_address == "hong@company.com"


def test_source_config_includes_email_sections():
    cfg = SourceConfig(
        email=EmailSourceConfig(provider="outlook"),
        outlook=OutlookSourceConfig(
            tenant_id="t",
            client_id="c",
            client_secret="s",
        ),
    )
    assert cfg.email is not None
    assert cfg.email.provider == "outlook"
    assert cfg.outlook is not None
    assert cfg.outlook.tenant_id == "t"


def test_user_config_includes_email_sections():
    cfg = UserConfig(
        email=EmailUserConfig(from_address="hong@company.com"),
        outlook=OutlookUserConfig(mailbox="hong@company.com"),
    )
    assert cfg.email is not None
    assert cfg.outlook is not None
    assert cfg.outlook.mailbox == "hong@company.com"


def test_email_source_config_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        EmailSourceConfig(provider="exchange")  # type: ignore[arg-type]


def test_search_source_config_defaults():
    cfg = SearchSourceConfig()
    assert cfg.max_display == 10
    assert cfg.default_category == "web"


def test_naver_source_config_with_secret_ref():
    cfg = NaverSourceConfig(client_id="app-id", client_secret_ref="NAVER_CLIENT_SECRET")
    assert cfg.client_id == "app-id"
    assert cfg.client_secret is None
    assert cfg.client_secret_ref == "NAVER_CLIENT_SECRET"


def test_fetch_source_config_ssrf_opt_in():
    cfg = FetchSourceConfig(allow_private_network=True, max_bytes=4096)
    assert cfg.allow_private_network is True
    assert cfg.max_bytes == 4096


def test_source_config_includes_search_sections():
    cfg = SourceConfig(
        search=SearchSourceConfig(max_display=25),
        naver=NaverSourceConfig(client_id="id", client_secret="sec"),
        fetch=FetchSourceConfig(),
    )
    assert cfg.search is not None
    assert cfg.search.max_display == 25
    assert cfg.naver is not None
    assert cfg.naver.client_id == "id"
    assert cfg.fetch is not None
