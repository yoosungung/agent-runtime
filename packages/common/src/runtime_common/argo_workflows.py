from __future__ import annotations

from typing import Any

import httpx


def _auth_header(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


async def resume_workflow(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    token: str | None,
    namespace: str,
    workflow: str,
    node_field_selector: str = "",
) -> None:
    url = f"{base_url.rstrip('/')}/api/v1/workflows/{namespace}/{workflow}/resume"
    body: dict[str, Any] = {"namespace": namespace, "name": workflow}
    if node_field_selector:
        body["nodeFieldSelector"] = node_field_selector
    resp = await client.put(url, json=body, headers=_auth_header(token))
    resp.raise_for_status()


async def stop_workflow(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    token: str | None,
    namespace: str,
    workflow: str,
    node_field_selector: str = "",
    message: str = "",
) -> None:
    url = f"{base_url.rstrip('/')}/api/v1/workflows/{namespace}/{workflow}/stop"
    body: dict[str, Any] = {"namespace": namespace, "name": workflow}
    if node_field_selector:
        body["nodeFieldSelector"] = node_field_selector
    if message:
        body["message"] = message
    resp = await client.put(url, json=body, headers=_auth_header(token))
    resp.raise_for_status()
