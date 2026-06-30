"""Cached general-tier agent builder."""

from __future__ import annotations

from typing import Any

from agent_base.general_agent import build_general_agent
from agent_base.knowledge_context import reset_knowledge_bindings, setup_knowledge_bindings
from runtime_common.factory import merge_configs
from runtime_common.instance_builder import source_instance_key
from runtime_common.instance_cache import InstanceCache, make_instance_key
from runtime_common.schemas import SourceMeta, UserMeta
from runtime_common.secrets import SecretResolver


async def get_or_build_general_agent(
    cache: InstanceCache,
    source: SourceMeta,
    user: UserMeta | None,
    secrets: SecretResolver,
    *,
    kind: str,
    agent_name: str,
    user_id: int,
    vfs_pool: Any,
    mcp_gateway_url: str | None,
    agent_gateway_url: str | None = None,
    agent_delegate_timeout_sec: float = 60.0,
    max_delegate_depth: int = 3,
    principal_tenant: str | None = None,
    path_graph_dsn: str | None = None,
    wiki_s3_bucket: str | None = None,
) -> object:
    """Build or reuse a cached general-tier DeepAgents graph."""
    cfg = merge_configs(source.config, user.config if user else None)
    key = make_instance_key(
        source_instance_key(source),
        f"{user_id}:{principal_tenant or ''}",
        user.updated_at if user else None,
    )

    async def builder() -> object:
        return build_general_agent(
            cfg,
            secrets,
            kind=kind,
            agent_name=agent_name,
            user_id=user_id,
            vfs_pool=vfs_pool,
            mcp_gateway_url=mcp_gateway_url,
            agent_gateway_url=agent_gateway_url,
            agent_delegate_timeout_sec=agent_delegate_timeout_sec,
            max_delegate_depth=max_delegate_depth,
            principal_tenant=principal_tenant,
            path_graph_dsn=path_graph_dsn,
            wiki_s3_bucket=wiki_s3_bucket,
        )

    return await cache.get_or_build(key, builder)
