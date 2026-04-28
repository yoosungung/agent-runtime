from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from threading import Lock

import httpx

from runtime_common.schemas import Principal


class AuthClient:
    """Thin HTTP client against the auth service. Gateways inject this into request handlers."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 2.0,
        cache_ttl_sec: float = 5.0,
        cache_max: int = 1024,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._cache_ttl = cache_ttl_sec
        self._cache_max = cache_max
        self._cache: OrderedDict[str, tuple[Principal, float]] = OrderedDict()
        self._lock = Lock()

    def _cache_key(self, token: str, grace_sec: int) -> str:
        return hashlib.sha256(f"{token}:{grace_sec}".encode()).hexdigest()

    def _get_cached(self, key: str) -> Principal | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            principal, ts = entry
            if time.monotonic() - ts > self._cache_ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return principal

    def _set_cached(self, key: str, principal: Principal) -> None:
        with self._lock:
            self._cache[key] = (principal, time.monotonic())
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)

    async def verify(self, token: str, grace_sec: int = 0) -> Principal:
        key = self._cache_key(token, grace_sec)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        resp = await self._client.post("/verify", json={"token": token, "grace_sec": grace_sec})
        resp.raise_for_status()
        principal = Principal.model_validate(resp.json())
        self._set_cached(key, principal)
        return principal

    async def revoke_tokens(self, user_id: int) -> None:
        """Revoke all refresh tokens for a given user (admin bridge)."""
        resp = await self._client.post(f"/v1/admin/revoke-tokens?user_id={user_id}")
        resp.raise_for_status()

    async def invalidate_access(self, user_id: int) -> None:
        """Invalidate the auth-side access cache for a user (admin bridge).

        Called by backend after grant/revoke writes so subsequent /verify
        calls see the fresh user_resource_access rows instead of the cache TTL
        window's pre-write snapshot.
        """
        resp = await self._client.post(f"/v1/admin/invalidate-access?user_id={user_id}")
        resp.raise_for_status()

    async def refresh(self, refresh_token: str) -> dict:
        """Exchange a refresh token for a new token pair."""
        resp = await self._client.post("/refresh", json={"refresh_token": refresh_token})
        resp.raise_for_status()
        return resp.json()

    async def logout(self, refresh_token: str) -> None:
        """Revoke a refresh token (logout)."""
        resp = await self._client.post("/logout", json={"refresh_token": refresh_token})
        resp.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()
