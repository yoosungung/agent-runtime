"""Composite VFS assembly for general-tier agents."""

from __future__ import annotations

from typing import Any

from deepagents.backends.composite import CompositeBackend
from deepagents.backends.state import StateBackend

from runtime_common.knowledge.models import KnowledgeBinding
from runtime_common.vfs.database_backend import AgentDatabaseBackend, UserDatabaseBackend
from runtime_common.vfs.store import AgentVfsStore, UserVfsStore


def build_general_vfs(
    agent_store: AgentVfsStore,
    user_store: UserVfsStore,
    *,
    kind: str,
    agent_name: str,
    user_id: int,
    wiki_routes: dict[str, Any] | None = None,
) -> CompositeBackend:
    """Build CompositeBackend: ``/`` → state, ``/agent/`` → agent DB, ``/user/`` → user DB."""
    routes: dict[str, Any] = {
        "/agent/": AgentDatabaseBackend(agent_store, kind, agent_name),
        "/user/": UserDatabaseBackend(user_store, user_id),
    }
    if wiki_routes:
        for mount, backend in wiki_routes.items():
            normalized = mount if mount.endswith("/") else f"{mount}/"
            routes[normalized] = backend
    return CompositeBackend(
        default=StateBackend(),
        routes=routes,
    )


def wiki_routes_from_bindings(
    bindings: list[KnowledgeBinding],
    *,
    s3_client: Any,
    bucket: str,
) -> dict[str, Any]:
    from runtime_common.vfs.wiki_backend import WikiS3ReadBackend

    routes: dict[str, Any] = {}
    for binding in bindings:
        mount = binding.wiki.vfs_mount.strip()
        prefix = binding.wiki.s3_prefix.strip()
        if not mount or not prefix or not bucket:
            continue
        routes[mount] = WikiS3ReadBackend(
            bucket=bucket,
            prefix=prefix,
            s3_client=s3_client,
        )
    return routes


async def build_general_vfs_from_pool(
    pool: Any,
    *,
    kind: str,
    agent_name: str,
    user_id: int,
    wiki_routes: dict[str, Any] | None = None,
) -> CompositeBackend:
    """Convenience wrapper using asyncpg pool for both stores."""
    from runtime_common.vfs.store import AsyncpgAgentVfsStore, AsyncpgUserVfsStore

    return build_general_vfs(
        AsyncpgAgentVfsStore(pool),
        AsyncpgUserVfsStore(pool),
        kind=kind,
        agent_name=agent_name,
        user_id=user_id,
        wiki_routes=wiki_routes,
    )
