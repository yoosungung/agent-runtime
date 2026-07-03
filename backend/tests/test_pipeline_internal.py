"""Tests for cluster-internal pipeline binding API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import app

BINDING = {
    "tenant": "acme",
    "project_id": "550e8400-e29b-41d4-a716-446655440000",
    "project_slug": "docs",
    "rag": {"index_namespace": "path_graph_acme_product-docs"},
}


@pytest.mark.asyncio
async def test_internal_binding_requires_agent_pool_caller():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/pipeline/tenants/acme/projects/p1/binding",
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_internal_binding_returns_payload():
    transport = ASGITransport(app=app)
    with patch(
        "backend.routers.pipeline_internal.get_tenant_project_binding",
        new=AsyncMock(return_value=BINDING),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/internal/v1/pipeline/tenants/acme/projects/p1/binding",
                headers={"X-Runtime-Caller": "agent-pool"},
            )
    assert resp.status_code == 200
    assert resp.json()["project_slug"] == "docs"
