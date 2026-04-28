"""HTTP client for deploy-api /v1/resolve with ETag + LRU caching and retry."""

from __future__ import annotations

import time
from collections import OrderedDict
from threading import Lock
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from runtime_common.schemas import ResolveResponse


class _CacheEntry:
    __slots__ = ("etag", "payload", "ts")

    def __init__(self, etag: str, payload: ResolveResponse, ts: float) -> None:
        self.etag = etag
        self.payload = payload
        self.ts = ts


class DeployApiClient:
    """Client for deploy-api.

    - resolve(kind, name, version, principal) → ResolveResponse
    - ETag-based conditional requests + local LRU cache
    - Exponential backoff retry on transient errors
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        cache_max: int = 256,
        cache_ttl_sec: float = 60.0,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._cache_max = cache_max
        self._cache_ttl = cache_ttl_sec
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = Lock()

    def _cache_key(self, kind: str, name: str, version: str | None, principal: str | None) -> str:
        return f"{kind}:{name}:{version or ''}:{principal or ''}"

    def _get_cached(self, key: str) -> _CacheEntry | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.monotonic() - entry.ts > self._cache_ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return entry

    def _set_cached(self, key: str, entry: _CacheEntry) -> None:
        with self._lock:
            self._cache[key] = entry
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=2.0),
        reraise=True,
    )
    async def resolve(
        self,
        kind: str,
        name: str,
        version: str | None = None,
        principal: str | None = None,
    ) -> ResolveResponse:
        key = self._cache_key(kind, name, version, principal)
        cached = self._get_cached(key)

        params: dict[str, Any] = {"kind": kind, "name": name}
        if version:
            params["version"] = version
        if principal:
            params["principal"] = principal

        headers = {}
        if cached is not None:
            headers["If-None-Match"] = cached.etag

        resp = await self._client.get("/v1/resolve", params=params, headers=headers)

        if resp.status_code == 304 and cached is not None:
            cached.ts = time.monotonic()
            return cached.payload

        resp.raise_for_status()
        data = resp.json()
        response = ResolveResponse.model_validate(data)
        etag = resp.headers.get("ETag", "")
        entry = _CacheEntry(etag=etag, payload=response, ts=time.monotonic())
        self._set_cached(key, entry)
        return response

    async def aclose(self) -> None:
        await self._client.aclose()
