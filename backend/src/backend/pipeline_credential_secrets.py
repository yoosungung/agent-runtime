from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

from backend.settings import Settings

logger = logging.getLogger(__name__)


class CredentialSecretStore(Protocol):
    async def read(self, secret_name: str) -> dict[str, str]: ...
    async def write(self, secret_name: str, secrets: dict[str, str]) -> None: ...
    async def delete_secret(self, secret_name: str) -> None: ...


class LocalCredentialSecretStore:
    """Dev fallback when K8s is unavailable — gitignored directory."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, secret_name: str) -> Path:
        safe = secret_name.replace("/", "_")
        return self._root / f"{safe}.json"

    async def read(self, secret_name: str) -> dict[str, str]:
        path = self._path(secret_name)
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}

    async def write(self, secret_name: str, secrets: dict[str, str]) -> None:
        path = self._path(secret_name)
        existing: dict[str, str] = {}
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
        existing.update(secrets)
        path.write_text(json.dumps(existing), encoding="utf-8")

    async def delete_secret(self, secret_name: str) -> None:
        path = self._path(secret_name)
        if path.exists():
            path.unlink()


class K8sCredentialSecretStore:
    def __init__(self, k8s_core, namespace: str) -> None:
        self._core = k8s_core
        self._ns = namespace

    async def read(self, secret_name: str) -> dict[str, str]:
        import base64

        from kubernetes_asyncio.client.exceptions import ApiException

        try:
            secret = await self._core.read_namespaced_secret(secret_name, self._ns)
        except ApiException as exc:
            if exc.status == 404:
                return {}
            raise
        data = secret.data or {}
        return {key: base64.b64decode(value).decode("utf-8") for key, value in data.items()}

    async def write(self, secret_name: str, secrets: dict[str, str]) -> None:
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": secret_name,
                "namespace": self._ns,
                "labels": {
                    "path-graph/managed-by": "backend",
                    "path-graph/role": "source-credential",
                },
            },
            "type": "Opaque",
            "stringData": secrets,
        }
        from kubernetes_asyncio.client.exceptions import ApiException

        try:
            await self._core.replace_namespaced_secret(secret_name, self._ns, body)
        except ApiException as exc:
            if exc.status != 404:
                raise
            await self._core.create_namespaced_secret(self._ns, body)

    async def delete_secret(self, secret_name: str) -> None:
        from kubernetes_asyncio.client.exceptions import ApiException

        try:
            await self._core.delete_namespaced_secret(secret_name, self._ns)
        except ApiException as exc:
            if exc.status != 404:
                raise


async def make_credential_secret_store(
    settings: Settings,
    request,
) -> CredentialSecretStore:
    k8s = getattr(request.app.state, "k8s_pool_manager", None)
    if k8s is not None:
        return K8sCredentialSecretStore(k8s._core, settings.PATH_GRAPH_CREDENTIAL_NAMESPACE)
    logger.info("pipeline credentials: using local secret store (no k8s_pool_manager)")
    return LocalCredentialSecretStore(settings.PIPELINE_CREDENTIAL_LOCAL_DIR)
