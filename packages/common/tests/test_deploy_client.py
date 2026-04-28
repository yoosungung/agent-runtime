"""Unit tests for runtime_common.deploy_client."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from runtime_common.deploy_client import DeployApiClient
from runtime_common.schemas import ResolveResponse


def _make_source():
    return {
        "kind": "agent",
        "name": "chat-bot",
        "version": "v1",
        "runtime_pool": "agent:compiled_graph",
        "entrypoint": "app:build",
        "bundle_uri": "s3://b/chat-bot.zip",
        "checksum": "sha256:abc",
    }


def _make_response(source: dict, status: int = 200, etag: str = 'W/"sha256:abc|0"') -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.headers = httpx.Headers({"ETag": etag})
    resp.json.return_value = {"source": source, "user": None}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def client():
    c = DeployApiClient("http://deploy-api", cache_max=4, cache_ttl_sec=60.0)
    return c


@pytest.mark.asyncio
async def test_resolve_success(client):
    source = _make_source()
    resp = _make_response(source)

    with patch.object(client._client, "get", new=AsyncMock(return_value=resp)):
        result = await client.resolve("agent", "chat-bot", "v1")

    assert isinstance(result, ResolveResponse)
    assert result.source.name == "chat-bot"
    assert result.user is None


@pytest.mark.asyncio
async def test_resolve_etag_cache_hit(client):
    source = _make_source()
    etag = 'W/"sha256:abc|0"'
    resp_first = _make_response(source, etag=etag)

    # Second response: 304 Not Modified
    resp_304 = MagicMock(spec=httpx.Response)
    resp_304.status_code = 304
    resp_304.headers = httpx.Headers({"ETag": etag})

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return resp_first
        return resp_304

    with patch.object(client._client, "get", side_effect=mock_get):
        r1 = await client.resolve("agent", "chat-bot", "v1")
        r2 = await client.resolve("agent", "chat-bot", "v1")

    assert r1.source.name == r2.source.name
    assert call_count == 2


@pytest.mark.asyncio
async def test_resolve_different_principals_separate_cache(client):
    source = _make_source()

    calls = []

    async def mock_get(path, **kwargs):
        calls.append(kwargs.get("params", {}))
        return _make_response(source)

    with patch.object(client._client, "get", side_effect=mock_get):
        await client.resolve("agent", "chat-bot", "v1", principal="u1")
        await client.resolve("agent", "chat-bot", "v1", principal="u2")

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_resolve_stale_ttl_sends_fresh_request(monkeypatch):
    """After cache_ttl_sec elapses, the next call must issue a new HTTP request."""
    import time as _time

    # Use a very short TTL so the cache entry expires immediately after insertion
    client = DeployApiClient("http://deploy-api", cache_max=4, cache_ttl_sec=0.001)
    source = _make_source()

    # Capture a fixed "now" then advance it past the TTL for the second call
    base_ts = _time.monotonic()
    call_count = 0

    def _fake_monotonic() -> float:
        # First call (cache write): base_ts. Second call (cache read): base_ts + 10s → expired.
        nonlocal call_count
        call_count += 1
        return base_ts if call_count <= 2 else base_ts + 10.0

    import runtime_common.deploy_client as dc_mod

    monkeypatch.setattr(dc_mod.time, "monotonic", _fake_monotonic)

    http_calls = 0

    async def mock_get(path, **kwargs):
        nonlocal http_calls
        http_calls += 1
        return _make_response(source)

    with patch.object(client._client, "get", side_effect=mock_get):
        await client.resolve("agent", "chat-bot", "v1")
        await client.resolve("agent", "chat-bot", "v1")

    assert http_calls == 2, "stale cache entry should trigger a new HTTP GET"
    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_retry_on_transient_503():
    """tenacity should retry on 503 and ultimately return success on the third attempt."""
    source = _make_source()
    call_count = 0

    def _raise_for_status_503() -> None:
        raise httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock())

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            resp_503 = MagicMock(spec=httpx.Response)
            resp_503.status_code = 503
            resp_503.headers = httpx.Headers({})
            resp_503.raise_for_status = _raise_for_status_503
            return resp_503
        return _make_response(source)

    client = DeployApiClient("http://deploy-api", cache_max=4, cache_ttl_sec=60.0)
    with patch.object(client._client, "get", side_effect=mock_get):
        # We accept up to ~0.4s of real sleep from tenacity; it's acceptable.
        result = await client.resolve("agent", "chat-bot", "v1")

    assert result.source.name == "chat-bot"
    assert call_count == 3
    await client.aclose()
