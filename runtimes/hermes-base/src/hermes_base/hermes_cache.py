"""Build and cache Hermes AIAgent instances per (source, user)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hermes_base.mcp_bridge import build_runtime_mcp_env
from hermes_base.profile_scope import profile_runtime_scope
from hermes_base.schemas import parse_hermes_cfg

from runtime_common.factory import merge_configs
from runtime_common.instance_cache import InstanceCache, make_instance_key
from runtime_common.providers.hermes import resolve_hermes_llm_binding
from runtime_common.schemas import SourceMeta, UserMeta
from runtime_common.secrets import SecretResolver

logger = logging.getLogger(__name__)


def hermes_instance_key(source: SourceMeta) -> str:
    return f"hermes:{source.name}:{source.version}"


def build_hermes_agent(
    cfg: dict,
    secrets: SecretResolver,
    *,
    profile_home: Path,
    agent_factory: Callable[..., Any] | None = None,
    mcp_gateway_url: str | None = None,
) -> Any:
    """Construct AIAgent (or inject agent_factory for tests)."""
    hermes = parse_hermes_cfg(cfg)
    gateway = mcp_gateway_url or os.environ.get("MCP_GATEWAY_URL", "")
    if gateway and hermes.mcp_tools:
        build_runtime_mcp_env(gateway, hermes.mcp_tools)
    llm = resolve_hermes_llm_binding(cfg)
    with profile_runtime_scope(profile_home):
        agent_kwargs: dict[str, Any] = {
            "model": llm.agent_model,
            "enabled_toolsets": hermes.enabled_toolsets,
            "quiet_mode": True,
            "skip_context_files": True,
            "max_iterations": hermes.max_iterations,
            "platform": "runtime",
        }
        if llm.provider:
            agent_kwargs["provider"] = llm.provider
        if llm.api_key:
            agent_kwargs["api_key"] = llm.api_key
        if llm.base_url:
            agent_kwargs["base_url"] = llm.base_url
        if agent_factory is not None:
            return agent_factory(**agent_kwargs)
        try:
            from run_agent import AIAgent  # type: ignore[import-untyped]  # vendored hermes-agent
        except ImportError as exc:
            raise RuntimeError(
                "hermes-agent not installed — run ./scripts/vendor-hermes.sh"
            ) from exc
        return AIAgent(
            model=llm.agent_model,
            provider=llm.provider,
            api_key=llm.api_key,
            base_url=llm.base_url,
            enabled_toolsets=hermes.enabled_toolsets,
            quiet_mode=True,
            skip_context_files=True,
            max_iterations=hermes.max_iterations,
            platform="runtime",
        )


async def get_or_build_hermes_agent(
    cache: InstanceCache,
    source: SourceMeta,
    user: UserMeta | None,
    secrets: SecretResolver,
    *,
    profile_home: Path,
    user_id: int,
    agent_factory: Callable[..., Any] | None = None,
    mcp_gateway_url: str | None = None,
) -> Any:
    cfg = merge_configs(source.config, user.config if user else None)
    key = make_instance_key(
        hermes_instance_key(source),
        str(user_id),
        user.updated_at if user else None,
    )

    async def builder() -> Any:
        return build_hermes_agent(
            cfg,
            secrets,
            profile_home=profile_home,
            agent_factory=agent_factory,
            mcp_gateway_url=mcp_gateway_url,
        )

    return await cache.get_or_build(key, builder)
