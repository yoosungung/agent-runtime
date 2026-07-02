"""Tests for async job invoke timeout (longer than sync /invoke)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_base.invoke_handler import InvokeContext, execute_invoke
from agent_base.jobs import JobService, JobSubmitRequest
from agent_base.settings import Settings
from runtime_common.agent_jobs import JobStore
from runtime_common.schemas import Principal


@pytest.mark.asyncio
async def test_execute_invoke_accepts_custom_timeout_sec(monkeypatch):
    settings = Settings(_env_file=None, invoke_timeout_sec=120)
    ctx = InvokeContext(
        settings=settings,
        counter=MagicMock(),
        deploy=MagicMock(),
        loader=MagicMock(),
        cache=MagicMock(),
        vfs_pool=None,
        adk_session_services={},
    )

    captured: dict[str, float] = {}

    async def fake_wait_for(coro, *, timeout):
        captured["timeout"] = timeout
        await coro
        return {"entities": []}

    async def fake_run(*_args, **_kwargs):
        return {"entities": []}

    monkeypatch.setattr("agent_base.invoke_handler.asyncio.wait_for", fake_wait_for)
    monkeypatch.setattr("agent_base.invoke_handler.run", fake_run)
    monkeypatch.setattr(
        "agent_base.invoke_handler.resolve_for_invoke",
        AsyncMock(
            return_value=MagicMock(
                source=MagicMock(runtime_pool="agent:compiled_graph", config={}),
                user=None,
            )
        ),
    )
    monkeypatch.setattr(
        "agent_base.invoke_handler.get_or_build_cached_instance",
        AsyncMock(return_value=MagicMock()),
    )

    await execute_invoke(
        ctx,
        agent="graph-extractor",
        version=None,
        input_data={},
        session_id="sess",
        principal=Principal(sub="user:1"),
        token=None,
        timeout_sec=1800,
    )
    assert captured["timeout"] == 1800


@pytest.mark.asyncio
async def test_job_service_uses_job_invoke_timeout(monkeypatch):
    store = MagicMock(spec=JobStore)
    store.create = AsyncMock(side_effect=lambda r: r)
    store.get = AsyncMock()
    store.mark_running = AsyncMock()
    store.mark_succeeded = AsyncMock()
    store.mark_failed = AsyncMock()

    settings = Settings(_env_file=None, invoke_timeout_sec=120, job_invoke_timeout_sec=1800)
    ctx = MagicMock()
    service = JobService(store, ctx, settings, http_client=MagicMock())

    captured: dict[str, float | None] = {}

    async def fake_execute(_ctx, **kwargs):
        captured["timeout_sec"] = kwargs.get("timeout_sec")
        return {"entities": []}

    monkeypatch.setattr("agent_base.jobs.execute_invoke", fake_execute)

    principal = Principal(sub="user:1", tenant="dev", user_id=1)
    req = JobSubmitRequest(agent="graph-extractor", input={"tenant": "dev"}, session_id="sess")

    await service._run_job("job-1", req, principal, None)

    assert captured["timeout_sec"] == 1800
