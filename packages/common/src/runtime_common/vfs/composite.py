"""Composite VFS assembly for general-tier agents."""

from __future__ import annotations

from typing import Any

from deepagents.backends.composite import CompositeBackend
from deepagents.backends.state import StateBackend

from runtime_common.vfs.database_backend import AgentDatabaseBackend, UserDatabaseBackend
from runtime_common.vfs.store import AgentVfsStore, UserVfsStore


def build_general_vfs(
    agent_store: AgentVfsStore,
    user_store: UserVfsStore,
    *,
    kind: str,
    agent_name: str,
    user_id: int,
) -> CompositeBackend:
    """Build CompositeBackend: ``/`` → state, ``/agent/`` → agent DB, ``/user/`` → user DB."""
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/agent/": AgentDatabaseBackend(agent_store, kind, agent_name),
            "/user/": UserDatabaseBackend(user_store, user_id),
        },
    )


async def build_general_vfs_from_pool(
    pool: Any,
    *,
    kind: str,
    agent_name: str,
    user_id: int,
) -> CompositeBackend:
    """Convenience wrapper using asyncpg pool for both stores."""
    from runtime_common.vfs.store import AsyncpgAgentVfsStore, AsyncpgUserVfsStore

    return build_general_vfs(
        AsyncpgAgentVfsStore(pool),
        AsyncpgUserVfsStore(pool),
        kind=kind,
        agent_name=agent_name,
        user_id=user_id,
    )
