"""Unit tests for runtime_common.scheduling."""

import pytest

from runtime_common.registry import PodState, RegistrySubscriber
from runtime_common.scheduling import (
    PickPath,
    Scheduler,
    _eligible_candidates,
    _p2c_pick,
    _ring_pick,
)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _make_subscriber_with_pods(pods_data: list[dict]) -> RegistrySubscriber:
    """Build a subscriber with pre-populated in-memory state (no Redis)."""
    sub = RegistrySubscriber.__new__(RegistrySubscriber)
    sub._kind = "agent"
    sub._healthy = True
    sub._bootstrap_done = True
    sub._pods = {}
    sub._warm = {}

    import asyncio

    sub._lock = asyncio.Lock()

    for pd in pods_data:
        pod_id = pd["pod_id"]
        cs = pd.get("checksum", "sha256:abc")
        state = PodState(
            pod_id=pod_id,
            addr=pd.get("addr", f"{pod_id}:8080"),
            active=pd.get("active", 0),
            max=pd.get("max", 10),
            checksums={cs},
        )
        sub._pods[pod_id] = state
        sub._warm.setdefault(cs, set()).add(pod_id)
    return sub


# ---------------------------------------------------------------------------
# _p2c_pick
# ---------------------------------------------------------------------------


def test_p2c_single_candidate():
    candidates = [("pod-1", "http://10.0.0.1:8080", 2, 10)]
    assert _p2c_pick(candidates) == "http://10.0.0.1:8080"


def test_p2c_empty():
    assert _p2c_pick([]) is None


def test_p2c_picks_less_loaded():
    # pod-1 utilization 0.8, pod-2 utilization 0.2 → pod-2 preferred
    results = set()
    for _ in range(20):
        candidates = [
            ("pod-1", "http://a:8080", 8, 10),
            ("pod-2", "http://b:8080", 2, 10),
        ]
        results.add(_p2c_pick(candidates))
    # The less-loaded pod should win most of the time
    # (p2c always picks both then chooses lower ratio → deterministic for 2 candidates)
    assert "http://b:8080" in results


# ---------------------------------------------------------------------------
# _ring_pick
# ---------------------------------------------------------------------------


def test_ring_pick_empty():
    assert _ring_pick("key", []) is None


def test_ring_pick_deterministic():
    endpoints = ["http://a:8080", "http://b:8080", "http://c:8080"]
    r1 = _ring_pick("some-key", endpoints)
    r2 = _ring_pick("some-key", endpoints)
    assert r1 == r2
    assert r1 in endpoints


# ---------------------------------------------------------------------------
# Scheduler.pick
# ---------------------------------------------------------------------------


def test_eligible_candidates_excludes_saturated():
    candidates = [
        ("pod-1", "http://a:8080", 10, 10),
        ("pod-2", "http://b:8080", 5, 10),
    ]
    eligible = _eligible_candidates(candidates, threshold=1.0)
    assert len(eligible) == 1
    assert eligible[0][0] == "pod-2"


def test_eligible_candidates_respects_util_threshold():
    candidates = [("pod-1", "http://a:8080", 9, 10)]
    assert len(_eligible_candidates(candidates, threshold=1.0)) == 1
    assert _eligible_candidates(candidates, threshold=0.85) == []
    assert len(_eligible_candidates(candidates, threshold=0.95)) == 1


@pytest.mark.asyncio
async def test_scheduler_warm_hit():
    sub = _make_subscriber_with_pods(
        [
            {"pod_id": "pod-1", "checksum": "sha256:abc", "active": 0, "max": 10},
        ]
    )
    scheduler = Scheduler(kind="agent", subscriber=sub)
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum="sha256:abc",
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.url == "http://pod-1:8080"
    assert result.path == PickPath.WARM


@pytest.mark.asyncio
async def test_scheduler_warm_miss_falls_back_to_pool_service():
    sub = _make_subscriber_with_pods([])  # no warm pods
    scheduler = Scheduler(kind="agent", subscriber=sub)
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum="sha256:xyz",
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.url == "http://agent-pool-compiled-graph:8080"
    assert result.path == PickPath.COLD


@pytest.mark.asyncio
async def test_scheduler_no_subscriber_falls_back_to_pool_service():
    scheduler = Scheduler(kind="agent")
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum="sha256:abc",
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.url == "http://agent-pool-compiled-graph:8080"
    assert result.path == PickPath.COLD


