"""Background reconciler for pipeline run terminal status persistence."""

from __future__ import annotations

import asyncio
import logging

from backend.pipeline_domain import SourceStore

from backend.pipeline_argo import _TERMINAL_WORKFLOW_PHASES, get_workflow_status
from backend.pipeline_collect_sync import apply_collect_sync_after_terminal
from backend.pipeline_helpers import _persist_terminal_run, apply_graphrag_after_terminal, apply_lifecycle_after_terminal

logger = logging.getLogger(__name__)

_PIPELINE_RUN_SYNC_INTERVAL = 300  # 5 minutes


def _path_graph_dsn(settings) -> str | None:
    dsn = settings.PATH_GRAPH_DSN or settings.POSTGRES_DSN
    if not dsn:
        return None
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


async def reconcile_pipeline_runs_once(app) -> None:  # type: ignore[type-arg]
    settings = app.state.settings
    if not settings.PIPELINE_CONSOLE_ENABLED:
        return
    dsn = _path_graph_dsn(settings)
    if not dsn:
        return

    store = SourceStore(dsn)
    runs = await asyncio.to_thread(store.list_non_finalized_pipeline_runs, 200)
    if not runs:
        return

    persisted = 0
    for run in runs:
        workflow_name = str(run.get("workflow_name") or "").strip()
        if not workflow_name:
            continue
        wf_status = await get_workflow_status(
            settings=settings,
            workflow_name=workflow_name,
        )
        if wf_status is None:
            continue
        phase = str(wf_status.get("phase") or "").strip()
        if phase not in _TERMINAL_WORKFLOW_PHASES:
            continue
        await _persist_terminal_run(
            store=store,
            tenant=str(run["tenant"]),
            run=run,
            wf_status=wf_status,
        )
        await apply_graphrag_after_terminal(
            settings=settings,
            run=run,
            phase=phase,
        )
        await apply_lifecycle_after_terminal(
            settings=settings,
            run=run,
            phase=phase,
        )
        await apply_collect_sync_after_terminal(
            settings=settings,
            store=store,
            tenant=str(run["tenant"]),
            run=run,
            phase=phase,
        )
        persisted += 1

    if persisted:
        logger.info(
            "pipeline_run_reconciler.persisted",
            extra={"count": persisted},
        )


async def run_pipeline_run_reconciler(app) -> None:  # type: ignore[type-arg]
    while True:
        await asyncio.sleep(_PIPELINE_RUN_SYNC_INTERVAL)
        try:
            await reconcile_pipeline_runs_once(app)
        except Exception:
            logger.exception("pipeline_run_reconciler.error")
