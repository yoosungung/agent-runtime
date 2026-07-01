"""Unit tests for K8sPoolManager KEDA optional behaviour."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from kubernetes_asyncio.client.exceptions import ApiException

from backend.k8s_client import K8sPoolManager, keda_crd_available
from backend.settings import Settings


def _settings() -> Settings:
    return Settings(
        POSTGRES_DSN="sqlite+aiosqlite:///:memory:",
        K8S_IN_CLUSTER=False,
        K8S_RUNTIME_NAMESPACE="runtime",
    )


@pytest.mark.asyncio
async def test_keda_crd_available_true_when_crd_exists() -> None:
    ext = AsyncMock()
    ext.read_custom_resource_definition = AsyncMock(return_value=MagicMock())
    assert await keda_crd_available(ext) is True


@pytest.mark.asyncio
async def test_keda_crd_available_false_on_404() -> None:
    ext = AsyncMock()
    ext.read_custom_resource_definition = AsyncMock(
        side_effect=ApiException(status=404, reason="Not Found")
    )
    assert await keda_crd_available(ext) is False


@pytest.mark.asyncio
async def test_create_pool_skips_scaled_object_when_keda_absent() -> None:
    api_client = MagicMock()
    manager = K8sPoolManager(api_client, _settings())
    manager._apps.create_namespaced_deployment = AsyncMock()
    manager._core.create_namespaced_service = AsyncMock()
    manager._custom.create_namespaced_custom_object = AsyncMock()
    manager._policy.create_namespaced_pod_disruption_budget = AsyncMock()
    manager._is_keda_available = AsyncMock(return_value=False)  # type: ignore[method-assign]

    await manager.create_pool(
        kind="mcp",
        slug="test-v1",
        image_uri="ghcr.io/example/mcp:v1",
        image_digest=None,
        replicas_max=3,
        resources=None,
        image_pull_secret=None,
        env_vars=None,
        deploy_api_url="http://deploy-api:8080",
    )

    manager._custom.create_namespaced_custom_object.assert_not_called()
    manager._policy.create_namespaced_pod_disruption_budget.assert_called_once()


@pytest.mark.asyncio
async def test_create_pool_creates_scaled_object_when_keda_present() -> None:
    api_client = MagicMock()
    manager = K8sPoolManager(api_client, _settings())
    manager._apps.create_namespaced_deployment = AsyncMock()
    manager._core.create_namespaced_service = AsyncMock()
    manager._custom.create_namespaced_custom_object = AsyncMock()
    manager._policy.create_namespaced_pod_disruption_budget = AsyncMock()
    manager._is_keda_available = AsyncMock(return_value=True)  # type: ignore[method-assign]

    await manager.create_pool(
        kind="mcp",
        slug="test-v1",
        image_uri="ghcr.io/example/mcp:v1",
        image_digest=None,
        replicas_max=3,
        resources=None,
        image_pull_secret=None,
        env_vars=None,
        deploy_api_url="http://deploy-api:8080",
    )

    manager._custom.create_namespaced_custom_object.assert_called_once()
