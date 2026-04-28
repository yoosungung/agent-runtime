"""Async LRU cache for factory-built runtime instances.

Why this exists
---------------
A bundle's `factory(cfg, secrets)` builds the framework-native object
(LangGraph CompiledGraph, ADK Runner, FastMCP server, ...). Without caching,
every invoke would rebuild the graph and re-open infra (DB connection pools,
checkpointer sessions, embedding clients), which is unsustainable.

This cache holds the built instance keyed by ``(checksum, principal_id, user.updated_at)``
so the factory is invoked at most once per (source version × user override version).

Cache key
---------
- ``checksum``        — pins to a specific source_meta version (immutable per checksum).
- ``principal_id``    — separates per-principal instances when user_meta exists.
- ``user_updated_at`` — invalidates this principal's entry when their user_meta changes.

When user_meta is absent, ``principal_id`` and ``user_updated_at`` should both be ``None``,
so all principals without overrides share a single cached instance.

Eviction
--------
On LRU eviction (or explicit invalidate), the cache best-effort calls ``aclose()`` then
``close()`` on the evicted instance — bundle authors can surface those methods on their
returned object to release connection pools.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

type InstanceKey = tuple[str | None, str | None, float | None]
type Builder = Callable[[], Any] | Callable[[], Awaitable[Any]]


def make_instance_key(
    checksum: str | None,
    principal_id: str | None,
    user_updated_at: datetime | None,
) -> InstanceKey:
    """Build an instance cache key.

    When user_meta is absent, callers should pass ``principal_id=None`` and
    ``user_updated_at=None`` so all principals without overrides share one entry.
    """
    ts = user_updated_at.timestamp() if user_updated_at else None
    return (checksum, principal_id, ts)


class InstanceCache:
    """Async LRU cache of factory-built instances. Thread-safe within a single event loop."""

    def __init__(self, max_entries: int) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._entries: OrderedDict[InstanceKey, Any] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get_or_build(self, key: InstanceKey, builder: Builder) -> Any:
        """Return the cached instance for ``key`` or call ``builder()`` and cache its result.

        ``builder`` may be sync or async (awaitable). The lock is held for the full
        build to deduplicate concurrent cold-starts on the same key — simple and safe.
        Once warm, cache hits are fast and contention is minimal.
        """
        evicted: list[Any] = []
        async with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]

            instance = builder()
            if inspect.isawaitable(instance):
                instance = await instance

            self._entries[key] = instance
            self._entries.move_to_end(key)

            while len(self._entries) > self._max_entries:
                _, victim = self._entries.popitem(last=False)
                evicted.append(victim)

        for victim in evicted:
            await _close_instance(victim)
        return instance

    async def invalidate_checksum(self, checksum: str) -> None:
        """Drop all entries for ``checksum``. Use when a bundle is removed or replaced."""
        evicted: list[Any] = []
        async with self._lock:
            victim_keys = [k for k in self._entries if k[0] == checksum]
            for k in victim_keys:
                evicted.append(self._entries.pop(k))
        for victim in evicted:
            await _close_instance(victim)

    async def invalidate_principal(self, checksum: str, principal_id: str) -> None:
        """Drop all entries for ``(checksum, principal_id)`` regardless of updated_at."""
        evicted: list[Any] = []
        async with self._lock:
            victim_keys = [k for k in self._entries if k[0] == checksum and k[1] == principal_id]
            for k in victim_keys:
                evicted.append(self._entries.pop(k))
        for victim in evicted:
            await _close_instance(victim)

    async def clear(self) -> None:
        """Drop every entry. Call from lifespan shutdown."""
        async with self._lock:
            evicted = list(self._entries.values())
            self._entries.clear()
        for victim in evicted:
            await _close_instance(victim)

    def __len__(self) -> int:
        return len(self._entries)

    def keys(self) -> list[InstanceKey]:
        """Snapshot of current keys (for tests / introspection)."""
        return list(self._entries.keys())


async def _close_instance(instance: Any) -> None:
    """Best-effort cleanup. Tries ``aclose()`` then ``close()``. Swallows exceptions."""
    if instance is None:
        return
    try:
        aclose = getattr(instance, "aclose", None)
        if callable(aclose):
            result = aclose()
            if inspect.isawaitable(result):
                await result
            return
        close = getattr(instance, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
    except Exception as exc:
        logger.warning("instance_cache_close_failed", extra={"error": str(exc)})
