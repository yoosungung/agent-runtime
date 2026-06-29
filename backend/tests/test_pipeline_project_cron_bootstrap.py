from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.pipeline_project_cron_bootstrap import bootstrap_project_reconcile_crons
from backend.settings import Settings


@pytest.mark.asyncio
async def test_bootstrap_project_reconcile_crons_upserts_each_project():
    settings = Settings(
        PATH_GRAPH_DSN="postgresql://localhost/test",
        PATH_GRAPH_RECONCILE_CRON_SCHEDULE="0 3 * * *",
    )
    app = MagicMock()
    app.state.settings = settings

    profiles = [
        MagicMock(tenant="dev", id="550e8400-e29b-41d4-a716-446655440000"),
        MagicMock(tenant="prod", id="660e8400-e29b-41d4-a716-446655440001"),
    ]

    with (
        patch(
            "backend.pipeline_project_cron_bootstrap.ProjectStore"
        ) as store_cls,
        patch(
            "backend.pipeline_project_cron_bootstrap.reconcile_project_cron",
            new_callable=AsyncMock,
        ) as reconcile_mock,
    ):
        store_cls.return_value.list_all_projects.return_value = profiles
        await bootstrap_project_reconcile_crons(app)

    assert reconcile_mock.await_count == 2
