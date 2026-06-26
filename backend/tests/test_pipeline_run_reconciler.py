from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.pipeline_run_reconciler import reconcile_pipeline_runs_once
from backend.settings import Settings


@pytest.mark.asyncio
async def test_reconcile_pipeline_runs_persists_terminal_runs():
    app = MagicMock()
    app.state.settings = Settings(
        PIPELINE_CONSOLE_ENABLED=True,
        PATH_GRAPH_DSN="postgresql://localhost/test",
    )

    open_run = {
        "tenant": "dev",
        "id": "run-1",
        "workflow_name": "ingest-docs-abc",
        "batch_id": "batch-1",
        "status": "submitted",
    }

    store = MagicMock()
    store.list_non_finalized_pipeline_runs.return_value = [open_run]

    async def _status(**_kwargs):
        return {
            "phase": "Succeeded",
            "started_at": "2026-06-26T12:00:01Z",
            "ended_at": "2026-06-26T12:05:00Z",
        }

    with (
        patch("backend.pipeline_run_reconciler.SourceStore", return_value=store),
        patch("backend.pipeline_run_reconciler.get_workflow_status", side_effect=_status),
        patch(
            "backend.pipeline_run_reconciler._persist_terminal_run",
            new=AsyncMock(),
        ) as persist_mock,
    ):
        await reconcile_pipeline_runs_once(app)

    persist_mock.assert_awaited_once()
    assert persist_mock.await_args.kwargs["tenant"] == "dev"


@pytest.mark.asyncio
async def test_reconcile_pipeline_runs_skips_when_console_disabled():
    app = MagicMock()
    app.state.settings = Settings(PIPELINE_CONSOLE_ENABLED=False)

    with patch("backend.pipeline_run_reconciler.SourceStore") as store_cls:
        await reconcile_pipeline_runs_once(app)

    store_cls.assert_not_called()
