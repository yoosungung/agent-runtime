"""Sliding-window rate limiter for gateway per-principal limits.

Usage:
    limiter = RateLimiter(max_calls=60, window_sec=60.0)
    if not limiter.allow("user-123:agent-name"):
        raise HTTPException(429, ...)
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    """Token-bucket approximation via sliding-window counter (in-process).

    Thread-safe. Each key gets an independent sliding window.

    Args:
        max_calls:  Maximum allowed calls within the window.
        window_sec: Rolling window duration in seconds.
    """

    def __init__(self, max_calls: int, window_sec: float) -> None:
        self._max = max_calls
        self._window = window_sec
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Return True if the call is permitted; False if the rate limit is exceeded."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = deque()
            bucket = self._buckets[key]
            # Evict timestamps outside the window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                return False
            bucket.append(now)
            return True

    def remaining(self, key: str) -> int:
        """Return how many calls remain in the current window for the key."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                return self._max
            count = sum(1 for ts in bucket if ts > cutoff)
            return max(0, self._max - count)
