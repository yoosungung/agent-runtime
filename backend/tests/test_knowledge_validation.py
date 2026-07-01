"""Tests for knowledge project validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.knowledge_validation import (
    mcp_servers_requiring_knowledge,
    validate_knowledge_projects,
)
from runtime_common.db.models import SourceMetaRow


def _mcp_row(*, name: str, requires: bool) -> SourceMetaRow:
    return SourceMetaRow(
        kind="mcp",
        name=name,
        version="v1",
        runtime_pool="mcp:custom:path-graph-rag-v1",
        entrypoint="",
        bundle_uri="",
        checksum="sha256:" + "a" * 64,
        config={"knowledge": {"requires_project": requires}},
        deploy_mode="image",
        status="active",
    )


@pytest.mark.asyncio
async def test_mcp_servers_requiring_knowledge_detects_policy():
    row = _mcp_row(name="rag-server", requires=True)
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db = AsyncMock()
    db.execute.return_value = result

    required = await mcp_servers_requiring_knowledge(db, ["rag-server"])
    assert required == ["rag-server"]


@pytest.mark.asyncio
async def test_validate_knowledge_projects_requires_projects_when_mcp_needs_them():
    row = _mcp_row(name="rag-server", requires=True)
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db = AsyncMock()
    db.execute.return_value = result
    store = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await validate_knowledge_projects(
            db,
            tenant="acme",
            project_ids=[],
            mcp_servers=["rag-server"],
            project_store=store,
        )
    assert exc.value.status_code == 400
    assert "knowledge_project_ids required" in exc.value.detail


@pytest.mark.asyncio
async def test_validate_knowledge_projects_ok_with_binding():
    row = _mcp_row(name="rag-server", requires=True)
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db = AsyncMock()
    db.execute.return_value = result
    store = MagicMock()
    store.get_project.return_value = object()

    required = await validate_knowledge_projects(
        db,
        tenant="acme",
        project_ids=["p1"],
        mcp_servers=["rag-server"],
        project_store=store,
    )
    assert required == ["rag-server"]
    store.get_project.assert_called_with("acme", "p1")
