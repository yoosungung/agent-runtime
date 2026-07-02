"""Tests for runtime_common.agent_jobs."""

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from runtime_common.agent_jobs import ArgoCallback, JobCallback, JobRecord, JobStatus, JobStore


def _mock_redis(*, get_data: str | None = None) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(return_value=get_data)
    client.set = AsyncMock(return_value=True)
    pipe = MagicMock()
    pipe.set = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[True])
    client.pipeline = MagicMock(return_value=pipe)
    return client


@pytest.mark.asyncio
async def test_job_store_create_and_get():
    record = JobRecord(
        job_id="job-1",
        agent="graph-extractor",
        version=None,
        session_id="sess",
        principal_sub="user:1",
        tenant="dev",
        status=JobStatus.pending,
        created_at=time.time(),
        updated_at=time.time(),
    )
    client = _mock_redis(get_data=record.model_dump_json())
    store = JobStore(client, ttl_sec=3600)

    created = await store.create(record)
    assert created.job_id == "job-1"
    client.set.assert_awaited_once()

    loaded = await store.get("job-1")
    assert loaded is not None
    assert loaded.agent == "graph-extractor"
    assert loaded.status == JobStatus.pending


@pytest.mark.asyncio
async def test_job_store_update_terminal():
    record = JobRecord(
        job_id="job-2",
        agent="wiki-synthesizer",
        version="1",
        session_id="sess",
        principal_sub="user:1",
        tenant="dev",
        status=JobStatus.running,
        created_at=time.time(),
        updated_at=time.time(),
        callback=JobCallback(
            argo=ArgoCallback(namespace="path-graph", workflow="wf-1"),
        ),
    )
    client = _mock_redis(get_data=record.model_dump_json())
    store = JobStore(client, ttl_sec=3600)

    updated = await store.mark_succeeded("job-2", output={"pages": []})
    assert updated.status == JobStatus.succeeded
    assert updated.output == {"pages": []}
    client.set.assert_awaited()


@pytest.mark.asyncio
async def test_job_record_serializes_callback():
    record = JobRecord(
        job_id="job-3",
        agent="graph-extractor",
        version=None,
        session_id="sess",
        principal_sub="user:1",
        tenant="dev",
        status=JobStatus.pending,
        created_at=1.0,
        updated_at=1.0,
        callback=JobCallback(
            argo=ArgoCallback(
                namespace="path-graph",
                workflow="pipeline-graphrag-abc",
                node_field_selector="inputs.parameters.job-id.value=job-3",
            )
        ),
    )
    raw = json.loads(record.model_dump_json())
    assert raw["callback"]["argo"]["workflow"] == "pipeline-graphrag-abc"
