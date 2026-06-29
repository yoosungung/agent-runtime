"""Redis profile lock — one invoke per agent_name at a time."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)

LOCK_PREFIX = "rt:lock:hermes:profile:"

_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def lock_key(agent_name: str) -> str:
    return f"{LOCK_PREFIX}{agent_name}"


@dataclass(frozen=True)
class LockHandle:
    key: str
    token: str


class ProfileLockContended(Exception):
    """Raised when profile lock cannot be acquired."""

    def __init__(self, agent_name: str) -> None:
        super().__init__(agent_name)
        self.agent_name = agent_name


@dataclass
class _MemoryEntry:
    token: str
    expires_at: float


class MemoryProfileLock:
    """In-process lock for unit tests and local dev without Redis."""

    def __init__(self, *, ttl_sec: float = 330) -> None:
        self._ttl_sec = ttl_sec
        self._locks: dict[str, _MemoryEntry] = {}
        self._guard = asyncio.Lock()

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._locks.items() if v.expires_at <= now]
        for k in expired:
            self._locks.pop(k, None)

    async def try_acquire(self, agent_name: str) -> LockHandle | None:
        async with self._guard:
            self._purge_expired()
            key = lock_key(agent_name)
            if key in self._locks:
                return None
            token = uuid.uuid4().hex
            self._locks[key] = _MemoryEntry(
                token=token,
                expires_at=time.monotonic() + self._ttl_sec,
            )
            return LockHandle(key=key, token=token)

    async def release(self, handle: LockHandle) -> None:
        async with self._guard:
            entry = self._locks.get(handle.key)
            if entry is None or entry.token != handle.token:
                return
            self._locks.pop(handle.key, None)

    @asynccontextmanager
    async def hold(self, agent_name: str) -> AsyncIterator[LockHandle]:
        handle = await self.try_acquire(agent_name)
        if handle is None:
            raise ProfileLockContended(agent_name)
        try:
            yield handle
        finally:
            await self.release(handle)


class RedisProfileLock:
    """Redis SET NX lock with token-safe release."""

    def __init__(self, redis_url: str, *, ttl_sec: int = 330) -> None:
        self._redis_url = redis_url
        self._ttl_sec = ttl_sec
        self._client = None

    async def _get_client(self):
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def try_acquire(self, agent_name: str) -> LockHandle | None:
        client = await self._get_client()
        key = lock_key(agent_name)
        token = uuid.uuid4().hex
        ok = await client.set(key, token, nx=True, ex=self._ttl_sec)
        if not ok:
            return None
        return LockHandle(key=key, token=token)

    async def release(self, handle: LockHandle) -> None:
        client = await self._get_client()
        await client.eval(_RELEASE_LUA, 1, handle.key, handle.token)

    @asynccontextmanager
    async def hold(self, agent_name: str) -> AsyncIterator[LockHandle]:
        handle = await self.try_acquire(agent_name)
        if handle is None:
            raise ProfileLockContended(agent_name)
        try:
            yield handle
        finally:
            await self.release(handle)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def build_profile_lock(redis_url: str | None, *, ttl_sec: int) -> MemoryProfileLock | RedisProfileLock:
    if redis_url:
        return RedisProfileLock(redis_url, ttl_sec=ttl_sec)
    logger.warning("profile_lock_memory_fallback", extra={"reason": "REDIS_URL unset"})
    return MemoryProfileLock(ttl_sec=float(ttl_sec))
