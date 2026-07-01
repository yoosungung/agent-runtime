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
_CRON_PLURAL = "cronworkflows"

_CRON_FIELD_RE = re.compile(r"^[\d*,/-]+$")


def validate_cron_schedule(schedule: str) -> str:
    """Validate a 5-field cron expression (minute hour dom month dow)."""
    expr = schedule.strip()
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("cron must have 5 fields: minute hour day month weekday")
    for part in parts:
        if not _CRON_FIELD_RE.match(part):
            raise ValueError(f"invalid cron field: {part}")
    return expr


def validate_cron_schedule_or_http(schedule: str) -> str:
    try:
        return validate_cron_schedule(schedule)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def cron_workflow_name(tenant: str, source_id: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", tenant.lower()).strip("-") or "tenant"
    short_id = source_id.replace("-", "")[:12]
    name = f"pg-cron-{slug}-{short_id}".lower()
    return name[:63].rstrip("-")


def project_reconcile_cron_name(tenant: str, project_id: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", tenant.lower()).strip("-") or "tenant"
    short_id = project_id.replace("-", "")[:12]
    name = f"pg-reconcile-{slug}-{short_id}".lower()
    return name[:63].rstrip("-")


def build_cron_workflow_body(
    *,
    name: str,
    namespace: str,
    schedule: str,
    template_name: str,
    tenant: str,
    source_id: str,
    credential_secret: str = "",
    suspend: bool = False,
) -> dict[str, Any]:
    return {
        "apiVersion": f"{_ARGO_GROUP}/{_ARGO_VERSION}",
        "kind": "CronWorkflow",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "path-graph/managed-by": "backend",
                "path-graph/tenant": tenant[:63],
                "path-graph/source-id": source_id[:63],
            },
        },
        "spec": {
            "schedule": schedule,
            "timezone": "UTC",
            "suspend": suspend,
            "concurrencyPolicy": "Forbid",
            "startingDeadlineSeconds": 300,
            "workflowSpec": {
                "serviceAccountName": "path-graph-pipeline",
                "workflowTemplateRef": {"name": template_name},
                "arguments": {
                    "parameters": [
                        {"name": "tenant", "value": tenant},
                        {"name": "source_id", "value": source_id},
                        {"name": "batch_id", "value": ""},
                        {"name": "credential_secret", "value": credential_secret},
                        {"name": "rag", "value": "true"},
                        {"name": "sync_mode", "value": ""},
                    ]
                },
            },
        },
    }


def build_project_reconcile_cron_body(
    *,
    name: str,
    namespace: str,
    schedule: str,
    template_name: str,
    tenant: str,
    project_id: str,
) -> dict[str, Any]:
    return {
        "apiVersion": f"{_ARGO_GROUP}/{_ARGO_VERSION}",
        "kind": "CronWorkflow",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "path-graph/managed-by": "backend",
                "path-graph/tenant": tenant[:63],
                "path-graph/project-id": project_id[:63],
            },
        },
        "spec": {
            "schedule": schedule,
            "timezone": "UTC",
            "suspend": False,
            "concurrencyPolicy": "Forbid",
            "startingDeadlineSeconds": 300,
            "workflowSpec": {
                "serviceAccountName": "path-graph-pipeline",
                "workflowTemplateRef": {"name": template_name},
                "arguments": {
                    "parameters": [
                        {"name": "tenant", "value": tenant},
                        {"name": "project_id", "value": project_id},
                    ]
                },
            },
        },
    }


async def _delete_cron_workflow(*, settings: Settings, name: str) -> None:
    api_client = None
    try:
        api_client = await make_api_client(settings)
        custom = k8s_client.CustomObjectsApi(api_client)
        await custom.delete_namespaced_custom_object(
            group=_ARGO_GROUP,
            version=_ARGO_VERSION,
            namespace=settings.PATH_GRAPH_ARGO_NAMESPACE,
            plural=_CRON_PLURAL,
            name=name,
        )
    except ApiException as exc:
        if exc.status == 404:
            return
        logger.warning("cron delete failed", extra={"status": exc.status, "name": name})
        raise _argo_http_error(exc) from exc
    except Exception as exc:
        logger.warning("argo cron client unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Argo CronWorkflows unavailable — connect to cluster",
        ) from exc
    finally:
        if api_client is not None:
            await api_client.close()


