from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import ApiNoCacheMiddleware, app


@pytest.mark.asyncio
async def test_api_responses_have_no_store_cache_control():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert "cache-control" not in {k.lower() for k in resp.headers.keys()}


@pytest.mark.asyncio
async def test_api_no_cache_middleware_sets_response_headers():
    captured: dict[str, object] = {}

    async def inner_app(scope, receive, send):
        async def respond():
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b"{}"})

        await respond()

    middleware = ApiNoCacheMiddleware(inner_app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["headers"] = dict(message["headers"])

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/pipeline/projects/abc",
        "headers": [],
    }
    await middleware(scope, receive, send)

    headers = {k.decode().lower(): v.decode() for k, v in captured["headers"].items()}
    assert headers["cache-control"] == "no-store"
    assert headers["pragma"] == "no-cache"
