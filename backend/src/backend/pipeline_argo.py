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


def _workflow_body(
    *,
    settings: Settings,
    tenant: str,
    template_name: str,
    source_name: str,
    parameters: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "apiVersion": f"{_ARGO_GROUP}/{_ARGO_VERSION}",
        "kind": "Workflow",
        "metadata": {
            "generateName": _collect_generate_prefix(source_name)
            if template_name == settings.PATH_GRAPH_COLLECT_WF_TEMPLATE
            else _safe_generate_prefix(source_name),
            "namespace": settings.PATH_GRAPH_ARGO_NAMESPACE,
        },
        "spec": {
            "workflowTemplateRef": {"name": template_name},
            "arguments": {"parameters": parameters},
        },
    }


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
    parameters = [
        {"name": "tenant", "value": tenant},
        {"name": "batch_manifest", "value": batch_manifest_json},
        {"name": "batch_manifest_key", "value": batch_manifest_key},
        {"name": "rag", "value": "true"},
    ]
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
) -> dict[str, str]:
    """Submit pipeline-collect-ingest-rag Workflow (async Run now)."""
    parameters = [
        {"name": "tenant", "value": tenant},
        {"name": "source_id", "value": source_id},
        {"name": "batch_id", "value": batch_id},
        {"name": "credential_secret", "value": credential_secret},
        {"name": "rag", "value": "true"},
    ]
    body = _workflow_body(
        settings=settings,
        tenant=tenant,
        template_name=settings.PATH_GRAPH_COLLECT_WF_TEMPLATE,
        source_name=source_name,
        parameters=parameters,
    )
    return await _submit_workflow(settings=settings, body=body)
