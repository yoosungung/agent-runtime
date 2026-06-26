from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.pipeline_helpers import enrich_pipeline_runs_with_argo, started_at_from_batch_id
from backend.settings import Settings


@pytest.mark.asyncio
async def test_enrich_pipeline_runs_merges_argo_status():
    runs = [
        {
            "id": "run-1",
            "workflow_name": "ingest-docs-abc",
            "argo_uid": "uid-1",
            "batch_id": "20260626-120000",
            "status": "submitted",
            "started_at": None,
            "ended_at": None,
        }
    ]

    async def _status(**_kwargs):
        return {
            "phase": "Succeeded",
            "started_at": "2026-06-26T12:00:01Z",
            "ended_at": "2026-06-26T12:05:00Z",
        }

    with patch("backend.pipeline_helpers.get_workflow_status", side_effect=_status):
        enriched, argo_available = await enrich_pipeline_runs_with_argo(
            settings=Settings(),
            runs=runs,
        )

    assert argo_available is True
    assert enriched[0]["status"] == "Succeeded"
    assert enriched[0]["started_at"] == "2026-06-26T12:00:01Z"
    assert enriched[0]["ended_at"] == "2026-06-26T12:05:00Z"


@pytest.mark.asyncio
async def test_enrich_pipeline_runs_persists_terminal_status():
    runs = [
        {
            "id": "run-1",
            "workflow_name": "ingest-docs-abc",
            "argo_uid": "uid-1",
            "batch_id": "20260626-120000",
            "status": "submitted",
            "started_at": None,
            "ended_at": None,
        }
    ]
    store = MagicMock()

    async def _status(**_kwargs):
        return {
            "phase": "Succeeded",
            "started_at": "2026-06-26T12:00:01Z",
            "ended_at": "2026-06-26T12:05:00Z",
        }

    with patch("backend.pipeline_helpers.get_workflow_status", side_effect=_status):
        await enrich_pipeline_runs_with_argo(
            settings=Settings(),
            runs=runs,
            store=store,
            tenant="dev",
        )

    store.finalize_pipeline_run.assert_called_once_with(
        "dev",
        "run-1",
        "Succeeded",
        "2026-06-26T12:00:01Z",
        "2026-06-26T12:05:00Z",
    )


@pytest.mark.asyncio
async def test_enrich_pipeline_runs_keeps_pg_status_when_workflow_missing():
    runs = [
        {
            "id": "run-1",
            "workflow_name": "ingest-docs-gone",
            "argo_uid": "uid-1",
            "batch_id": "batch-old",
            "status": "submitted",
            "started_at": None,
            "ended_at": None,
        }
    ]

    async def _missing(**_kwargs):
        return None

    with patch("backend.pipeline_helpers.get_workflow_status", side_effect=_missing):
        enriched, argo_available = await enrich_pipeline_runs_with_argo(
            settings=Settings(),
            runs=runs,
        )

    assert argo_available is True
    assert enriched[0]["status"] == "submitted"
    assert enriched[0]["started_at"] is None
    assert enriched[0]["ended_at"] is None


@pytest.mark.asyncio
async def test_enrich_pipeline_runs_uses_pg_snapshot_when_workflow_deleted():
    runs = [
        {
            "id": "run-1",
            "workflow_name": "ingest-docs-gone",
            "argo_uid": "uid-1",
            "batch_id": "20260626-120000",
            "status": "Succeeded",
            "started_at": "2026-06-26T12:00:01Z",
            "ended_at": "2026-06-26T12:05:00Z",
        }
    ]

    status_mock = AsyncMock(return_value=None)
    with patch("backend.pipeline_helpers.get_workflow_status", status_mock):
        enriched, argo_available = await enrich_pipeline_runs_with_argo(
            settings=Settings(),
            runs=runs,
        )

    assert argo_available is True
    status_mock.assert_not_called()
    assert enriched[0]["status"] == "Succeeded"
    assert enriched[0]["ended_at"] == "2026-06-26T12:05:00Z"


def test_started_at_from_batch_id_parses_utc_timestamp():
    assert started_at_from_batch_id("20260626-015255") == "2026-06-26T01:52:55Z"
    assert started_at_from_batch_id("batch-old") is None


@pytest.mark.asyncio
async def test_enrich_pipeline_runs_uses_batch_id_when_workflow_missing():
    runs = [
        {
            "id": "run-1",
            "workflow_name": "ingest-source-gone",
            "argo_uid": "uid-1",
            "batch_id": "20260624-072131",
            "status": "submitted",
        }
    ]

    async def _missing(**_kwargs):
        return None

    with patch("backend.pipeline_helpers.get_workflow_status", side_effect=_missing):
        enriched, argo_available = await enrich_pipeline_runs_with_argo(
            settings=Settings(),
            runs=runs,
        )

    assert argo_available is True
    assert enriched[0]["status"] == "submitted"
    assert enriched[0]["started_at"] == "2026-06-24T07:21:31Z"
    assert enriched[0]["ended_at"] is None


@pytest.mark.asyncio
async def test_enrich_pipeline_runs_argo_unavailable():
    runs = [
        {
            "id": "run-1",
            "workflow_name": "ingest-docs-abc",
            "argo_uid": "uid-1",
            "batch_id": "20260626-015255",
            "status": "submitted",
        }
    ]

    async def _down(**_kwargs):
        raise HTTPException(status_code=503, detail="Argo Workflows unavailable")

    with patch("backend.pipeline_helpers.get_workflow_status", side_effect=_down):
        enriched, argo_available = await enrich_pipeline_runs_with_argo(
            settings=Settings(),
            runs=runs,
        )

    assert argo_available is False
    assert enriched[0]["status"] == "submitted"
    assert enriched[0]["started_at"] == "2026-06-26T01:52:55Z"
    assert enriched[0]["ended_at"] is None
