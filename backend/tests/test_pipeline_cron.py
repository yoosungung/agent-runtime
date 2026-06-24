from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi import HTTPException

from backend.pipeline_cron import (
    build_cron_workflow_body,
    cron_workflow_name,
    validate_cron_schedule,
)


def test_validate_cron_schedule_accepts_standard():
    assert validate_cron_schedule("0 2 * * *") == "0 2 * * *"


def test_validate_cron_schedule_rejects_wrong_field_count():
    with pytest.raises(ValueError, match="5 fields"):
        validate_cron_schedule("0 2 * *")


def test_validate_cron_schedule_rejects_invalid_chars():
    with pytest.raises(ValueError, match="invalid cron field"):
        validate_cron_schedule("0 2 * * monday")


def test_cron_workflow_name_is_dns_safe():
    name = cron_workflow_name("dev", "11111111-1111-4111-8111-111111111111")
    assert name.startswith("pg-cron-dev-")
    assert len(name) <= 63
    assert re.fullmatch(r"[a-z0-9-]+", name)


def test_build_cron_workflow_body():
    body = build_cron_workflow_body(
        name="pg-cron-dev-abc",
        namespace="path-graph",
        schedule="0 3 * * *",
        template_name="pipeline-collect-ingest-rag",
        tenant="dev",
        source_id="11111111-1111-4111-8111-111111111111",
        credential_secret="path-graph-cred-dev-abc",
        suspend=False,
    )
    assert body["kind"] == "CronWorkflow"
    assert body["metadata"]["name"] == "pg-cron-dev-abc"
    assert body["spec"]["schedule"] == "0 3 * * *"
    assert body["spec"]["suspend"] is False
    params = {
        p["name"]: p["value"]
        for p in body["spec"]["workflowSpec"]["arguments"]["parameters"]
    }
    assert params["tenant"] == "dev"
    assert params["source_id"] == "11111111-1111-4111-8111-111111111111"
    assert params["batch_id"] == ""
    assert params["credential_secret"] == "path-graph-cred-dev-abc"


@pytest.mark.asyncio
async def test_reconcile_source_cron_delete_when_empty(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.pipeline_cron import reconcile_source_cron
    from backend.settings import Settings

    delete_mock = AsyncMock()
    monkeypatch.setattr("backend.pipeline_cron._delete_cron_workflow", delete_mock)

    settings = Settings(PATH_GRAPH_ARGO_NAMESPACE="path-graph")
    await reconcile_source_cron(
        settings=settings,
        tenant="dev",
        source_id="11111111-1111-4111-8111-111111111111",
        schedule_cron=None,
    )
    delete_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_source_cron_upsert(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.pipeline_cron import reconcile_source_cron
    from backend.settings import Settings

    upsert_mock = AsyncMock()
    monkeypatch.setattr("backend.pipeline_cron._upsert_cron_workflow", upsert_mock)

    settings = Settings(
        PATH_GRAPH_ARGO_NAMESPACE="path-graph",
        PATH_GRAPH_COLLECT_WF_TEMPLATE="pipeline-collect-ingest-rag",
    )
    await reconcile_source_cron(
        settings=settings,
        tenant="dev",
        source_id="11111111-1111-4111-8111-111111111111",
        schedule_cron="0 4 * * *",
        credential_secret="path-graph-cred-dev-x",
        suspend=False,
    )
    upsert_mock.assert_awaited_once()
    body = upsert_mock.await_args.kwargs["body"]
    assert body["spec"]["schedule"] == "0 4 * * *"


def test_validate_cron_schedule_http_error():
    from backend.pipeline_cron import validate_cron_schedule_or_http

    with pytest.raises(HTTPException) as exc:
        validate_cron_schedule_or_http("bad cron")
    assert exc.value.status_code == 400
