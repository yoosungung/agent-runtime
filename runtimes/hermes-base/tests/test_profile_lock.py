"""Profile lock tests — Memory + Redis mock (TDD)."""

from __future__ import annotations

import asyncio

import pytest

from hermes_base.profile_lock import (
    LockHandle,
    MemoryProfileLock,
    ProfileLockContended,
    lock_key,
)


def test_lock_key_format() -> None:
    assert lock_key("my-bot") == "rt:lock:hermes:profile:my-bot"


@pytest.mark.asyncio()
async def test_memory_lock_acquire_and_release() -> None:
    lock = MemoryProfileLock(ttl_sec=60)
    h1 = await lock.try_acquire("agent-a")
    assert h1 is not None
    h2 = await lock.try_acquire("agent-a")
    assert h2 is None
    await lock.release(h1)
    h3 = await lock.try_acquire("agent-a")
    assert h3 is not None


@pytest.mark.asyncio()
async def test_memory_lock_different_agents_parallel() -> None:
    lock = MemoryProfileLock(ttl_sec=60)
    a = await lock.try_acquire("agent-a")
    b = await lock.try_acquire("agent-b")
    assert a is not None and b is not None


@pytest.mark.asyncio()
async def test_memory_lock_context_manager() -> None:
    lock = MemoryProfileLock(ttl_sec=60)
    async with lock.hold("agent-x") as handle:
        assert isinstance(handle, LockHandle)
        with pytest.raises(ProfileLockContended):
            async with lock.hold("agent-x"):
                pass  # pragma: no cover
    async with lock.hold("agent-x"):
        pass


@pytest.mark.asyncio()
async def test_memory_lock_ttl_expires() -> None:
    lock = MemoryProfileLock(ttl_sec=0.05)
    h1 = await lock.try_acquire("agent-ttl")
    assert h1 is not None
    await asyncio.sleep(0.08)
    h2 = await lock.try_acquire("agent-ttl")
    assert h2 is not None


@pytest.mark.asyncio()
async def test_release_wrong_token_is_noop() -> None:
    lock = MemoryProfileLock(ttl_sec=60)
    h1 = await lock.try_acquire("agent-z")
    assert h1 is not None
    bad = LockHandle(key=h1.key, token="wrong")
    await lock.release(bad)
    assert await lock.try_acquire("agent-z") is None
