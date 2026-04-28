"""Background reconciler for custom image mode state machine.

Runs every 60 seconds and:
1. Cleans up 'pending' rows older than K8S_PENDING_TIMEOUT_SEC → K8s delete + status='failed'.
2. Reports 'active' rows whose Deployment is missing/extra (admin alert via log).
3. Cleans up K8s resources for 'retired' rows that still have a Deployment.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timezone

from sqlalchemy import select

from runtime_common.db import session_scope

logger = logging.getLogger(__name__)

_RECONCILE_INTERVAL = 60  # seconds


async def _now_utc():
    from datetime import datetime
    return datetime.now(tz=timezone.utc)


async def reconcile_once(app) -> None:  # type: ignore[type-arg]
    """Single reconcile pass — called by the background loop."""
    from datetime import datetime, timedelta, timezone

    settings = app.state.settings
    k8s = getattr(app.state, "k8s_pool_manager", None)
    session_factory = app.state.session_factory
    timeout_sec = settings.K8S_PENDING_TIMEOUT_SEC

    from runtime_common.db.models import SourceMetaRow

    async with session_scope(session_factory) as session:
        # ----------------------------------------------------------------
        # 1. Stuck 'pending' rows → force-failed
        # ----------------------------------------------------------------
        cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=timeout_sec)
        stmt = select(SourceMetaRow).where(
            SourceMetaRow.deploy_mode == "image",
            SourceMetaRow.status == "pending",
            SourceMetaRow.created_at < cutoff,
        )
        result = await session.execute(stmt)
        stuck_rows = result.scalars().all()

        for row in stuck_rows:
            logger.warning(
                "reconciler.pending_timeout",
                extra={"id": row.id, "slug": row.slug, "kind": row.kind},
            )
            if k8s is not None and row.slug:
                await k8s.delete_pool(row.kind, row.slug)
            row.status = "failed"

        if stuck_rows:
            await session.commit()

        # ----------------------------------------------------------------
        # 2. 'active' rows — check K8s Deployment existence (report only)
        # ----------------------------------------------------------------
        stmt2 = select(SourceMetaRow).where(
            SourceMetaRow.deploy_mode == "image",
            SourceMetaRow.status == "active",
        )
        result2 = await session.execute(stmt2)
        active_rows = result2.scalars().all()

        if k8s is not None:
            for row in active_rows:
                if row.slug is None:
                    continue
                try:
                    exists = await k8s.deployment_exists(row.kind, row.slug)
                except Exception as exc:
                    logger.error(
                        "reconciler.k8s_check_error",
                        extra={"slug": row.slug, "error": str(exc)},
                    )
                    continue
                if not exists:
                    logger.error(
                        "reconciler.active_deployment_missing",
                        extra={
                            "id": row.id,
                            "slug": row.slug,
                            "kind": row.kind,
                            "action": "admin_action_required",
                        },
                    )

        # ----------------------------------------------------------------
        # 3. 'retired' rows with residual K8s resources → force-delete
        # ----------------------------------------------------------------
        stmt3 = select(SourceMetaRow).where(
            SourceMetaRow.deploy_mode == "image",
            SourceMetaRow.status == "retired",
            SourceMetaRow.slug.is_not(None),
        )
        result3 = await session.execute(stmt3)
        retired_rows = result3.scalars().all()

        if k8s is not None:
            for row in retired_rows:
                try:
                    exists = await k8s.deployment_exists(row.kind, row.slug)
                    if exists:
                        logger.warning(
                            "reconciler.retired_k8s_residual_cleanup",
                            extra={"slug": row.slug},
                        )
                        await k8s.delete_pool(row.kind, row.slug)
                except Exception as exc:
                    logger.error(
                        "reconciler.retired_cleanup_error",
                        extra={"slug": row.slug, "error": str(exc)},
                    )


async def run_reconciler(app) -> None:  # type: ignore[type-arg]
    """Background task that calls reconcile_once every _RECONCILE_INTERVAL seconds."""
    while True:
        await asyncio.sleep(_RECONCILE_INTERVAL)
        try:
            await reconcile_once(app)
        except Exception as exc:
            logger.error("reconciler.error", extra={"error": str(exc)})
