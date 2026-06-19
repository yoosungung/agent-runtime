"""Built-in factory for deploy_mode='general' agents (no bundle)."""

from __future__ import annotations

import os
from typing import Any

from deepagents import create_deep_agent

from agent_base.mcp_tools import build_mcp_tools
from runtime_common.config_schema import GeneralAgentSourceConfig
from runtime_common.providers.langgraph import build_checkpointer, get_model_spec
from runtime_common.secrets import SecretResolver
from runtime_common.vfs.composite import build_general_vfs
from runtime_common.vfs.store import (
    AgentVfsStore,
    AsyncpgAgentVfsStore,
    AsyncpgUserVfsStore,
    UserVfsStore,
)

_DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"
_DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


def _export_llm_keys(cfg: dict) -> None:
    for cfg_key, env_key in (
        ("anthropic_api_key", "ANTHROPIC_API_KEY"),
        ("openai_api_key", "OPENAI_API_KEY"),
        ("google_api_key", "GOOGLE_API_KEY"),
    ):
        if val := cfg.get(cfg_key):
            os.environ[env_key] = val


def _parse_general_cfg(cfg: dict) -> GeneralAgentSourceConfig:
    raw = cfg.get("general") or {}
    if not raw.get("system_prompt"):
        raise ValueError("general agent requires config.general.system_prompt")
    if not raw.get("mcp_servers"):
        raise ValueError("general agent requires config.general.mcp_servers")
    return GeneralAgentSourceConfig.model_validate(raw)


def build_general_agent(
    cfg: dict,
    secrets: SecretResolver,
    *,
    kind: str,
    agent_name: str,
    user_id: int,
    agent_store: AgentVfsStore | None = None,
    user_store: UserVfsStore | None = None,
    vfs_pool: Any | None = None,
    mcp_gateway_url: str | None = None,
) -> Any:
    """Build a DeepAgents CompiledStateGraph for a general-tier agent."""
    general = _parse_general_cfg(cfg)
    if not general.vfs.enabled:
        backend = None
    else:
        a_store = agent_store or (AsyncpgAgentVfsStore(vfs_pool) if vfs_pool else None)
        u_store = user_store or (AsyncpgUserVfsStore(vfs_pool) if vfs_pool else None)
        if a_store is None or u_store is None:
            raise RuntimeError("VFS store or vfs_pool required for general agent")
        backend = build_general_vfs(
            a_store,
            u_store,
            kind=kind,
            agent_name=agent_name,
            user_id=user_id,
        )

    _export_llm_keys(cfg)

    mcp_tool_entries = [
        {"server": t.server, "name": t.name, "description": t.description}
        for t in general.mcp_tools
    ]
    tools = build_mcp_tools(mcp_tool_entries, gateway_url=mcp_gateway_url)
    checkpointer = build_checkpointer(cfg, secrets)

    return create_deep_agent(
        model=get_model_spec(cfg) or _DEFAULT_MODEL,
        tools=tools,
        system_prompt=general.system_prompt or _DEFAULT_SYSTEM_PROMPT,
        backend=backend,
        checkpointer=checkpointer,
        subagents=general.subagents,
    )
