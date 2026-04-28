"""Tests for auth service."""

import time

from auth.app import _AccessCache, _RateLimiter
from runtime_common.schemas import ResourceRef


class TestRateLimiter:
    def test_allows_under_limit(self):
        limiter = _RateLimiter(max_attempts=3, window_sec=60.0)
        assert not limiter.is_blocked("user1")

    def test_blocks_when_exceeded(self):
        limiter = _RateLimiter(max_attempts=3, window_sec=60.0)
        limiter.record_failure("user1")
        limiter.record_failure("user1")
        limiter.record_failure("user1")
        assert limiter.is_blocked("user1")

    def test_not_blocked_until_limit_reached(self):
        limiter = _RateLimiter(max_attempts=3, window_sec=60.0)
        limiter.record_failure("user1")
        limiter.record_failure("user1")
        assert not limiter.is_blocked("user1")
        limiter.record_failure("user1")
        assert limiter.is_blocked("user1")

    def test_success_resets_failures(self):
        limiter = _RateLimiter(max_attempts=3, window_sec=60.0)
        limiter.record_failure("user1")
        limiter.record_failure("user1")
        limiter.record_failure("user1")
        assert limiter.is_blocked("user1")
        limiter.record_success("user1")
        assert not limiter.is_blocked("user1")

    def test_evicts_old_entries(self):
        # Use a tiny window so past entries fall out immediately
        limiter = _RateLimiter(max_attempts=2, window_sec=0.01)
        limiter.record_failure("user1")
        limiter.record_failure("user1")
        # Give old entries time to expire
        time.sleep(0.05)
        # is_blocked calls _evict_old internally, so old entries should be gone
        assert not limiter.is_blocked("user1")

    def test_different_keys_are_independent(self):
        limiter = _RateLimiter(max_attempts=2, window_sec=60.0)
        limiter.record_failure("alice")
        limiter.record_failure("alice")
        assert limiter.is_blocked("alice")
        assert not limiter.is_blocked("bob")

    def test_success_on_unknown_key_is_noop(self):
        limiter = _RateLimiter(max_attempts=3, window_sec=60.0)
        limiter.record_success("nobody")  # should not raise
        assert not limiter.is_blocked("nobody")


class TestAccessCache:
    def test_miss_returns_none(self):
        cache = _AccessCache(ttl_sec=10.0)
        assert cache.get(999) is None

    def test_set_get(self):
        cache = _AccessCache(ttl_sec=10.0)
        refs = [ResourceRef(kind="agent", name="chat-bot")]
        cache.set(1, refs)
        result = cache.get(1)
        assert result is not None
        assert len(result) == 1
        assert result[0].name == "chat-bot"

    def test_expired_returns_none(self):
        cache = _AccessCache(ttl_sec=0.01)
        refs = [ResourceRef(kind="mcp", name="rag")]
        cache.set(2, refs)
        time.sleep(0.05)
        assert cache.get(2) is None

    def test_lru_eviction(self):
        cache = _AccessCache(ttl_sec=60.0, max_size=2)
        refs = [ResourceRef(kind="agent", name="bot")]
        cache.set(1, refs)
        cache.set(2, refs)
        cache.set(3, refs)  # should evict key 1
        assert cache.get(1) is None
        assert cache.get(2) is not None
        assert cache.get(3) is not None

    def test_get_refreshes_lru_order(self):
        cache = _AccessCache(ttl_sec=60.0, max_size=2)
        refs = [ResourceRef(kind="agent", name="bot")]
        cache.set(1, refs)
        cache.set(2, refs)
        # Access key 1 to move it to the end (most recently used)
        cache.get(1)
        # Now set key 3 — key 2 should be evicted (oldest), not key 1
        cache.set(3, refs)
        assert cache.get(1) is not None
        assert cache.get(2) is None
        assert cache.get(3) is not None

    def test_overwrite_same_key(self):
        cache = _AccessCache(ttl_sec=60.0)
        refs_a = [ResourceRef(kind="agent", name="a")]
        refs_b = [ResourceRef(kind="mcp", name="b")]
        cache.set(1, refs_a)
        cache.set(1, refs_b)
        result = cache.get(1)
        assert result is not None
        assert result[0].kind == "mcp"
