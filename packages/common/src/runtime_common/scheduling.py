"""Gateway-shared warm-aware scheduler.

Scheduler.pick() selects a pod endpoint using:
1. subscriber.snapshot() in-memory table  → power-of-2-choices (p2c)
2. If subscriber unhealthy → RegistryQuery pull fallback
3. If no warm pod found → consistent ring-hash over provided endpoints
"""

from __future__ import annotations

import hashlib
import logging
import random

from runtime_common.registry import RegistryQuery, RegistrySubscriber

logger = logging.getLogger(__name__)


def _ring_pick(key: str, endpoints: list[str]) -> str | None:
    if not endpoints:
        return None
    try:
        from uhashring import HashRing

        ring = HashRing(endpoints)
        return ring.get_node(key)
    except Exception:
        # Fallback: simple deterministic hash
        idx = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(endpoints)
        return endpoints[idx]


def _p2c_pick(candidates: list[tuple[str, str, int, int]]) -> str | None:
    """Power-of-2-choices: pick 2 random candidates, choose the less loaded.

    candidates: list of (pod_id, addr, active, max)
    Returns addr of selected pod.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][1]
    a, b = random.sample(candidates, 2)
    # prefer lower utilization ratio; tie-break by pod_id for determinism
    ratio_a = a[2] / max(a[3], 1)
    ratio_b = b[2] / max(b[3], 1)
    chosen = a if ratio_a <= ratio_b else b
    return chosen[1]


class Scheduler:
    """Warm-aware scheduler shared by agent-gateway and mcp-gateway.

    Args:
        subscriber: RegistrySubscriber instance (or None when not available).
        kind: "agent" | "mcp"
        ring_fallback_endpoints: list of service URL strings for cold-start ring-hash.
        query: optional RegistryQuery for pull fallback when subscriber unhealthy.
    """

    def __init__(
        self,
        kind: str,
        ring_fallback_endpoints: list[str],
        subscriber: RegistrySubscriber | None = None,
        query: RegistryQuery | None = None,
    ) -> None:
        self._kind = kind
        self._endpoints = ring_fallback_endpoints
        self._subscriber = subscriber
        self._query = query

    async def pick(
        self,
        runtime_kind: str,
        checksum: str | None,
        ring_key: str,
    ) -> str | None:
        """Return an endpoint URL (addr or pool service URL)."""

        # 1. subscriber memory path
        if self._subscriber is not None and self._subscriber.healthy() and checksum:
            pods, warm = self._subscriber.snapshot()
            warm_pod_ids = warm.get(checksum, set())
            if warm_pod_ids:
                candidates = []
                for pid in warm_pod_ids:
                    state = pods.get(pid)
                    if state and state.max > 0:
                        candidates.append((pid, f"http://{state.addr}", state.active, state.max))
                addr = _p2c_pick(candidates)
                if addr:
                    return addr

        # 2. RegistryQuery pull fallback
        if self._query is not None and checksum:
            try:
                pod_ids = await self._query.warm_pods(self._kind, runtime_kind, checksum)
                if pod_ids:
                    load_map = await self._query.load(pod_ids)
                    candidates = []
                    for pid, data in load_map.items():
                        addr = data.get("addr", "")
                        active = int(data.get("active", 0))
                        max_c = int(data.get("max", 1))
                        if addr and max_c > 0:
                            candidates.append((pid, f"http://{addr}", active, max_c))
                    addr = _p2c_pick(candidates)
                    if addr:
                        return addr
            except Exception:
                logger.exception("registry query failed; falling back to ring-hash")

        # 3. ring-hash fallback (cold-start)
        return _ring_pick(ring_key, self._endpoints)
