"""Built-in factory for deploy_mode='general' agents (no bundle)."""

from __future__ import annotations

import os
from typing import Any

from deepagents import create_deep_agent

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
    path_graph_dsn: str | None,
    wiki_s3_bucket: str | None,
) -> dict[str, Any]:
    if not general.vfs.wiki_enabled or not general.knowledge_project_ids:
        return {}
    if not tenant or not path_graph_dsn or not wiki_s3_bucket:
        return {}
    try:
        from path_graph.admin.lifecycle import api_get_binding
        import boto3

        bindings = resolve_knowledge_bindings(
            tenant,
            general.knowledge_project_ids,
            fetch_binding=api_get_binding,
        )
        client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("WIKI_S3_ENDPOINT_URL")
            or os.environ.get("S3_ENDPOINT_URL")
            or None,
            aws_access_key_id=os.environ.get("WIKI_S3_ACCESS_KEY_ID")
            or os.environ.get("S3_ACCESS_KEY_ID")
            or None,
            aws_secret_access_key=os.environ.get("WIKI_S3_SECRET_ACCESS_KEY")
            or os.environ.get("S3_SECRET_ACCESS_KEY")
            or None,
            region_name=os.environ.get("WIKI_S3_REGION")
            or os.environ.get("S3_REGION")
            or "us-east-1",
        )
        return wiki_routes_from_bindings(bindings, s3_client=client, bucket=wiki_s3_bucket)
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
    principal_tenant: str | None = None,
    path_graph_dsn: str | None = None,
    wiki_s3_bucket: str | None = None,
) -> Any:
    """Build a DeepAgents CompiledStateGraph for a general-tier agent."""
    general = _parse_general_cfg(cfg)
    wiki_routes: dict[str, Any] = {}
    if general.vfs.enabled:
        a_store = agent_store or (AsyncpgAgentVfsStore(vfs_pool) if vfs_pool else None)
        u_store = user_store or (AsyncpgUserVfsStore(vfs_pool) if vfs_pool else None)
        if a_store is None or u_store is None:
            raise RuntimeError("VFS store or vfs_pool required for general agent")
        wiki_routes = _wiki_routes_for_build(
            general,
            tenant=principal_tenant,
            path_graph_dsn=path_graph_dsn,
            wiki_s3_bucket=wiki_s3_bucket,
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
    checkpointer = build_checkpointer(cfg, secrets)

    return create_deep_agent(
        model=prepare_langgraph_llm(cfg),
        tools=tools,
        system_prompt=general.system_prompt or _DEFAULT_SYSTEM_PROMPT,
        backend=backend,
        checkpointer=checkpointer,
        subagents=general.subagents,
    )