@pytest.mark.asyncio
async def test_scheduler_unhealthy_subscriber_uses_pool_service():
    sub = _make_subscriber_with_pods(
        [
            {"pod_id": "pod-1", "checksum": "sha256:abc"},
        ]
    )
    sub._healthy = False  # simulate unhealthy

    scheduler = Scheduler(kind="agent", subscriber=sub)
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum="sha256:abc",
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.url == "http://agent-pool-compiled-graph:8080"
    assert result.path == PickPath.COLD


@pytest.mark.asyncio
async def test_scheduler_saturated_warm_pod_spills_to_pool():
    sub = _make_subscriber_with_pods(
        [
            {"pod_id": "pod-1", "checksum": "sha256:abc", "active": 10, "max": 10},
        ]
    )
    scheduler = Scheduler(kind="agent", subscriber=sub)
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum="sha256:abc",
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.url == "http://agent-pool-compiled-graph:8080"
    assert result.path == PickPath.SPILLOVER
    assert result.warm_replicas == 1


@pytest.mark.asyncio
async def test_scheduler_picks_less_loaded_warm_pod():
    sub = _make_subscriber_with_pods(
        [
            {"pod_id": "pod-1", "checksum": "sha256:abc", "active": 10, "max": 10},
            {"pod_id": "pod-2", "checksum": "sha256:abc", "active": 2, "max": 10},
        ]
    )
    scheduler = Scheduler(kind="agent", subscriber=sub)
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum="sha256:abc",
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.url == "http://pod-2:8080"
    assert result.path == PickPath.WARM


@pytest.mark.asyncio
async def test_scheduler_all_warm_pods_saturated_spills():
    sub = _make_subscriber_with_pods(
        [
            {"pod_id": "pod-1", "checksum": "sha256:abc", "active": 10, "max": 10},
            {"pod_id": "pod-2", "checksum": "sha256:abc", "active": 32, "max": 32},
        ]
    )
    scheduler = Scheduler(kind="agent", subscriber=sub)
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum="sha256:abc",
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.url == "http://agent-pool-compiled-graph:8080"
    assert result.path == PickPath.SPILLOVER
    assert result.warm_replicas == 2


@pytest.mark.asyncio
async def test_scheduler_no_checksum_skips_warm():
    sub = _make_subscriber_with_pods(
        [
            {"pod_id": "pod-1", "checksum": "sha256:abc"},
        ]
    )
    scheduler = Scheduler(kind="agent", subscriber=sub)
    # checksum=None → skip warm path entirely
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum=None,
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.url == "http://agent-pool-compiled-graph:8080"
    assert result.path == PickPath.COLD


@pytest.mark.asyncio
async def test_scheduler_no_pool_fallback_returns_none():
    scheduler = Scheduler(kind="agent")
    result = await scheduler.pick(runtime_kind="compiled_graph", checksum=None, ring_key="key")
    assert result.url is None
    assert result.path == PickPath.COLD


@pytest.mark.asyncio
async def test_scheduler_soft_spill_when_replicas_below_target():
    sub = _make_subscriber_with_pods(
        [
            {"pod_id": "pod-1", "checksum": "sha256:abc", "active": 6, "max": 10},
        ]
    )
    scheduler = Scheduler(
        kind="agent",
        subscriber=sub,
        warm_target_replicas=3,
        warm_spill_util=0.5,
        warm_spill_prob=1.0,
    )
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum="sha256:abc",
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.url == "http://agent-pool-compiled-graph:8080"
    assert result.path == PickPath.SOFT_SPILL


@pytest.mark.asyncio
async def test_scheduler_no_soft_spill_when_target_replicas_met():
    sub = _make_subscriber_with_pods(
        [
            {"pod_id": "pod-1", "checksum": "sha256:abc", "active": 6, "max": 10},
            {"pod_id": "pod-2", "checksum": "sha256:abc", "active": 6, "max": 10},
            {"pod_id": "pod-3", "checksum": "sha256:abc", "active": 6, "max": 10},
        ]
    )
    scheduler = Scheduler(
        kind="agent",
        subscriber=sub,
        warm_target_replicas=3,
        warm_spill_util=0.5,
        warm_spill_prob=1.0,
    )
    result = await scheduler.pick(
        runtime_kind="compiled_graph",
        checksum="sha256:abc",
        ring_key="key",
        pool_fallback_url="http://agent-pool-compiled-graph:8080",
    )
    assert result.path == PickPath.WARM
    assert result.url.startswith("http://pod-")
