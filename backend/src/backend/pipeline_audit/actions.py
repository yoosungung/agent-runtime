from __future__ import annotations

from typing import Any

from backend.pipeline_audit.context import PIPELINE_AUDIT_DOMAIN, PIPELINE_ROUTE_PREFIX
from runtime_common.schemas import Principal

# Router-relative paths (prefix /api/pipeline). Dry-run probe excluded.
_MUTATION_ACTIONS: dict[tuple[str, str], str] = {
    ("POST", "/projects"): "pipeline.project.create",
    ("POST", "/projects/{project_id}/reconcile"): "pipeline.project.reconcile",
    ("POST", "/projects/{project_id}/cleanup"): "pipeline.project.cleanup",
    ("POST", "/projects/{project_id}/purge"): "pipeline.project.purge",
    ("POST", "/projects/{project_id}/delete"): "pipeline.project.delete",
    ("POST", "/projects/{project_id}/graphrag"): "pipeline.project.graphrag",
    ("POST", "/sources"): "pipeline.source.create",
    ("PATCH", "/sources/{source_id}"): "pipeline.source.update",
    ("DELETE", "/sources/{source_id}"): "pipeline.source.delete",
    ("POST", "/sources/{source_id}/run"): "pipeline.source.run",
    ("POST", "/sources/{source_id}/upload"): "pipeline.source.upload",
    ("POST", "/sources/{source_id}/purge"): "pipeline.source.purge",
    ("POST", "/sources/{source_id}/ingest"): "pipeline.source.ingest",
    ("POST", "/documents/{document_id}/purge"): "pipeline.document.purge",
    ("POST", "/documents/{document_id}/restore"): "pipeline.document.restore",
    ("POST", "/documents/{document_id}/reingest"): "pipeline.document.reingest",
    ("POST", "/credentials"): "pipeline.credential.create",
    ("DELETE", "/credentials/{credential_id}"): "pipeline.credential.delete",
    ("PUT", "/credentials/{credential_id}/secrets"): "pipeline.credential.secrets_put",
}


def _route_suffix(path: str) -> str:
    if path.startswith(PIPELINE_ROUTE_PREFIX):
        suffix = path[len(PIPELINE_ROUTE_PREFIX) :]
        return suffix or "/"
    return path


def resolve_audit_action(methods: set[str], path: str) -> str | None:
    suffix = _route_suffix(path)
    for method in sorted(methods):
        if method in {"GET", "HEAD", "OPTIONS"}:
            continue
        action = _MUTATION_ACTIONS.get((method, suffix))
        if action is not None:
            return action
    return None


def _model_fields(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=True)
    if isinstance(obj, dict):
        return dict(obj)
    fields: dict[str, Any] = {}
    for key in (
        "id",
        "project_id",
        "source_id",
        "document_id",
        "credential_id",
        "slug",
        "name",
        "batch_id",
        "workflow_name",
        "argo_uid",
        "file_count",
        "uploaded",
        "skipped",
        "reason",
        "dry_run",
        "hard_raw",
    ):
        if hasattr(obj, key):
            value = getattr(obj, key)
            if value is not None:
                fields[key] = value
    return fields


def build_audit_details(
    action: str,
    *,
    kwargs: dict[str, Any],
    result: Any,
    principal: Principal,
) -> dict[str, Any]:
    details: dict[str, Any] = {"domain": PIPELINE_AUDIT_DOMAIN}
    tenant = (principal.tenant or "").strip()
    if tenant:
        details["tenant"] = tenant

    body = kwargs.get("body")
    body_fields = _model_fields(body)
    secrets = body_fields.pop("secrets", None)
    if secrets is None and body is not None:
        secrets = getattr(body, "secrets", None)
    if isinstance(secrets, dict):
        details["secret_keys"] = sorted(secrets.keys())
    details.update({k: v for k, v in body_fields.items() if k not in details})

    for key in ("project_id", "source_id", "document_id", "credential_id"):
        value = kwargs.get(key)
        if value is not None and key not in details:
            details[key] = value

    response_fields = _model_fields(result)
    for key, value in response_fields.items():
        if key not in details and key != "domain":
            details[key] = value

    if action == "pipeline.project.create" and "project_id" not in details:
        project_id = response_fields.get("id")
        if project_id is not None:
            details["project_id"] = project_id
    elif action == "pipeline.source.create" and "source_id" not in details:
        source_id = response_fields.get("id")
        if source_id is not None:
            details["source_id"] = source_id
    elif action == "pipeline.credential.create" and "credential_id" not in details:
        credential_id = response_fields.get("id")
        if credential_id is not None:
            details["credential_id"] = credential_id

    if action == "pipeline.source.upload" and "file_count" not in details:
        uploaded = details.get("uploaded")
        if isinstance(uploaded, int):
            details["file_count"] = uploaded

    ingest_ids = getattr(body, "document_ids", None) if body is not None else None
    if ingest_ids and "document_ids" not in details:
        details["document_ids"] = list(ingest_ids)

    return details
