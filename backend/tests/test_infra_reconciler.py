"""Tests for infra K8s reconcile helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.infra_reconciler import reconcile_infra
from runtime_common.db.models import InfraMetaRow, LlmPresetRow


@pytest.mark.asyncio
async def test_reconcile_infra_applies_env_and_secrets():
    k8s = MagicMock()
    k8s.read_infra_secrets = AsyncMock(return_value={"OPENAI_API_KEY": "existing"})
    k8s.apply_infra_configmap = AsyncMock()
    k8s.apply_infra_secret = AsyncMock()
    k8s.restart_infra_pool_deployments = AsyncMock(return_value=["agent-pool-adk"])

    infra_row = InfraMetaRow(scope="global", scope_key="", env={"OPIK_URL": "http://opik/api"}, secret_keys=["OPENAI_API_KEY"])
    db = AsyncMock()
    
    mock_infra_res = MagicMock()
    mock_infra_res.scalar_one_or_none.return_value = infra_row
    mock_presets_res = MagicMock()
    mock_presets_res.scalars.return_value.all.return_value = []
    
    db.execute.side_effect = [mock_infra_res, mock_presets_res]

    restarted = await reconcile_infra(
        k8s,
        db,
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

    infra_row = InfraMetaRow(scope="global", scope_key="", env={}, secret_keys=["OPENAI_API_KEY"])
    db = AsyncMock()
    
    mock_infra_res = MagicMock()
    mock_infra_res.scalar_one_or_none.return_value = infra_row
    mock_presets_res = MagicMock()
    mock_presets_res.scalars.return_value.all.return_value = []
    
    db.execute.side_effect = [mock_infra_res, mock_presets_res]

    await reconcile_infra(k8s, db, secrets_patch=None)

    k8s.apply_infra_secret.assert_awaited_once_with({"OPENAI_API_KEY": "sk-x"})


@pytest.mark.asyncio
async def test_reconcile_infra_legacy_key_migration():
    k8s = MagicMock()
    k8s.read_infra_secrets = AsyncMock(return_value={"OPENAI_API_KEY": "legacy-key"})
    k8s.apply_infra_configmap = MagicMock() # not awaited but mock
    k8s.apply_infra_configmap = AsyncMock()
    k8s.apply_infra_secret = AsyncMock()
    k8s.restart_infra_pool_deployments = AsyncMock(return_value=[])

    infra_row = InfraMetaRow(scope="global", scope_key="", env={})
    preset = LlmPresetRow(
        name="DEFAULT_PRESET",
        mode="frontier",
        frontier_provider="openai",
        model_id="gpt-4o",
        is_default=True,
    )

    db = AsyncMock()
    mock_infra_res = MagicMock()
    mock_infra_res.scalar_one_or_none.return_value = infra_row
    mock_presets_res = MagicMock()
    mock_presets_res.scalars.return_value.all.return_value = [preset]
    db.execute.side_effect = [mock_infra_res, mock_presets_res]

    await reconcile_infra(k8s, db)

    k8s.apply_infra_secret.assert_awaited_once()
    saved_secrets = k8s.apply_infra_secret.call_args[0][0]
    # legacy OPENAI_API_KEY copied to LLM_PRESET_DEFAULT_PRESET_API_KEY
    assert saved_secrets["LLM_PRESET_DEFAULT_PRESET_API_KEY"] == "legacy-key"
    assert saved_secrets["OPENAI_API_KEY"] == "legacy-key"


@pytest.mark.asyncio
async def test_reconcile_infra_default_preset_projection():
    k8s = MagicMock()
    k8s.read_infra_secrets = AsyncMock(return_value={})
    k8s.apply_infra_configmap = AsyncMock()
    k8s.apply_infra_secret = AsyncMock()
    k8s.restart_infra_pool_deployments = AsyncMock(return_value=[])

    infra_row = InfraMetaRow(scope="global", scope_key="", env={})
    preset = LlmPresetRow(
        name="DEFAULT_PRESET",
        mode="frontier",
        frontier_provider="anthropic",
        model_id="claude-3-5-sonnet",
        is_default=True,
    )

    db = AsyncMock()
    mock_infra_res = MagicMock()
    mock_infra_res.scalar_one_or_none.return_value = infra_row
    mock_presets_res = MagicMock()
    mock_presets_res.scalars.return_value.all.return_value = [preset]
    db.execute.side_effect = [mock_infra_res, mock_presets_res]

    await reconcile_infra(k8s, db)

    k8s.apply_infra_configmap.assert_awaited_once()
    saved_env = k8s.apply_infra_configmap.call_args[0][0]
    
    # Check default projection
    assert saved_env["DEFAULT_LLM_MODEL"] == "anthropic:claude-3-5-sonnet"
    assert "OPENAI_API_BASE" not in saved_env
    assert "LLM_RUNTIME" not in saved_env


@pytest.mark.asyncio
async def test_reconcile_infra_secret_key_naming():
    k8s = MagicMock()
    k8s.read_infra_secrets = AsyncMock(return_value={})
    k8s.apply_infra_configmap = AsyncMock()
    k8s.apply_infra_secret = AsyncMock()
    k8s.restart_infra_pool_deployments = AsyncMock(return_value=[])

    infra_row = InfraMetaRow(scope="global", scope_key="", env={})
    preset = LlmPresetRow(
        name="GPTPRESET",
        mode="openai_compatible",
        model_id="gpt-4",
        is_default=False,
    )

    db = AsyncMock()
    mock_infra_res = MagicMock()
    mock_infra_res.scalar_one_or_none.return_value = infra_row
    mock_presets_res = MagicMock()
    mock_presets_res.scalars.return_value.all.return_value = [preset]
    db.execute.side_effect = [mock_infra_res, mock_presets_res]

    # Patch new secret key during reconcile
    await reconcile_infra(
        k8s,
        db,
        secrets_patch={"LLM_PRESET_GPTPRESET_API_KEY": "sk-preset-val"},
    )

    k8s.apply_infra_secret.assert_awaited_once()
    saved_secrets = k8s.apply_infra_secret.call_args[0][0]
    
    # Check correct preset secret naming
    assert saved_secrets["LLM_PRESET_GPTPRESET_API_KEY"] == "sk-preset-val"


@pytest.mark.asyncio
async def test_reconcile_infra_delete_preset_clears_secrets():
    k8s = MagicMock()
    # secret contains an old preset API key
    k8s.read_infra_secrets = AsyncMock(return_value={
        "LLM_PRESET_OLD_PRESET_API_KEY": "sk-old-val",
        "LLM_PRESET_ACTIVE_PRESET_API_KEY": "sk-active-val",
    })
    k8s.apply_infra_configmap = AsyncMock()
    k8s.apply_infra_secret = AsyncMock()
    k8s.restart_infra_pool_deployments = AsyncMock(return_value=[])

    infra_row = InfraMetaRow(scope="global", scope_key="", env={})
    # Only ACTIVE_PRESET remains in DB
    preset = LlmPresetRow(
        name="ACTIVE_PRESET",
        mode="frontier",
        frontier_provider="openai",
        model_id="gpt-4o",
        is_default=False,
    )

    db = AsyncMock()
    mock_infra_res = MagicMock()
    mock_infra_res.scalar_one_or_none.return_value = infra_row
    mock_presets_res = MagicMock()
    mock_presets_res.scalars.return_value.all.return_value = [preset]
    db.execute.side_effect = [mock_infra_res, mock_presets_res]

    await reconcile_infra(k8s, db)

    k8s.apply_infra_secret.assert_awaited_once()
    saved_secrets = k8s.apply_infra_secret.call_args[0][0]
    
    # OLD_PRESET_API_KEY must be cleaned up because it is orphaned
    assert "LLM_PRESET_OLD_PRESET_API_KEY" not in saved_secrets
    assert saved_secrets["LLM_PRESET_ACTIVE_PRESET_API_KEY"] == "sk-active-val"
