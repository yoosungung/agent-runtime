"""Fetch pipeline knowledge bindings from admin backend (cluster-internal)."""

from __future__ import annotations

import httpx

_RUNTIME_CALLER = "agent-pool"
_DEFAULT_TIMEOUT_SEC = 30.0


def fetch_project_binding(
    admin_backend_url: str,
    tenant: str,
    project_id: str,
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
) -> dict:
    """Return binding JSON for tenant/project (sync — use via asyncio.to_thread)."""
    base = admin_backend_url.rstrip("/")
    url = f"{base}/internal/v1/pipeline/tenants/{tenant}/projects/{project_id}/binding"
    response = httpx.get(
        url,
        headers={"X-Runtime-Caller": _RUNTIME_CALLER},
        timeout=timeout_sec,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("binding response must be a JSON object")
    return payload
