"""Tests for runtime_common.argo_workflows."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from runtime_common.argo_workflows import resume_workflow, stop_workflow


@pytest.mark.asyncio
async def test_resume_workflow_posts_to_argo_server():
    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.raise_for_status = MagicMock()
    client.put = AsyncMock(return_value=response)

    await resume_workflow(
        client,
        base_url="http://argo-server.argo:2746",
        token="tok",
        namespace="path-graph",
        workflow="wf-1",
        node_field_selector="inputs.parameters.job-id.value=abc",
    )

    client.put.assert_awaited_once()
    call = client.put.await_args
    assert "/workflows/path-graph/wf-1/resume" in call.args[0]
    assert call.kwargs["json"]["nodeFieldSelector"] == "inputs.parameters.job-id.value=abc"
    assert call.kwargs["headers"]["Authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_stop_workflow_includes_message():
    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.raise_for_status = MagicMock()
    client.put = AsyncMock(return_value=response)

    await stop_workflow(
        client,
        base_url="http://argo-server.argo:2746",
        token="tok",
        namespace="path-graph",
        workflow="wf-1",
        message="agent job failed",
    )

    client.put.assert_awaited_once()
    assert client.put.await_args.kwargs["json"]["message"] == "agent job failed"
