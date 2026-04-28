"""Kubernetes client helpers for custom image mode deployments.

Creates/updates/deletes Deployment + Service + ScaledObject + PodDisruptionBudget
for each custom image registration. All operations are scoped to the runtime namespace.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import config as k8s_config
from kubernetes_asyncio.client import ApiClient

from backend.settings import Settings

logger = logging.getLogger(__name__)

# Labels applied to all dynamically-managed resources so NetworkPolicy can select them.
_MANAGED_LABELS = {
    "runtime/managed-by": "backend",
    "runtime/role": "pool",
}


async def make_api_client(settings: Settings) -> ApiClient:
    """Create a kubernetes ApiClient using in-cluster config or kubeconfig."""
    if settings.K8S_IN_CLUSTER:
        k8s_config.load_incluster_config()
    else:
        await k8s_config.load_kube_config()
    return ApiClient()


def _deployment_manifest(
    kind: str,
    slug: str,
    image_uri: str,
    image_digest: str | None,
    namespace: str,
    replicas_max: int,
    resources: dict | None,
    image_pull_secret: str | None,
    env_vars: dict[str, str] | None,
    deploy_api_url: str,
) -> dict[str, Any]:
    image_ref = f"{image_uri}@{image_digest}" if image_digest else image_uri
    name = f"{kind}-pool-custom-{slug}"

    container_env = [
        {"name": "RUNTIME_POOL", "value": f"{kind}:custom:{slug}"},
        {"name": "DEPLOY_API_URL", "value": deploy_api_url},
        {"name": "POD_NAME", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
        {"name": "POD_IP", "valueFrom": {"fieldRef": {"fieldPath": "status.podIP"}}},
        {"name": "POD_PORT", "value": "8080"},
    ]
    if env_vars:
        for k, v in env_vars.items():
            container_env.append({"name": k, "value": v})

    container: dict[str, Any] = {
        "name": "pool",
        "image": image_ref,
        "ports": [{"containerPort": 8080, "name": "http"}],
        "env": container_env,
        "readinessProbe": {
            "httpGet": {"path": "/readyz", "port": 8080},
            "initialDelaySeconds": 5,
            "periodSeconds": 5,
        },
        "livenessProbe": {
            "httpGet": {"path": "/healthz", "port": 8080},
            "initialDelaySeconds": 10,
            "periodSeconds": 15,
        },
    }
    if resources:
        container["resources"] = resources

    image_pull_secrets = [{"name": image_pull_secret}] if image_pull_secret else []

    labels = {**_MANAGED_LABELS, "app": name, "runtime/kind": kind, "runtime/slug": slug}

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "replicas": 1,  # KEDA will manage scale; start with 1
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "serviceAccountName": "pool-base",
                    "containers": [container],
                    "imagePullSecrets": image_pull_secrets,
                },
            },
        },
    }


def _service_manifest(kind: str, slug: str, namespace: str) -> dict[str, Any]:
    name = f"{kind}-pool-custom-{slug}"
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {**_MANAGED_LABELS, "app": name},
        },
        "spec": {
            "selector": {"app": name},
            "ports": [{"port": 8080, "targetPort": 8080, "name": "http"}],
        },
    }


def _scaled_object_manifest(
    kind: str, slug: str, namespace: str, replicas_max: int
) -> dict[str, Any]:
    name = f"{kind}-pool-custom-{slug}"
    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {**_MANAGED_LABELS, "app": name},
        },
        "spec": {
            "scaleTargetRef": {"name": name},
            "minReplicaCount": 1,
            "maxReplicaCount": replicas_max,
            "triggers": [
                {
                    "type": "prometheus",
                    "metadata": {
                        "serverAddress": "http://prometheus.monitoring.svc.cluster.local:9090",
                        "query": f'sum(rate(http_requests_total{{service="{name}"}}[1m]))',
                        "threshold": "10",
                    },
                }
            ],
        },
    }


def _pdb_manifest(kind: str, slug: str, namespace: str) -> dict[str, Any]:
    name = f"{kind}-pool-custom-{slug}"
    return {
        "apiVersion": "policy/v1",
        "kind": "PodDisruptionBudget",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {**_MANAGED_LABELS, "app": name},
        },
        "spec": {
            "minAvailable": 1,
            "selector": {"matchLabels": {"app": name}},
        },
    }


class K8sPoolManager:
    """Manages lifecycle of custom image pool K8s resources."""

    def __init__(self, api_client: ApiClient, settings: Settings) -> None:
        self._api_client = api_client
        self._settings = settings
        self._ns = settings.K8S_RUNTIME_NAMESPACE
        self._apps = k8s_client.AppsV1Api(api_client)
        self._core = k8s_client.CoreV1Api(api_client)
        self._custom = k8s_client.CustomObjectsApi(api_client)
        self._policy = k8s_client.PolicyV1Api(api_client)

    async def create_pool(
        self,
        *,
        kind: str,
        slug: str,
        image_uri: str,
        image_digest: str | None,
        replicas_max: int,
        resources: dict | None,
        image_pull_secret: str | None,
        env_vars: dict[str, str] | None,
        deploy_api_url: str,
    ) -> None:
        """Create Deployment + Service + ScaledObject + PDB for a new image pool."""
        name = f"{kind}-pool-custom-{slug}"
        logger.info("k8s.create_pool start", extra={"pool": name})

        dep = _deployment_manifest(
            kind=kind,
            slug=slug,
            image_uri=image_uri,
            image_digest=image_digest,
            namespace=self._ns,
            replicas_max=replicas_max,
            resources=resources,
            image_pull_secret=image_pull_secret,
            env_vars=env_vars,
            deploy_api_url=deploy_api_url,
        )
        svc = _service_manifest(kind, slug, self._ns)
        so = _scaled_object_manifest(kind, slug, self._ns, replicas_max)
        pdb = _pdb_manifest(kind, slug, self._ns)

        await self._apps.create_namespaced_deployment(self._ns, dep)
        await self._core.create_namespaced_service(self._ns, svc)
        await self._custom.create_namespaced_custom_object(
            group="keda.sh", version="v1alpha1", namespace=self._ns,
            plural="scaledobjects", body=so,
        )
        await self._policy.create_namespaced_pod_disruption_budget(self._ns, pdb)
        logger.info("k8s.create_pool done", extra={"pool": name})

    async def wait_ready(self, kind: str, slug: str, timeout_sec: int = 60) -> bool:
        """Poll until Deployment has at least 1 available replica, or timeout."""
        name = f"{kind}-pool-custom-{slug}"
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            dep = await self._apps.read_namespaced_deployment(name, self._ns)
            available = (dep.status.available_replicas or 0) if dep.status else 0
            if available >= 1:
                return True
            await asyncio.sleep(3)
        return False

    async def delete_pool(self, kind: str, slug: str) -> None:
        """Delete all four K8s resources for an image pool. Errors are logged, not raised."""
        name = f"{kind}-pool-custom-{slug}"
        logger.info("k8s.delete_pool start", extra={"pool": name})
        errors: list[str] = []

        for coro in [
            self._delete_deployment(name),
            self._delete_service(name),
            self._delete_scaled_object(name),
            self._delete_pdb(name),
        ]:
            try:
                await coro
            except Exception as exc:
                errors.append(str(exc))

        if errors:
            logger.warning("k8s.delete_pool partial errors", extra={"pool": name, "errors": errors})
        else:
            logger.info("k8s.delete_pool done", extra={"pool": name})

    async def _delete_deployment(self, name: str) -> None:
        from kubernetes_asyncio.client.exceptions import ApiException
        try:
            await self._apps.delete_namespaced_deployment(name, self._ns)
        except ApiException as exc:
            if exc.status != 404:
                raise

    async def _delete_service(self, name: str) -> None:
        from kubernetes_asyncio.client.exceptions import ApiException
        try:
            await self._core.delete_namespaced_service(name, self._ns)
        except ApiException as exc:
            if exc.status != 404:
                raise

    async def _delete_scaled_object(self, name: str) -> None:
        from kubernetes_asyncio.client.exceptions import ApiException
        try:
            await self._custom.delete_namespaced_custom_object(
                group="keda.sh", version="v1alpha1", namespace=self._ns,
                plural="scaledobjects", name=name,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

    async def _delete_pdb(self, name: str) -> None:
        from kubernetes_asyncio.client.exceptions import ApiException
        try:
            await self._policy.delete_namespaced_pod_disruption_budget(name, self._ns)
        except ApiException as exc:
            if exc.status != 404:
                raise

    async def patch_deployment(
        self,
        kind: str,
        slug: str,
        replicas_max: int | None = None,
        resources: dict | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> None:
        """Patch Deployment env/resources and ScaledObject maxReplicaCount."""
        name = f"{kind}-pool-custom-{slug}"
        patches: list[dict] = []

        if resources is not None:
            patches.append({
                "op": "replace",
                "path": "/spec/template/spec/containers/0/resources",
                "value": resources,
            })

        if env_vars is not None:
            # Merge new env into existing (simple list patch replaces the segment)
            new_env = [{"name": k, "value": v} for k, v in env_vars.items()]
            patches.append({
                "op": "add",
                "path": "/spec/template/spec/containers/0/env/-",
                "value": new_env,
            })

        if patches:
            await self._apps.patch_namespaced_deployment(
                name, self._ns, patches,
                _content_type="application/json-patch+json",
            )

        if replicas_max is not None:
            so_patch = [{"op": "replace", "path": "/spec/maxReplicaCount", "value": replicas_max}]
            await self._custom.patch_namespaced_custom_object(
                group="keda.sh", version="v1alpha1", namespace=self._ns,
                plural="scaledobjects", name=name, body=so_patch,
                _content_type="application/json-patch+json",
            )

    async def restart_pool(self, kind: str, slug: str) -> None:
        """Trigger a rolling restart by patching the restartedAt annotation."""
        from datetime import timezone

        import datetime

        name = f"{kind}-pool-custom-{slug}"
        now = datetime.datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                    }
                }
            }
        }
        await self._apps.patch_namespaced_deployment(name, self._ns, patch)
        logger.info("k8s.restart_pool done", extra={"pool": name})

    async def deployment_exists(self, kind: str, slug: str) -> bool:
        """Return True if the Deployment exists in K8s."""
        from kubernetes_asyncio.client.exceptions import ApiException
        name = f"{kind}-pool-custom-{slug}"
        try:
            await self._apps.read_namespaced_deployment(name, self._ns)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    async def aclose(self) -> None:
        await self._api_client.close()
