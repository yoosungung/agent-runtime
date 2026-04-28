"""Redis-based warm-registry for pool pods.

Three-sided API:
- RegistryPublisher  — pool side: heartbeat + Pub/Sub snapshot
- RegistrySubscriber — gateway side: push-based in-memory routing table
- RegistryQuery      — gateway side: pull fallback when subscriber is unhealthy
- ActiveCounter      — asyncio semaphore wrapper exposing active/max counts
- make_redis_saver   — LangGraph RedisSaver factory helper
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Key patterns
# rt:warm:{agent,mcp}_{runtime_kind}:{checksum}  → SET of pod_id, TTL=registry_ttl_sec
# rt:load:{pod_id}                                → HASH {active, max, addr}, TTL=registry_ttl_sec
# rt:events:{agent,mcp}_{runtime_kind}            → Pub/Sub channel
# rt:ckpt:*                                       → LangGraph checkpoint keys


def _warm_key(kind: str, runtime_kind: str, checksum: str) -> str:
    return f"rt:warm:{kind}_{runtime_kind}:{checksum}"


def _load_key(pod_id: str) -> str:
    return f"rt:load:{pod_id}"


def _events_channel(kind: str, runtime_kind: str) -> str:
    return f"rt:events:{kind}_{runtime_kind}"


# ---------------------------------------------------------------------------
# ActiveCounter
# ---------------------------------------------------------------------------


class ActiveCounter:
    """asyncio.Semaphore wrapper that exposes active/max counts."""

    def __init__(self, max_concurrent: int) -> None:
        self._max = max_concurrent
        self._sem = asyncio.Semaphore(max_concurrent)
        self._active = 0
        self._lock = asyncio.Lock()

    @property
    def max(self) -> int:
        return self._max

    @property
    def active(self) -> int:
        return self._active

    async def acquire(self) -> None:
        await self._sem.acquire()
        async with self._lock:
            self._active += 1

    def release(self) -> None:
        self._sem.release()
        asyncio.get_event_loop().create_task(self._dec())

    async def _dec(self) -> None:
        async with self._lock:
            self._active -= 1

    async def __aenter__(self) -> ActiveCounter:
        await self.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        self.release()


# ---------------------------------------------------------------------------
# RegistryPublisher (pool side)
# ---------------------------------------------------------------------------


class RegistryPublisher:
    """Heartbeat publisher for pool pods.

    Runs a background task that every `interval` seconds:
    1. Stores warm-set + load HASH in Redis (TTL = ttl_sec).
    2. Publishes a snapshot JSON to the events channel.

    On shutdown, publishes a {type:"down"} event.
    """

    def __init__(
        self,
        redis_url: str,
        pod_id: str,
        addr: str,
        runtime_kind: str,
        kind: str,
        active_counter: ActiveCounter,
        warm_checksums_getter: Callable[[], set[str]],
        interval_sec: int = 2,
        ttl_sec: int = 3,
    ) -> None:
        self._redis_url = redis_url
        self._pod_id = pod_id
        self._addr = addr
        self._runtime_kind = runtime_kind
        self._kind = kind
        self._counter = active_counter
        self._warm_checksums_getter = warm_checksums_getter
        self._interval = interval_sec
        self._ttl = ttl_sec
        self._task: asyncio.Task | None = None
        self._client: aioredis.Redis | None = None
        self._last_ok = False

    async def start(self) -> None:
        self._client = aioredis.from_url(self._redis_url, decode_responses=True)
        self._task = asyncio.create_task(self._loop(), name=f"registry-publisher-{self._pod_id}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._publish_down()
            await self._client.aclose()

    def healthy(self) -> bool:
        return self._last_ok

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
                self._last_ok = True
            except Exception:
                logger.exception("registry publisher tick failed")
                self._last_ok = False
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        assert self._client is not None
        checksums = self._warm_checksums_getter()
        active = self._counter.active
        max_c = self._counter.max
        channel = _events_channel(self._kind, self._runtime_kind)

        pipe = self._client.pipeline()
        for cs in checksums:
            key = _warm_key(self._kind, self._runtime_kind, cs)
            pipe.sadd(key, self._pod_id)
            pipe.expire(key, self._ttl)
        load_key = _load_key(self._pod_id)
        pipe.hset(load_key, mapping={"active": active, "max": max_c, "addr": self._addr})
        pipe.expire(load_key, self._ttl)

        snapshot = json.dumps(
            {
                "type": "snapshot",
                "pod_id": self._pod_id,
                "addr": self._addr,
                "active": active,
                "max": max_c,
                "checksums": list(checksums),
                "ts": time.time(),
            }
        )
        pipe.publish(channel, snapshot)
        await pipe.execute()

    async def _publish_down(self) -> None:
        if not self._client:
            return
        try:
            channel = _events_channel(self._kind, self._runtime_kind)
            msg = json.dumps({"type": "down", "pod_id": self._pod_id, "ts": time.time()})
            await self._client.publish(channel, msg)
        except Exception:
            logger.exception("failed to publish down event")


# ---------------------------------------------------------------------------
# PodState (gateway in-memory table entry)
# ---------------------------------------------------------------------------


@dataclass
class PodState:
    pod_id: str
    addr: str
    active: int
    max: int
    checksums: set[str] = field(default_factory=set)
    last_seen: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# RegistrySubscriber (gateway side — push-based)
# ---------------------------------------------------------------------------


class RegistrySubscriber:
    """Gateway-side warm-registry subscriber.

    Subscribes to `rt:events:{kind}_*`, builds an in-memory routing table,
    and runs bootstrap SCAN + periodic reconcile to handle missed events.
    """

    def __init__(
        self,
        redis_url: str,
        kind: str,
        ttl_sec: float = 3.0,
        reconcile_interval_sec: float = 30.0,
    ) -> None:
        self._redis_url = redis_url
        self._kind = kind
        self._ttl = ttl_sec
        self._reconcile_interval = reconcile_interval_sec
        self._pods: dict[str, PodState] = {}
        self._warm: dict[str, set[str]] = {}  # checksum → set[pod_id]
        self._lock = asyncio.Lock()
        self._healthy = False
        self._bootstrap_done = False
        self._sub_task: asyncio.Task | None = None
        self._reconcile_task: asyncio.Task | None = None
        self._reaper_task: asyncio.Task | None = None
        self._client: aioredis.Redis | None = None

    async def start(self) -> None:
        self._client = aioredis.from_url(self._redis_url, decode_responses=True)
        self._sub_task = asyncio.create_task(
            self._subscribe_loop(), name=f"registry-sub-{self._kind}"
        )
        self._reconcile_task = asyncio.create_task(
            self._reconcile_loop(), name=f"registry-reconcile-{self._kind}"
        )
        self._reaper_task = asyncio.create_task(
            self._reaper_loop(), name=f"registry-reaper-{self._kind}"
        )

    async def stop(self) -> None:
        for task in (self._sub_task, self._reconcile_task, self._reaper_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._client:
            await self._client.aclose()
        self._healthy = False

    def healthy(self) -> bool:
        return self._healthy and self._bootstrap_done

    def snapshot(self) -> tuple[dict[str, PodState], dict[str, set[str]]]:
        """Return (pods, warm) — caller should not mutate."""
        return self._pods, self._warm

    async def _subscribe_loop(self) -> None:
        pattern = f"rt:events:{self._kind}_*"
        while True:
            try:
                pubsub = self._client.pubsub()  # type: ignore[union-attr]
                await pubsub.psubscribe(pattern)
                self._healthy = True
                # Bootstrap after subscription established (prevents event loss)
                await self._bootstrap()
                async for raw in pubsub.listen():
                    if raw["type"] != "pmessage":
                        continue
                    await self._handle_event(raw["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("registry subscriber error — reconnecting")
                self._healthy = False
                await asyncio.sleep(1)

    async def _handle_event(self, data: str) -> None:
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return
        msg_type = msg.get("type")
        pod_id = msg.get("pod_id", "")
        async with self._lock:
            if msg_type == "snapshot":
                addr = msg.get("addr", "")
                active = int(msg.get("active", 0))
                max_c = int(msg.get("max", 1))
                checksums: set[str] = set(msg.get("checksums", []))
                prev = self._pods.get(pod_id)
                old_checksums = prev.checksums if prev else set()
                self._pods[pod_id] = PodState(
                    pod_id=pod_id,
                    addr=addr,
                    active=active,
                    max=max_c,
                    checksums=checksums,
                    last_seen=time.monotonic(),
                )
                # Update warm index
                for cs in old_checksums - checksums:
                    if cs in self._warm:
                        self._warm[cs].discard(pod_id)
                        if not self._warm[cs]:
                            del self._warm[cs]
                for cs in checksums - old_checksums:
                    self._warm.setdefault(cs, set()).add(pod_id)
            elif msg_type == "down":
                if pod_id in self._pods:
                    old = self._pods.pop(pod_id)
                    for cs in old.checksums:
                        if cs in self._warm:
                            self._warm[cs].discard(pod_id)
                            if not self._warm[cs]:
                                del self._warm[cs]

    async def _bootstrap(self) -> None:
        assert self._client is not None
        try:
            pattern = f"rt:warm:{self._kind}_*"
            cursor = 0
            pod_checksums: dict[str, set[str]] = {}
            while True:
                cursor, keys = await self._client.scan(cursor, match=pattern, count=100)
                for key in keys:
                    # key: rt:warm:{kind}_{runtime_kind}:{checksum}
                    parts = key.split(":")
                    if len(parts) < 3:
                        continue
                    checksum = parts[-1]
                    members: set[str] = await self._client.smembers(key)  # type: ignore[misc]
                    for pod_id in members:
                        pod_checksums.setdefault(pod_id, set()).add(checksum)
                if cursor == 0:
                    break

            if pod_checksums:
                pipe = self._client.pipeline()
                for pod_id in pod_checksums:
                    pipe.hgetall(_load_key(pod_id))
                results = await pipe.execute()

                async with self._lock:
                    for pod_id, load_data in zip(pod_checksums.keys(), results, strict=False):
                        if not load_data:
                            continue
                        addr = load_data.get("addr", "")
                        active = int(load_data.get("active", 0))
                        max_c = int(load_data.get("max", 1))
                        checksums = pod_checksums[pod_id]
                        self._pods[pod_id] = PodState(
                            pod_id=pod_id,
                            addr=addr,
                            active=active,
                            max=max_c,
                            checksums=checksums,
                            last_seen=time.monotonic(),
                        )
                        for cs in checksums:
                            self._warm.setdefault(cs, set()).add(pod_id)

            self._bootstrap_done = True
        except Exception:
            logger.exception("registry bootstrap failed")

    async def _reconcile_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reconcile_interval)
            if self._healthy:
                await self._bootstrap()

    async def _reaper_loop(self) -> None:
        while True:
            await asyncio.sleep(self._ttl * 2)
            cutoff = time.monotonic() - self._ttl * 2
            async with self._lock:
                dead = [pid for pid, state in self._pods.items() if state.last_seen < cutoff]
                for pid in dead:
                    old = self._pods.pop(pid)
                    for cs in old.checksums:
                        if cs in self._warm:
                            self._warm[cs].discard(pid)
                            if not self._warm[cs]:
                                del self._warm[cs]


# ---------------------------------------------------------------------------
# RegistryQuery (gateway side — pull fallback)
# ---------------------------------------------------------------------------


class RegistryQuery:
    """Pull-based fallback for when RegistrySubscriber is unhealthy."""

    def __init__(self, redis_url: str) -> None:
        self._client: aioredis.Redis = aioredis.from_url(redis_url, decode_responses=True)

    async def warm_pods(self, kind: str, runtime_kind: str, checksum: str) -> list[str]:
        key = _warm_key(kind, runtime_kind, checksum)
        members: set[str] = await self._client.smembers(key)  # type: ignore[misc]
        return list(members)

    async def load(self, pod_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not pod_ids:
            return {}
        pipe = self._client.pipeline()
        for pid in pod_ids:
            pipe.hgetall(_load_key(pid))
        results = await pipe.execute()
        return {pid: data for pid, data in zip(pod_ids, results, strict=False) if data}

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# make_redis_saver (LangGraph checkpoint helper)
# ---------------------------------------------------------------------------


def make_redis_saver(redis_url: str) -> Any:
    """Create a LangGraph RedisSaver with the rt:ckpt: prefix."""
    try:
        from langgraph.checkpoint.redis import RedisSaver

        return RedisSaver.from_conn_string(redis_url, prefix="rt:ckpt:")
    except ImportError:
        logger.warning("langgraph-checkpoint-redis not installed; make_redis_saver returns None")
        return None
