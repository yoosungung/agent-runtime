"""In-memory warm-registry pool stats for the admin dashboard.

Subscribes to the same Pub/Sub events as ext-authz (RegistrySubscriber) and
aggregates pod load by runtime_kind on read — no Redis SCAN on the request path.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from runtime_common.registry import RegistrySubscriber

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


def aggregate_subscriber_pools(subscriber: RegistrySubscriber) -> list[PoolRuntimeStatus]:
    """Roll up in-memory pod states by runtime_kind."""
    pods, _ = subscriber.snapshot()
    totals: dict[str, dict[str, int]] = {}

    for state in pods.values():
        if state.max <= 0:
            continue
        runtime_kind = state.runtime_kind or "unknown"
        bucket = totals.setdefault(
            runtime_kind,
            {"pod_count": 0, "active": 0, "max": 0},
        )
        bucket["pod_count"] += 1
        bucket["active"] += state.active
        bucket["max"] += state.max

    return [
        PoolRuntimeStatus(
            runtime_kind=runtime_kind,
            pod_count=values["pod_count"],
            active_requests=values["active"],
            max_capacity=values["max"],
        )
        for runtime_kind, values in sorted(totals.items())
        if runtime_kind != "unknown" or values["pod_count"] > 0
    ]


class PoolRegistryMonitor:
    """Background warm-registry mirror for dashboard pool metrics."""

    def __init__(self, redis_url: str, registry_ttl_sec: float = 3.0) -> None:
        self._redis_url = redis_url
        self._registry_ttl_sec = registry_ttl_sec
        self._agent_sub: RegistrySubscriber | None = None
        self._mcp_sub: RegistrySubscriber | None = None
        self._started = False

    async def start(self) -> None:
        if not self._redis_url:
            return
        self._agent_sub = RegistrySubscriber(
            redis_url=self._redis_url,
            kind="agent",
            ttl_sec=self._registry_ttl_sec,
        )
        self._mcp_sub = RegistrySubscriber(
            redis_url=self._redis_url,
            kind="mcp",
            ttl_sec=self._registry_ttl_sec,
        )
        await asyncio.gather(self._agent_sub.start(), self._mcp_sub.start())
        self._started = True
        logger.info("pool registry monitor started")

    async def stop(self) -> None:
        for sub in (self._agent_sub, self._mcp_sub):
            if sub is not None:
                await sub.stop()
        self._started = False

    def summary(self) -> PoolSummary:
        if not self._redis_url:
            return PoolSummary(
                available=False,
                error="REDIS_URL not configured",
                agents=[],
                mcp=[],
            )
        if not self._started or self._agent_sub is None or self._mcp_sub is None:
            return PoolSummary(
                available=False,
                error="pool registry not started",
                agents=[],
                mcp=[],
            )

        return PoolSummary(
            available=True,
            error=None,
            agents=aggregate_subscriber_pools(self._agent_sub),
            mcp=aggregate_subscriber_pools(self._mcp_sub),
        )
