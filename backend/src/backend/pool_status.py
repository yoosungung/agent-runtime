"""Read warm-registry pool stats from Redis for the admin dashboard."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoolRuntimeStatus:
    runtime_kind: str
    pod_count: int
    active_requests: int
    max_capacity: int


@dataclass(frozen=True)
class PoolSummary:
    available: bool
    error: str | None
    agents: list[PoolRuntimeStatus]
    mcp: list[PoolRuntimeStatus]


async def fetch_pool_summary(redis_url: str) -> PoolSummary:
    """Aggregate warm-registry pod load by runtime kind."""
    if not redis_url:
        return PoolSummary(
            available=False,
            error="REDIS_URL not configured",
            agents=[],
            mcp=[],
        )

    client = aioredis.from_url(redis_url, decode_responses=True)
    try:
        agents = await _collect_kind_pools(client, "agent")
        mcp = await _collect_kind_pools(client, "mcp")
        return PoolSummary(available=True, error=None, agents=agents, mcp=mcp)
    except Exception as exc:
        logger.warning("failed to fetch pool summary from redis: %s", exc)
        return PoolSummary(
            available=False,
            error=str(exc),
            agents=[],
            mcp=[],
        )
    finally:
        await client.aclose()


async def _collect_kind_pools(
    client: aioredis.Redis,
    kind: str,
) -> list[PoolRuntimeStatus]:
    pod_ids_by_runtime: dict[str, set[str]] = {}
    cursor = 0
    while True:
        cursor, keys = await client.scan(cursor, match=f"rt:warm:{kind}_*", count=100)
        for key in keys:
            parts = key.split(":")
            if len(parts) < 3:
                continue
            runtime_kind = parts[2].removeprefix(f"{kind}_")
            members: set[str] = await client.smembers(key)  # type: ignore[misc]
            if members:
                pod_ids_by_runtime.setdefault(runtime_kind, set()).update(members)
        if cursor == 0:
            break

    pools: list[PoolRuntimeStatus] = []
    for runtime_kind in sorted(pod_ids_by_runtime):
        pod_ids = pod_ids_by_runtime[runtime_kind]
        pipe = client.pipeline()
        for pod_id in pod_ids:
            pipe.hgetall(f"rt:load:{pod_id}")
        load_rows = await pipe.execute()

        active = 0
        max_capacity = 0
        live_pods = 0
        for load in load_rows:
            if not load:
                continue
            live_pods += 1
            active += int(load.get("active", 0))
            max_capacity += int(load.get("max", 0))

        pools.append(
            PoolRuntimeStatus(
                runtime_kind=runtime_kind,
                pod_count=live_pods,
                active_requests=active,
                max_capacity=max_capacity,
            )
        )
    return pools
