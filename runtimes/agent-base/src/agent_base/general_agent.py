"""Built-in factory for deploy_mode='general' agents (no bundle)."""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent

from agent_base.agent_tools import build_agent_delegate_tools
from agent_base.mcp_tools import build_mcp_tools
from runtime_common.config_schema import GeneralAgentSourceConfig
from runtime_common.knowledge import resolve_knowledge_bindings
from runtime_common.providers.langgraph import build_checkpointer, prepare_langgraph_llm
from runtime_common.secrets import SecretResolver
from runtime_common.vfs.composite import build_general_vfs, wiki_routes_from_bindings
from runtime_common.vfs.store import (
    AgentVfsStore,
    AsyncpgAgentVfsStore,
    AsyncpgUserVfsStore,
    UserVfsStore,
)
from runtime_common.vfs.wiki_store import AsyncpgWikiVfsStore, WikiVfsStore

_DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


def _parse_general_cfg(cfg: dict) -> GeneralAgentSourceConfig:
    raw = cfg.get("general") or {}
    if not raw.get("system_prompt"):
        raise ValueError("general agent requires config.general.system_prompt")
    if not raw.get("mcp_servers"):
        raise ValueError("general agent requires config.general.mcp_servers")
    return GeneralAgentSourceConfig.model_validate(raw)


def _wiki_routes_for_build(
    general: GeneralAgentSourceConfig,
    *,
    tenant: str | None,
    admin_backend_url: str | None,
    wiki_store: WikiVfsStore | None,
) -> dict[str, Any]:
    if not general.vfs.wiki_enabled or not general.knowledge_project_ids:
        return {}
    if not tenant or not admin_backend_url or wiki_store is None:
        return {}
    try:
        from runtime_common.pipeline_binding import fetch_project_binding

        bindings = resolve_knowledge_bindings(
            tenant,
            general.knowledge_project_ids,
            fetch_binding=lambda t, pid: fetch_project_binding(admin_backend_url, t, pid),
        )
        return wiki_routes_from_bindings(bindings, wiki_store=wiki_store, read_only=True)
    except Exception:
        return {}


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
    agent_gateway_url: str | None = None,
    agent_delegate_timeout_sec: float = 60.0,
    max_delegate_depth: int = 3,
    principal_tenant: str | None = None,
    admin_backend_url: str | None = None,
) -> Any:
    """Build a DeepAgents CompiledStateGraph for a general-tier agent."""
    general = _parse_general_cfg(cfg)
    wiki_routes: dict[str, Any] = {}
    if general.vfs.enabled:
        a_store = agent_store or (AsyncpgAgentVfsStore(vfs_pool) if vfs_pool else None)
        u_store = user_store or (AsyncpgUserVfsStore(vfs_pool) if vfs_pool else None)
        if a_store is None or u_store is None:
            raise RuntimeError("VFS store or vfs_pool required for general agent")
        wiki_store: WikiVfsStore | None = (
            AsyncpgWikiVfsStore(vfs_pool) if vfs_pool else None
        )
        wiki_routes = _wiki_routes_for_build(
            general,
            tenant=principal_tenant,
            admin_backend_url=admin_backend_url,
            wiki_store=wiki_store,
        )
        backend = build_general_vfs(
            a_store,
            u_store,
            kind=kind,
            agent_name=agent_name,
            user_id=user_id,
            wiki_routes=wiki_routes or None,
        )
    else:
        backend = None

    mcp_tool_entries = [
        {"server": t.server, "name": t.name, "description": t.description}
        for t in general.mcp_tools
    ]
    tools = build_mcp_tools(
        mcp_tool_entries,
        gateway_url=mcp_gateway_url,
        mcp_requires_knowledge=set(general.mcp_requires_knowledge),
    )
    gateway = agent_gateway_url or mcp_gateway_url
    if gateway and general.delegate_agents:
        tools.extend(
            build_agent_delegate_tools(
                general.delegate_agents,
                gateway_url=gateway,
                allow_delegation=general.allow_agent_delegation,
                max_depth=max_delegate_depth,
                delegate_timeout_sec=agent_delegate_timeout_sec,
            )
        )
    checkpointer = build_checkpointer(cfg, secrets)

    return create_deep_agent(
        model=prepare_langgraph_llm(cfg),
        tools=tools,
        system_prompt=general.system_prompt or _DEFAULT_SYSTEM_PROMPT,
        backend=backend,
        checkpointer=checkpointer,
        subagents=general.subagents,
    )
