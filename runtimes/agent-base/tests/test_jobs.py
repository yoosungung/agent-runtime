"""Unit tests for agent-base JobService."""

from unittest.mock import AsyncMock, MagicMock

import asyncio
import pytest

from agent_base.invoke_handler import InvokeContext
from agent_base.jobs import JobService, JobSubmitRequest
from agent_base.settings import Settings
from runtime_common.agent_jobs import JobRecord, JobStatus, JobStore
from runtime_common.schemas import Principal


@pytest.mark.asyncio
async def test_job_service_submit_creates_pending_record(monkeypatch):
    store = MagicMock(spec=JobStore)
    store.create = AsyncMock(side_effect=lambda r: r)
    ctx = MagicMock(spec=InvokeContext)
    settings = Settings(_env_file=None)
    service = JobService(store, ctx, settings, http_client=MagicMock())

    principal = Principal(sub="user:1", tenant="dev", user_id=1)
    req = JobSubmitRequest(
        agent="graph-extractor",
        input={"tenant": "dev"},
        session_id="sess",
        job_id="job-abc",
    )

    monkeypatch.setattr(asyncio, "create_task", lambda _coro: None)
    record = await service.submit(req, principal=principal, auth_token="tok")

    assert record.job_id == "job-abc"
    assert record.status == JobStatus.pending
    store.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_job_service_get_for_principal_checks_owner():
    record = JobRecord(
        job_id="job-1",
        agent="graph-extractor",
        version=None,
        session_id="sess",
        principal_sub="user:1",
        tenant="dev",
        status=JobStatus.succeeded,
        output={"entities": []},
    )
    store = MagicMock(spec=JobStore)
    store.get = AsyncMock(return_value=record)
    service = JobService(store, MagicMock(), Settings(_env_file=None), http_client=MagicMock())

    loaded = await service.get_for_principal("job-1", principal=Principal(sub="user:1"))
    assert loaded.output == {"entities": []}
