"""Unit tests for runtime_common.instance_cache."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from runtime_common.instance_cache import InstanceCache, make_instance_key


class _FakeInstance:
    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _SyncCloseInstance:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _BadCloseInstance:
    async def aclose(self) -> None:
        raise RuntimeError("boom")


# ── make_instance_key ────────────────────────────────────────────────────────

class TestMakeInstanceKey:
    def test_no_user(self):
        assert make_instance_key("sha256:abc", None, None) == ("sha256:abc", None, None)

    def test_with_user(self):
        ts = datetime(2026, 4, 26, 10, 0, 0, tzinfo=UTC)
        key = make_instance_key("sha256:abc", "user-1", ts)
        assert key == ("sha256:abc", "user-1", ts.timestamp())

    def test_different_principals_different_keys(self):
        ts = datetime(2026, 4, 26, 10, 0, 0, tzinfo=UTC)
        k1 = make_instance_key("sha256:abc", "user-1", ts)
        k2 = make_instance_key("sha256:abc", "user-2", ts)
        assert k1 != k2

    def test_different_updated_at_different_keys(self):
        ts1 = datetime(2026, 4, 26, 10, 0, 0, tzinfo=UTC)
        ts2 = datetime(2026, 4, 26, 11, 0, 0, tzinfo=UTC)
        k1 = make_instance_key("sha256:abc", "user-1", ts1)
        k2 = make_instance_key("sha256:abc", "user-1", ts2)
        assert k1 != k2


# ── get_or_build ─────────────────────────────────────────────────────────────

class TestGetOrBuild:
    async def test_builds_on_miss(self):
        cache = InstanceCache(max_entries=4)
        key = make_instance_key("sha256:a", None, None)
        calls = 0

        def builder():
            nonlocal calls
            calls += 1
            return _FakeInstance("a")

        result = await cache.get_or_build(key, builder)
        assert isinstance(result, _FakeInstance)
        assert result.label == "a"
        assert calls == 1

    async def test_hit_skips_builder(self):
        cache = InstanceCache(max_entries=4)
        key = make_instance_key("sha256:a", None, None)
        calls = 0

        def builder():
            nonlocal calls
            calls += 1
            return _FakeInstance("a")

        first = await cache.get_or_build(key, builder)
        second = await cache.get_or_build(key, builder)
        assert first is second
        assert calls == 1

    async def test_async_builder(self):
        cache = InstanceCache(max_entries=4)
        key = make_instance_key("sha256:a", None, None)

        async def builder():
            return _FakeInstance("async")

        result = await cache.get_or_build(key, builder)
        assert result.label == "async"

    async def test_different_keys_independent(self):
        cache = InstanceCache(max_entries=4)
        k1 = make_instance_key("sha256:a", None, None)
        k2 = make_instance_key("sha256:b", None, None)

        first = await cache.get_or_build(k1, lambda: _FakeInstance("a"))
        second = await cache.get_or_build(k2, lambda: _FakeInstance("b"))
        assert first is not second
        assert first.label == "a"
        assert second.label == "b"


# ── LRU eviction + close ─────────────────────────────────────────────────────

class TestEviction:
    async def test_lru_eviction_calls_aclose(self):
        cache = InstanceCache(max_entries=2)
        a = _FakeInstance("a")
        b = _FakeInstance("b")
        c = _FakeInstance("c")

        await cache.get_or_build(make_instance_key("ck:a", None, None), lambda: a)
        await cache.get_or_build(make_instance_key("ck:b", None, None), lambda: b)
        # 'a' is the least-recently-used; inserting c evicts it
        await cache.get_or_build(make_instance_key("ck:c", None, None), lambda: c)

        assert a.closed is True
        assert b.closed is False
        assert c.closed is False
        assert len(cache) == 2

    async def test_hit_refreshes_lru_order(self):
        cache = InstanceCache(max_entries=2)
        a = _FakeInstance("a")
        b = _FakeInstance("b")
        c = _FakeInstance("c")

        ka = make_instance_key("ck:a", None, None)
        kb = make_instance_key("ck:b", None, None)
        kc = make_instance_key("ck:c", None, None)

        await cache.get_or_build(ka, lambda: a)
        await cache.get_or_build(kb, lambda: b)
        # touch 'a' so it becomes most recent; 'b' is now LRU
        await cache.get_or_build(ka, lambda: _FakeInstance("should-not-build"))
        await cache.get_or_build(kc, lambda: c)

        assert b.closed is True
        assert a.closed is False

    async def test_sync_close_called(self):
        cache = InstanceCache(max_entries=1)
        a = _SyncCloseInstance()
        b = _SyncCloseInstance()

        await cache.get_or_build(make_instance_key("ck:a", None, None), lambda: a)
        await cache.get_or_build(make_instance_key("ck:b", None, None), lambda: b)

        assert a.closed is True
        assert b.closed is False

    async def test_bad_close_does_not_propagate(self):
        cache = InstanceCache(max_entries=1)
        bad = _BadCloseInstance()
        good = _FakeInstance("good")

        await cache.get_or_build(make_instance_key("ck:bad", None, None), lambda: bad)
        # eviction calls bad.aclose() which raises — must not bubble up
        await cache.get_or_build(make_instance_key("ck:good", None, None), lambda: good)
        assert len(cache) == 1


# ── Invalidation ─────────────────────────────────────────────────────────────

class TestInvalidate:
    async def test_invalidate_checksum_drops_all_principals(self):
        cache = InstanceCache(max_entries=8)
        ts = datetime(2026, 4, 26, tzinfo=UTC)
        a1 = _FakeInstance("a-user1")
        a2 = _FakeInstance("a-user2")
        b1 = _FakeInstance("b-user1")

        await cache.get_or_build(make_instance_key("ck:a", "u1", ts), lambda: a1)
        await cache.get_or_build(make_instance_key("ck:a", "u2", ts), lambda: a2)
        await cache.get_or_build(make_instance_key("ck:b", "u1", ts), lambda: b1)

        await cache.invalidate_checksum("ck:a")

        assert a1.closed is True
        assert a2.closed is True
        assert b1.closed is False
        assert len(cache) == 1

    async def test_invalidate_principal_drops_only_one(self):
        cache = InstanceCache(max_entries=8)
        ts1 = datetime(2026, 4, 26, 10, tzinfo=UTC)
        ts2 = datetime(2026, 4, 26, 11, tzinfo=UTC)
        old = _FakeInstance("old")
        new = _FakeInstance("new")
        other = _FakeInstance("other")

        await cache.get_or_build(make_instance_key("ck:a", "u1", ts1), lambda: old)
        await cache.get_or_build(make_instance_key("ck:a", "u1", ts2), lambda: new)
        await cache.get_or_build(make_instance_key("ck:a", "u2", ts1), lambda: other)

        await cache.invalidate_principal("ck:a", "u1")

        assert old.closed is True
        assert new.closed is True
        assert other.closed is False
        assert len(cache) == 1

    async def test_clear_drops_everything(self):
        cache = InstanceCache(max_entries=4)
        a = _FakeInstance("a")
        b = _FakeInstance("b")
        await cache.get_or_build(make_instance_key("ck:a", None, None), lambda: a)
        await cache.get_or_build(make_instance_key("ck:b", None, None), lambda: b)

        await cache.clear()

        assert a.closed is True
        assert b.closed is True
        assert len(cache) == 0


# ── Validation ───────────────────────────────────────────────────────────────

def test_max_entries_must_be_positive():
    with pytest.raises(ValueError, match="max_entries"):
        InstanceCache(max_entries=0)
