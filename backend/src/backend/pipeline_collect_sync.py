"""Persist SharePoint delta_link after collect+ingest workflows complete."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.pipeline_domain import SourceDriver, SourceStore

from backend.pipeline_argo import _get_workflow_object
from backend.settings import Settings

logger = logging.getLogger(__name__)


def extract_collect_step_outputs(wf: dict[str, Any]) -> dict[str, str]:
    """Read collect step output parameters from an Argo Workflow CR."""
    nodes = (wf.get("status") or {}).get("nodes") or {}
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        display = str(node.get("displayName") or "")
        if display != "collect" and not str(node_id).endswith(".collect"):
            continue
        params = (node.get("outputs") or {}).get("parameters") or []
        out: dict[str, str] = {}
        for param in params:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip()
            if name:
                out[name] = str(param.get("value") or "")
        if out:
            return out
    return {}


def collect_sync_patch_from_outputs(
    outputs: dict[str, str],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    sync_mode = (outputs.get("sync_mode") or "").strip()
    delta_link = (outputs.get("delta_link") or "").strip()
    if sync_mode == "full":
        return {}, ("delta_link",)
    if delta_link:
        return {"delta_link": delta_link}, ()
    return {}, ()


async def apply_collect_sync_after_terminal(
    *,
    settings: Settings,
    store: SourceStore,
    tenant: str,
    run: dict[str, Any],
    phase: str,
) -> None:
    if phase != "Succeeded":
        return
    if str(run.get("run_kind") or "ingest") != "ingest":
        return
    batch_id = str(run.get("batch_id") or "").strip()
    workflow_name = str(run.get("workflow_name") or "").strip()
    if not batch_id or not workflow_name:
        return

    profile = await asyncio.to_thread(store.get_source_by_last_batch, tenant, batch_id)
    if profile is None or profile.driver != SourceDriver.SHAREPOINT:
        return

    wf = await _get_workflow_object(settings=settings, workflow_name=workflow_name)
    if wf is None:
        return
    outputs = extract_collect_step_outputs(wf)
    if not outputs:
        return

    set_fields, unset_fields = collect_sync_patch_from_outputs(outputs)
    if not set_fields and not unset_fields:
        return

    await asyncio.to_thread(
        store.patch_source_config,
        tenant,
        profile.id,
        set_fields=set_fields or None,
        unset_fields=unset_fields,
    )
    logger.info(
        "pipeline_collect_sync.persisted",
        extra={
            "tenant": tenant,
            "source_id": profile.id,
            "sync_mode": outputs.get("sync_mode"),
            "delta_link_updated": bool(set_fields.get("delta_link")),
            "delta_link_cleared": "delta_link" in unset_fields,
        },
    )
