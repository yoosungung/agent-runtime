"""Tests for dashboard pool stats aggregation (in-memory RegistrySubscriber)."""

import json
import time

import pytest

from backend.pool_status import PoolRegistryMonitor, aggregate_subscriber_pools
from runtime_common.registry import RegistrySubscriber


@pytest.mark.asyncio
async def test_aggregate_subscriber_pools_by_runtime_kind():
    subscriber = RegistrySubscriber(redis_url="redis://localhost", kind="agent")

    await subscriber._handle_event(
        json.dumps(
            {
                "type": "snapshot",
                "pod_id": "pod-a",
                "addr": "10.0.0.1:8080",
                "active": 2,
                "max": 10,
                "checksums": ["sha256:abc"],
                "ts": time.time(),
            }
        ),
        channel="rt:events:agent_compiled_graph",
    )
    await subscriber._handle_event(
        json.dumps(
            {
                "type": "snapshot",
                "pod_id": "pod-b",
                "addr": "10.0.0.2:8080",
                "active": 1,
                "max": 8,
                "checksums": ["sha256:def"],
                "ts": time.time(),
            }
        ),
        channel="rt:events:agent_adk",
    )

    pools = aggregate_subscriber_pools(subscriber)
    assert len(pools) == 2
    by_kind = {p.runtime_kind: p for p in pools}
    assert by_kind["compiled_graph"].pod_count == 1
    assert by_kind["compiled_graph"].active_requests == 2
    assert by_kind["compiled_graph"].max_capacity == 10
    assert by_kind["adk"].pod_count == 1
    assert by_kind["adk"].active_requests == 1
    assert by_kind["adk"].max_capacity == 8


def test_pool_registry_monitor_summary_without_redis():
    monitor = PoolRegistryMonitor(redis_url="")
    summary = monitor.summary()
    assert summary.available is False
    assert summary.error == "REDIS_URL not configured"
    assert summary.agents == []
    assert summary.mcp == []


def test_pool_registry_monitor_summary_before_start():
    monitor = PoolRegistryMonitor(redis_url="redis://localhost:6379")
    summary = monitor.summary()
    assert summary.available is False
    assert summary.error == "pool registry not started"
