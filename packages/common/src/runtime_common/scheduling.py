"""Gateway-shared warm-aware scheduler.

Scheduler.pick() selects a pod endpoint using:
1. subscriber.snapshot() in-memory table  → power-of-2-choices (p2c)
2. If subscriber unhealthy → RegistryQuery pull fallback
3. If no warm pod found → pool ClusterIP Service URL (kube-proxy LB)
4. If all warm pods saturated → pool ClusterIP Service URL (spillover)
5. Optional soft spill when warm replica count is below target
"""

from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass
from enum import StrEnum

from runtime_common.registry import PodState, RegistryQuery, RegistrySubscriber

logger = logging.getLogger(__name__)

Candidate = tuple[str, str, int, int]  # (pod_id, addr, active, max)


class PickPath(StrEnum):
    WARM = "warm"
    COLD = "cold"
    SPILLOVER = "spillover"
    SOFT_SPILL = "soft_spill"


@dataclass(frozen=True)
class PickResult:
    url: str | None
    path: PickPath
    warm_replicas: int = 0
    warm_util_max: float = 0.0


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


def _p2c_pick(candidates: list[Candidate]) -> str | None:
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


def _warm_util_max(candidates: list[Candidate]) -> float:
    if not candidates:
        return 0.0
    return max(c[2] / max(c[3], 1) for c in candidates)


def _eligible_candidates(candidates: list[Candidate], threshold: float) -> list[Candidate]:
    """Return warm pods whose active/max ratio is strictly below *threshold*."""
    return [c for c in candidates if c[2] / max(c[3], 1) < threshold]


def _pick_from_warm_candidates(
    warm_candidates: list[Candidate],
    *,
    warm_util_threshold: float,
    warm_target_replicas: int,
    warm_spill_util: float,
    warm_spill_prob: float,
    pool_fallback_url: str | None,
    rng: random.Random,
) -> PickResult | None:
    """Select among warm pods or spill to pool service."""
    if not warm_candidates:
        return None

    warm_count = len(warm_candidates)
    util_max = _warm_util_max(warm_candidates)

    if (
        warm_target_replicas > 0
        and warm_count < warm_target_replicas
        and util_max >= warm_spill_util
        and pool_fallback_url
        and rng.random() < warm_spill_prob
    ):
        return PickResult(
            url=pool_fallback_url,
            path=PickPath.SOFT_SPILL,
            warm_replicas=warm_count,
            warm_util_max=util_max,
        )

    eligible = _eligible_candidates(warm_candidates, warm_util_threshold)
    if eligible:
        addr = _p2c_pick(eligible)
        if addr:
            return PickResult(
                url=addr,
                path=PickPath.WARM,
                warm_replicas=warm_count,
                warm_util_max=util_max,
            )

    if pool_fallback_url:
        return PickResult(
            url=pool_fallback_url,
            path=PickPath.SPILLOVER,
            warm_replicas=warm_count,
            warm_util_max=util_max,
        )

    return None


class Scheduler:
    """Warm-aware scheduler for ext-authz.

    Args:
        subscriber: RegistrySubscriber instance (or None when not available).
        kind: "agent" | "mcp"
        query: optional RegistryQuery for pull fallback when subscriber unhealthy.
        warm_util_threshold: max active/max ratio for a warm pod to remain eligible.
        warm_target_replicas: target warm pod count per checksum (0 disables soft spill).
        warm_spill_util: min util before soft spill is considered.
        warm_spill_prob: probability of soft spill when below target replicas.
    """

    def __init__(
        self,
        kind: str,
        subscriber: RegistrySubscriber | None = None,
        query: RegistryQuery | None = None,
        *,
        warm_util_threshold: float = 1.0,
        warm_target_replicas: int = 0,
        warm_spill_util: float = 0.5,
        warm_spill_prob: float = 0.2,
        rng: random.Random | None = None,
    ) -> None:
        self._kind = kind
        self._subscriber = subscriber
        self._query = query
        self._warm_util_threshold = warm_util_threshold
        self._warm_target_replicas = warm_target_replicas
        self._warm_spill_util = warm_spill_util
        self._warm_spill_prob = warm_spill_prob
        self._rng = rng or random.Random()

    async def pick(
        self,
        runtime_kind: str,
        checksum: str | None,
        ring_key: str,
        *,
        pool_fallback_url: str | None = None,
    ) -> PickResult:
        """Return a pod endpoint URL and routing path metadata."""

        pick_kwargs = {
            "warm_util_threshold": self._warm_util_threshold,
            "warm_target_replicas": self._warm_target_replicas,
            "warm_spill_util": self._warm_spill_util,
            "warm_spill_prob": self._warm_spill_prob,
            "pool_fallback_url": pool_fallback_url,
            "rng": self._rng,
        }

        # 1. subscriber memory path
        if self._subscriber is not None and self._subscriber.healthy() and checksum:
            pods, warm = self._subscriber.snapshot()
            warm_pod_ids = warm.get(checksum, set())
            if warm_pod_ids:
                warm_candidates = _build_candidates(pods, warm_pod_ids)
                result = _pick_from_warm_candidates(warm_candidates, **pick_kwargs)
                if result is not None:
                    return result

        # 2. RegistryQuery pull fallback
        if self._query is not None and checksum:
            try:
                pod_ids = await self._query.warm_pods(self._kind, runtime_kind, checksum)
                if pod_ids:
                    load_map = await self._query.load(pod_ids)
                    warm_candidates = []
                    for pid, data in load_map.items():
                        addr = data.get("addr", "")
                        active = int(data.get("active", 0))
                        max_c = int(data.get("max", 1))
                        if addr and max_c > 0:
                            warm_candidates.append((pid, f"http://{addr}", active, max_c))
                    result = _pick_from_warm_candidates(warm_candidates, **pick_kwargs)
                    if result is not None:
                        return result
            except Exception:
                logger.exception("registry query failed; falling back to pool service")

        # 3. cold-start: pool ClusterIP Service (one URL per runtime_kind; no headless/EDS)
        return PickResult(url=pool_fallback_url, path=PickPath.COLD)


def _build_candidates(
    pods: dict[str, PodState],
    warm_pod_ids: set[str],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for pid in warm_pod_ids:
        state = pods.get(pid)
        if state and state.max > 0:
            candidates.append((pid, f"http://{state.addr}", state.active, state.max))
    return candidates
