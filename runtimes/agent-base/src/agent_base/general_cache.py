"""Cached general-tier agent builder."""

from __future__ import annotations

from typing import Any

from agent_base.general_agent import build_general_agent
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
) -> object:
    """Build or reuse a cached general-tier DeepAgents graph."""
    cfg = merge_configs(source.config, user.config if user else None)
    key = make_instance_key(
        source_instance_key(source),
        str(user_id),
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
        )

    return await cache.get_or_build(key, builder)
