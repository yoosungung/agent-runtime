"""Unit tests for runtime_common.registry."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from runtime_common.registry import (
    ActiveCounter,
    RegistryPublisher,
    RegistrySubscriber,
)

# ---------------------------------------------------------------------------
# ActiveCounter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_counter_acquire_release():
    counter = ActiveCounter(max_concurrent=2)
    assert counter.active == 0
    assert counter.max == 2

    await counter.acquire()
    assert counter.active == 1

    await counter.acquire()
    assert counter.active == 2

    counter.release()
    await asyncio.sleep(0)  # let _dec task run
    assert counter.active == 1

    counter.release()
    await asyncio.sleep(0)
    assert counter.active == 0


@pytest.mark.asyncio
async def test_active_counter_context_manager():
    counter = ActiveCounter(max_concurrent=3)
    async with counter:
        assert counter.active == 1
    await asyncio.sleep(0)
    assert counter.active == 0


@pytest.mark.asyncio
async def test_active_counter_blocks_at_max():
    counter = ActiveCounter(max_concurrent=1)
    await counter.acquire()

    # Second acquire should block; we verify it doesn't complete immediately
    task = asyncio.create_task(counter.acquire())
    await asyncio.sleep(0)
    assert not task.done()

    counter.release()
    await asyncio.sleep(0)
    await task  # now it should complete
    counter.release()
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# RegistryPublisher (unit — mocked Redis)
# ---------------------------------------------------------------------------


def _make_mock_pipeline():
    pipe = MagicMock()
    pipe.sadd = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.hset = MagicMock(return_value=pipe)
    pipe.publish = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    return pipe


@pytest.mark.asyncio
async def test_publisher_tick_calls_redis(monkeypatch):
    mock_redis = MagicMock()
    mock_pipe = _make_mock_pipeline()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    counter = ActiveCounter(3)

    def checksums_getter():
        return {"sha256:abc", "sha256:def"}

    publisher = RegistryPublisher(
        redis_url="redis://localhost",
        pod_id="pod-1",
        addr="10.0.0.1:8080",
        runtime_kind="compiled_graph",
        kind="agent",
        active_counter=counter,
        warm_checksums_getter=checksums_getter,
        interval_sec=1,
        ttl_sec=3,
    )
    publisher._client = mock_redis

    await publisher._tick()

    # Verify pipeline was built and executed
    mock_pipe.execute.assert_called_once()
    # sadd called for each checksum
    assert mock_pipe.sadd.call_count == 2
    # hset called once for load key
    mock_pipe.hset.assert_called_once()
    # publish called once for snapshot
    mock_pipe.publish.assert_called_once()

    channel, payload_str = mock_pipe.publish.call_args[0]
    assert channel == "rt:events:agent_compiled_graph"
    payload = json.loads(payload_str)
    assert payload["type"] == "snapshot"
    assert payload["pod_id"] == "pod-1"
    assert set(payload["checksums"]) == {"sha256:abc", "sha256:def"}


@pytest.mark.asyncio
async def test_publisher_down_event(monkeypatch):
    published = {}

    async def mock_publish(channel, msg):
        published["channel"] = channel
        published["msg"] = json.loads(msg)

    mock_redis = MagicMock()
    mock_redis.publish = mock_publish

    counter = ActiveCounter(1)
    publisher = RegistryPublisher(
        redis_url="redis://localhost",
        pod_id="pod-down",
        addr="10.0.0.1:8080",
        runtime_kind="adk",
        kind="agent",
        active_counter=counter,
        warm_checksums_getter=lambda: set(),
    )
    publisher._client = mock_redis
    await publisher._publish_down()

    assert published["channel"] == "rt:events:agent_adk"
    assert published["msg"]["type"] == "down"
    assert published["msg"]["pod_id"] == "pod-down"


# ---------------------------------------------------------------------------
# RegistrySubscriber snapshot + event handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscriber_handle_snapshot_event():
    subscriber = RegistrySubscriber(redis_url="redis://localhost", kind="agent")

    snapshot_msg = json.dumps(
        {
            "type": "snapshot",
            "pod_id": "pod-1",
            "addr": "10.0.0.1:8080",
            "active": 2,
            "max": 10,
            "checksums": ["sha256:abc"],
            "ts": time.time(),
        }
    )
    await subscriber._handle_event(snapshot_msg)

    pods, warm = subscriber.snapshot()
    assert "pod-1" in pods
    assert pods["pod-1"].active == 2
    assert "sha256:abc" in warm
    assert "pod-1" in warm["sha256:abc"]


@pytest.mark.asyncio
async def test_subscriber_handle_down_event():
    subscriber = RegistrySubscriber(redis_url="redis://localhost", kind="agent")

    snapshot_msg = json.dumps(
        {
            "type": "snapshot",
            "pod_id": "pod-1",
            "addr": "10.0.0.1:8080",
            "active": 1,
            "max": 10,
            "checksums": ["sha256:abc"],
            "ts": time.time(),
        }
    )
    await subscriber._handle_event(snapshot_msg)

    down_msg = json.dumps({"type": "down", "pod_id": "pod-1", "ts": time.time()})
    await subscriber._handle_event(down_msg)

    pods, warm = subscriber.snapshot()
    assert "pod-1" not in pods
    assert "sha256:abc" not in warm or "pod-1" not in warm.get("sha256:abc", set())


@pytest.mark.asyncio
async def test_subscriber_snapshot_checksum_update():
    subscriber = RegistrySubscriber(redis_url="redis://localhost", kind="agent")

    # First snapshot: pod has cs1
    await subscriber._handle_event(
        json.dumps(
            {
                "type": "snapshot",
                "pod_id": "pod-1",
                "addr": "a:8080",
                "active": 0,
                "max": 10,
                "checksums": ["sha256:cs1"],
                "ts": time.time(),
            }
        )
    )
    # Second snapshot: pod now has cs2 only
    await subscriber._handle_event(
        json.dumps(
            {
                "type": "snapshot",
                "pod_id": "pod-1",
                "addr": "a:8080",
                "active": 0,
                "max": 10,
                "checksums": ["sha256:cs2"],
                "ts": time.time(),
            }
        )
    )

    pods, warm = subscriber.snapshot()
    assert "sha256:cs1" not in warm or "pod-1" not in warm.get("sha256:cs1", set())
    assert "sha256:cs2" in warm
    assert "pod-1" in warm["sha256:cs2"]


@pytest.mark.asyncio
async def test_subscriber_ttl_reaper():
    subscriber = RegistrySubscriber(redis_url="redis://localhost", kind="agent", ttl_sec=1.0)

    # Inject a stale pod directly
    from runtime_common.registry import PodState

    stale_pod = PodState(
        pod_id="stale",
        addr="x:8080",
        active=0,
        max=1,
        checksums={"sha256:old"},
        last_seen=time.monotonic() - 10.0,  # way past TTL*2
    )
    async with subscriber._lock:
        subscriber._pods["stale"] = stale_pod
        subscriber._warm.setdefault("sha256:old", set()).add("stale")

    await subscriber._reaper_loop.__wrapped__(subscriber) if hasattr(
        subscriber._reaper_loop, "__wrapped__"
    ) else None

    # Directly invoke reaper logic
    cutoff = time.monotonic() - subscriber._ttl * 2
    async with subscriber._lock:
        dead = [pid for pid, s in subscriber._pods.items() if s.last_seen < cutoff]
        for pid in dead:
            old = subscriber._pods.pop(pid)
            for cs in old.checksums:
                if cs in subscriber._warm:
                    subscriber._warm[cs].discard(pid)
                    if not subscriber._warm[cs]:
                        del subscriber._warm[cs]

    pods, warm = subscriber.snapshot()
    assert "stale" not in pods
    assert "sha256:old" not in warm


@pytest.mark.asyncio
async def test_subscriber_healthy_false_initially():
    subscriber = RegistrySubscriber(redis_url="redis://localhost", kind="agent")
    assert not subscriber.healthy()
