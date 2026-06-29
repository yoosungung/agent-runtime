from __future__ import annotations

import asyncio
import logging

from path_graph.admin.projects import ProjectStore

from backend.pipeline_cron import reconcile_project_cron

logger = logging.getLogger(__name__)


def _path_graph_dsn(settings) -> str | None:
    dsn = settings.PATH_GRAPH_DSN or settings.POSTGRES_DSN
    if not dsn:
        return None
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


async def bootstrap_project_reconcile_crons(app) -> None:  # type: ignore[type-arg]
    """Ensure reconcile CronWorkflow exists for every project (startup drift correction)."""
    settings = app.state.settings
    if not settings.PIPELINE_CONSOLE_ENABLED:
        return

    dsn = _path_graph_dsn(settings)
    if not dsn:
        logger.debug("project_reconcile_cron_bootstrap skipped — no PATH_GRAPH_DSN")
        return

    store = ProjectStore(dsn)
    try:
        projects = await asyncio.to_thread(store.list_all_projects)
    except Exception:
        logger.exception("project_reconcile_cron_bootstrap.list_failed")
        return

    for project in projects:
        try:
            await reconcile_project_cron(
                settings=settings,
                tenant=project.tenant,
                project_id=project.id,
            )
        except Exception:
            logger.exception(
                "project_reconcile_cron_bootstrap.upsert_failed",
                extra={"tenant": project.tenant, "project_id": project.id},
            )

    logger.info(
        "project_reconcile_cron_bootstrap.done",
        extra={"project_count": len(projects)},
    )
