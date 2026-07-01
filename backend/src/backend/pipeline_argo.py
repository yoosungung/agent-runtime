from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.exceptions import ApiException

from backend.k8s_client import make_api_client
from backend.settings import Settings

logger = logging.getLogger(__name__)

_ARGO_GROUP = "argoproj.io"
_ARGO_VERSION = "v1alpha1"
_ARGO_PLURAL = "workflows"


def _safe_generate_prefix(source_name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", source_name.lower()).strip("-")
    if not slug:
        slug = "source"
    return f"ingest-{slug}-"


def _collect_generate_prefix(source_name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", source_name.lower()).strip("-")
    if not slug:
        slug = "source"
    return f"collect-{slug}-"


def _graphrag_generate_prefix(project_slug: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", project_slug.lower()).strip("-")
    if not slug:
        slug = "project"
    return f"graphrag-{slug}-"


def _workflow_body(
    *,
    settings: Settings,
    tenant: str,
    template_name: str,
    source_name: str,
    parameters: list[dict[str, str]],
    generate_prefix: str | None = None,
) -> dict[str, Any]:
    if generate_prefix:
        name_prefix = generate_prefix
    elif template_name == settings.PATH_GRAPH_COLLECT_WF_TEMPLATE:
        name_prefix = _collect_generate_prefix(source_name)
    else:
        name_prefix = _safe_generate_prefix(source_name)
    return {
        "apiVersion": f"{_ARGO_GROUP}/{_ARGO_VERSION}",
        "kind": "Workflow",
        "metadata": {
            "generateName": name_prefix,
            "namespace": settings.PATH_GRAPH_ARGO_NAMESPACE,
        },
        "spec": {
            "workflowTemplateRef": {"name": template_name},
            "arguments": {"parameters": parameters},
        },
    }


_ACTIVE_WORKFLOW_PHASES = frozenset({"Running", "Pending"})
_TERMINAL_WORKFLOW_PHASES = frozenset({"Succeeded", "Failed", "Error"})


def ingest_rag_parameters(
    *,
    tenant: str,
    batch_manifest_json: str = "",
    batch_manifest_key: str = "",
) -> list[dict[str, str]]:
    """Build pipeline-ingest-rag WF parameters.

    Argo resolve-manifest prefers inline batch_manifest over batch_manifest_key;
    when an S3 key is set, omit inline JSON so the pod reads the S3 manifest.
    """
    inline = "" if batch_manifest_key.strip() else batch_manifest_json
    return [
        {"name": "tenant", "value": tenant},
        {"name": "batch_manifest", "value": inline},
        {"name": "batch_manifest_key", "value": batch_manifest_key},
        {"name": "rag", "value": "true"},
    ]


def workflow_status_from_object(wf: dict[str, Any]) -> dict[str, str | None]:
    """Extract Argo Workflow phase and timestamps from a Workflow CR object."""
    status = wf.get("status") or {}
    phase = str(status.get("phase") or "").strip() or None
    started_at = status.get("startedAt") or None
    ended_at = status.get("finishedAt") or None
    return {
        "phase": phase,
        "started_at": str(started_at) if started_at else None,
        "ended_at": str(ended_at) if ended_at else None,
    }


async def _get_workflow_object(
    *,
    settings: Settings,
    workflow_name: str,
) -> dict[str, Any] | None:
    """Fetch Workflow CR; None if deleted (404)."""
    if not workflow_name:
        return None
    api_client = None
    try:
        api_client = await make_api_client(settings)
        custom = k8s_client.CustomObjectsApi(api_client)
        return await custom.get_namespaced_custom_object(
            group=_ARGO_GROUP,
            version=_ARGO_VERSION,
            namespace=settings.PATH_GRAPH_ARGO_NAMESPACE,
            plural=_ARGO_PLURAL,
            name=workflow_name,
        )
    except ApiException as exc:
        if exc.status == 404:
            return None
        logger.warning(
            "argo get workflow failed",
            extra={"status": exc.status, "workflow": workflow_name},
        )
        raise HTTPException(
            status_code=503,
            detail=f"Argo workflow lookup failed: {exc.reason or exc.status}",
        ) from exc
    except Exception as exc:
        logger.warning("argo client unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Argo Workflows unavailable — connect to cluster or set K8S_IN_CLUSTER=false",
        ) from exc
    finally:
        if api_client is not None:
            await api_client.close()


async def get_workflow_status(
    *,
    settings: Settings,
    workflow_name: str,
) -> dict[str, str | None] | None:
    """Return phase/timestamps from Argo, or None if the workflow no longer exists."""
    wf = await _get_workflow_object(settings=settings, workflow_name=workflow_name)
    if wf is None:
        return None
    return workflow_status_from_object(wf)


async def get_workflow_phase(
    *,
    settings: Settings,
    workflow_name: str,
) -> str | None:
    """Return Argo Workflow phase, or None if the workflow no longer exists."""
    status = await get_workflow_status(settings=settings, workflow_name=workflow_name)
    return status["phase"] if status else None


async def _submit_workflow(
    *,
    settings: Settings,
    body: dict[str, Any],
) -> dict[str, str]:
    api_client = None
    try:
        api_client = await make_api_client(settings)
        custom = k8s_client.CustomObjectsApi(api_client)
        created = await custom.create_namespaced_custom_object(
            group=_ARGO_GROUP,
            version=_ARGO_VERSION,
            namespace=settings.PATH_GRAPH_ARGO_NAMESPACE,
            plural=_ARGO_PLURAL,
            body=body,
        )
        meta = created.get("metadata") or {}
        return {
            "workflow_name": str(meta.get("name", "")),
            "argo_uid": str(meta.get("uid", "")),
        }
    except ApiException as exc:
        logger.warning("argo submit failed", extra={"status": exc.status, "reason": exc.reason})
        if exc.status in (401, 403):
            raise HTTPException(
                status_code=503,
                detail="Argo Workflows API not authorized — check cluster RBAC",
            ) from exc
        raise HTTPException(
            status_code=503,
            detail=f"Argo submit failed: {exc.reason or exc.status}",
        ) from exc
    except Exception as exc:
        logger.warning("argo client unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Argo Workflows unavailable — connect to cluster or set K8S_IN_CLUSTER=false",
        ) from exc
    finally:
        if api_client is not None:
            await api_client.close()


async def submit_ingest_rag(
    *,
    settings: Settings,
    tenant: str,
    batch_manifest_json: str = "",
    batch_manifest_key: str = "",
    source_name: str,
) -> dict[str, str]:
    """Submit pipeline-ingest-rag Workflow. Prefer batch_manifest_key over inline JSON."""
    parameters = ingest_rag_parameters(
        tenant=tenant,
        batch_manifest_json=batch_manifest_json,
        batch_manifest_key=batch_manifest_key,
    )
    body = _workflow_body(
        settings=settings,
        tenant=tenant,
        template_name=settings.PATH_GRAPH_INGEST_WF_TEMPLATE,
        source_name=source_name,
        parameters=parameters,
    )
    return await _submit_workflow(settings=settings, body=body)


async def submit_collect_ingest_rag(
    *,
    settings: Settings,
    tenant: str,
    source_id: str,
    batch_id: str,
    source_name: str,
    credential_secret: str = "",
    sync_mode: str = "",
) -> dict[str, str]:
    """Submit pipeline-collect-ingest-rag Workflow (async Run now)."""
    parameters = [
        {"name": "tenant", "value": tenant},
        {"name": "source_id", "value": source_id},
        {"name": "batch_id", "value": batch_id},
        {"name": "credential_secret", "value": credential_secret},
        {"name": "rag", "value": "true"},
        {"name": "sync_mode", "value": sync_mode},
    ]
    body = _workflow_body(
        settings=settings,
        tenant=tenant,
        template_name=settings.PATH_GRAPH_COLLECT_WF_TEMPLATE,
        source_name=source_name,
        parameters=parameters,
    )
    return await _submit_workflow(settings=settings, body=body)


def graphrag_parameters(
    *,
    tenant: str,
    project_id: str,
    project_slug: str,
    batch_id: str,
    chunks_key: str,
    skip_agent: bool = False,
) -> list[dict[str, str]]:
    return [
        {"name": "tenant", "value": tenant},
        {"name": "project_id", "value": project_id},
        {"name": "project_slug", "value": project_slug},
        {"name": "batch_id", "value": batch_id},
        {"name": "chunks_key", "value": chunks_key},
        {"name": "skip_agent", "value": "1" if skip_agent else "0"},
    ]


def _lifecycle_generate_prefix(project_slug: str, operation: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", project_slug.lower()).strip("-")
    if not slug:
        slug = "project"
    return f"{operation}-{slug}-"


def project_lifecycle_parameters(
    *,
    tenant: str,
    project_id: str,
    reason: str = "",
) -> list[dict[str, str]]:
    return [
        {"name": "tenant", "value": tenant},
        {"name": "project_id", "value": project_id},
        {"name": "reason", "value": reason},
    ]


async def submit_purge_project(
    *,
    settings: Settings,
    tenant: str,
    project_id: str,
    project_slug: str,
    reason: str = "",
) -> dict[str, str]:
    parameters = project_lifecycle_parameters(
        tenant=tenant, project_id=project_id, reason=reason
    )
    body = _workflow_body(
        settings=settings,
        tenant=tenant,
        template_name=settings.PATH_GRAPH_PURGE_PROJECT_WF_TEMPLATE,
        source_name=project_slug,
        parameters=parameters,
        generate_prefix=_lifecycle_generate_prefix(project_slug, "purge"),
    )
    return await _submit_workflow(settings=settings, body=body)


async def submit_delete_project(
    *,
    settings: Settings,
    tenant: str,
    project_id: str,
    project_slug: str,
    reason: str = "",
) -> dict[str, str]:
    parameters = project_lifecycle_parameters(
        tenant=tenant, project_id=project_id, reason=reason
    )
    body = _workflow_body(
        settings=settings,
        tenant=tenant,
        template_name=settings.PATH_GRAPH_DELETE_PROJECT_WF_TEMPLATE,
        source_name=project_slug,
        parameters=parameters,
        generate_prefix=_lifecycle_generate_prefix(project_slug, "delete"),
    )
    return await _submit_workflow(settings=settings, body=body)


async def submit_graphrag(
    *,
    settings: Settings,
    tenant: str,
    project_id: str,
    project_slug: str,
    batch_id: str,
    chunks_key: str,
) -> dict[str, str]:
    """Submit pipeline-graphrag Workflow."""
    parameters = graphrag_parameters(
        tenant=tenant,
        project_id=project_id,
        project_slug=project_slug,
        batch_id=batch_id,
        chunks_key=chunks_key,
    )
    body = _workflow_body(
        settings=settings,
        tenant=tenant,
        template_name=settings.PATH_GRAPH_GRAPHRAG_WF_TEMPLATE,
        source_name=project_slug,
        parameters=parameters,
        generate_prefix=_graphrag_generate_prefix(project_slug),
    )
    return await _submit_workflow(settings=settings, body=body)
