from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.pipeline_collect_sync import (
    apply_collect_sync_after_terminal,
    collect_sync_patch_from_outputs,
    extract_collect_step_outputs,
)
from path_graph.contracts.source import SourceDriver, SourceProfile


def test_extract_collect_step_outputs_from_node():
    wf = {
        "status": {
            "nodes": {
                "collect-ingest-rag-abc.collect": {
                    "displayName": "collect",
                    "outputs": {
                        "parameters": [
                            {"name": "sync_mode", "value": "delta"},
                            {"name": "delta_link", "value": "https://graph/delta/new"},
                        ]
                    },
                }
            }
        }
    }
    out = extract_collect_step_outputs(wf)
    assert out["sync_mode"] == "delta"
    assert out["delta_link"] == "https://graph/delta/new"


def test_collect_sync_patch_delta_persists_link():
    set_fields, unset = collect_sync_patch_from_outputs(
        {"sync_mode": "delta", "delta_link": "https://graph/delta/new"}
    )
    assert set_fields == {"delta_link": "https://graph/delta/new"}
    assert unset == ()


def test_collect_sync_patch_full_clears_cursor():
    set_fields, unset = collect_sync_patch_from_outputs({"sync_mode": "full"})
    assert set_fields == {}
    assert unset == ("delta_link",)


@pytest.mark.asyncio
async def test_apply_collect_sync_persists_delta_link():
    settings = MagicMock()
    store = MagicMock()
    profile = SourceProfile(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        project_id="550e8400-e29b-41d4-a716-446655440000",
        name="kms",
        driver=SourceDriver.SHAREPOINT,
        source_id="sharepoint:kms",
        config={"folder": "docs"},
    )
    store.get_source_by_last_batch.return_value = profile

    wf = {
        "status": {
            "nodes": {
                "wf.collect": {
                    "displayName": "collect",
                    "outputs": {
                        "parameters": [
                            {"name": "sync_mode", "value": "delta"},
                            {"name": "delta_link", "value": "https://graph/delta/new"},
                        ]
                    },
                }
            }
        }
    }

    async def _to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with (
        patch(
            "backend.pipeline_collect_sync._get_workflow_object",
            new=AsyncMock(return_value=wf),
        ),
        patch(
            "backend.pipeline_collect_sync.asyncio.to_thread",
            side_effect=_to_thread,
        ) as to_thread,
    ):
        await apply_collect_sync_after_terminal(
            settings=settings,
            store=store,
            tenant="dev",
            run={"batch_id": "batch-1", "run_kind": "ingest", "workflow_name": "collect-kms-abc"},
            phase="Succeeded",
        )

    assert to_thread.await_count == 2
    store.patch_source_config.assert_called_once_with(
        "dev",
        profile.id,
        set_fields={"delta_link": "https://graph/delta/new"},
        unset_fields=(),
    )


@pytest.mark.asyncio
async def test_apply_collect_sync_skips_non_ingest():
    store = MagicMock()
    with patch("backend.pipeline_collect_sync._get_workflow_object", new=AsyncMock()) as get_wf:
        await apply_collect_sync_after_terminal(
            settings=MagicMock(),
            store=store,
            tenant="dev",
            run={"batch_id": "batch-1", "run_kind": "graphrag"},
            phase="Succeeded",
        )
    get_wf.assert_not_awaited()