async def _upsert_cron_workflow(*, settings: Settings, body: dict[str, Any]) -> None:
    api_client = None
    name = body["metadata"]["name"]
    namespace = body["metadata"]["namespace"]
    try:
        api_client = await make_api_client(settings)
        custom = k8s_client.CustomObjectsApi(api_client)
        try:
            await custom.get_namespaced_custom_object(
                group=_ARGO_GROUP,
                version=_ARGO_VERSION,
                namespace=namespace,
                plural=_CRON_PLURAL,
                name=name,
            )
            await custom.replace_namespaced_custom_object(
                group=_ARGO_GROUP,
                version=_ARGO_VERSION,
                namespace=namespace,
                plural=_CRON_PLURAL,
                name=name,
                body=body,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            await custom.create_namespaced_custom_object(
                group=_ARGO_GROUP,
                version=_ARGO_VERSION,
                namespace=namespace,
                plural=_CRON_PLURAL,
                body=body,
            )
    except ApiException as exc:
        logger.warning("cron upsert failed", extra={"status": exc.status, "name": name})
        raise _argo_http_error(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("argo cron client unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Argo CronWorkflows unavailable — connect to cluster",
        ) from exc
    finally:
        if api_client is not None:
            await api_client.close()


def _argo_http_error(exc: ApiException) -> HTTPException:
    if exc.status in (401, 403):
        return HTTPException(
            status_code=503,
            detail="Argo CronWorkflow API not authorized — check cluster RBAC",
        )
    return HTTPException(
        status_code=503,
        detail=f"Argo cron reconcile failed: {exc.reason or exc.status}",
    )


async def reconcile_source_cron(
    *,
    settings: Settings,
    tenant: str,
    source_id: str,
    schedule_cron: str | None,
    credential_secret: str = "",
    suspend: bool = False,
) -> None:
    """Create, update, or delete CronWorkflow for a source schedule."""
    name = cron_workflow_name(tenant, source_id)
    if not (schedule_cron or "").strip():
        await _delete_cron_workflow(settings=settings, name=name)
        return

    schedule = validate_cron_schedule(schedule_cron)
    body = build_cron_workflow_body(
        name=name,
        namespace=settings.PATH_GRAPH_ARGO_NAMESPACE,
        schedule=schedule,
        template_name=settings.PATH_GRAPH_COLLECT_WF_TEMPLATE,
        tenant=tenant,
        source_id=source_id,
        credential_secret=credential_secret,
        suspend=suspend,
    )
    await _upsert_cron_workflow(settings=settings, body=body)


async def delete_source_cron(*, settings: Settings, tenant: str, source_id: str) -> None:
    await _delete_cron_workflow(
        settings=settings,
        name=cron_workflow_name(tenant, source_id),
    )


async def reconcile_project_cron(
    *,
    settings: Settings,
    tenant: str,
    project_id: str,
) -> None:
    """Create or update daily index-reconcile CronWorkflow for a project."""
    schedule = validate_cron_schedule(settings.PATH_GRAPH_RECONCILE_CRON_SCHEDULE)
    body = build_project_reconcile_cron_body(
        name=project_reconcile_cron_name(tenant, project_id),
        namespace=settings.PATH_GRAPH_ARGO_NAMESPACE,
        schedule=schedule,
        template_name=settings.PATH_GRAPH_RECONCILE_WF_TEMPLATE,
        tenant=tenant,
        project_id=project_id,
    )
    await _upsert_cron_workflow(settings=settings, body=body)


async def delete_project_reconcile_cron(
    *,
    settings: Settings,
    tenant: str,
    project_id: str,
) -> None:
    await _delete_cron_workflow(
        settings=settings,
        name=project_reconcile_cron_name(tenant, project_id),
    )
