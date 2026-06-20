"""Tests for infra K8s reconcile helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.infra_reconciler import reconcile_infra


@pytest.mark.asyncio
async def test_reconcile_infra_applies_env_and_secrets():
    k8s = MagicMock()
    k8s.read_infra_secrets = AsyncMock(return_value={"OPENAI_API_KEY": "existing"})
    k8s.apply_infra_configmap = AsyncMock()
    k8s.apply_infra_secret = AsyncMock()
    k8s.restart_infra_pool_deployments = AsyncMock(return_value=["agent-pool-adk"])

    restarted = await reconcile_infra(
        k8s,
        env={"opik_url": "http://opik/api"},
        secrets_patch={"ANTHROPIC_API_KEY": "sk-new"},
    )

    k8s.apply_infra_configmap.assert_awaited_once_with({"OPIK_URL": "http://opik/api"})
    k8s.apply_infra_secret.assert_awaited_once_with(
        {"OPENAI_API_KEY": "existing", "ANTHROPIC_API_KEY": "sk-new"}
    )
    assert restarted == ["agent-pool-adk"]


@pytest.mark.asyncio
async def test_reconcile_infra_preserves_secrets_when_no_patch():
    k8s = MagicMock()
    k8s.read_infra_secrets = AsyncMock(return_value={"OPENAI_API_KEY": "sk-x"})
    k8s.apply_infra_configmap = AsyncMock()
    k8s.apply_infra_secret = AsyncMock()
    k8s.restart_infra_pool_deployments = AsyncMock(return_value=[])

    await reconcile_infra(k8s, env={}, secrets_patch=None)

    k8s.apply_infra_secret.assert_awaited_once_with({"OPENAI_API_KEY": "sk-x"})
