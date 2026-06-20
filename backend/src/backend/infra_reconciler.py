"""Reconcile infra_meta DB state to K8s ConfigMap/Secret and restart pool pods."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from runtime_common.infra_env import infra_config_to_env

if TYPE_CHECKING:
    from backend.k8s_client import K8sPoolManager

logger = logging.getLogger(__name__)


async def reconcile_infra(
    k8s: K8sPoolManager,
    *,
    env: dict,
    secrets_patch: dict[str, str] | None,
) -> list[str]:
    """Apply infra env to ConfigMap, merge secrets into Secret, restart pool Deployments."""
    flat_env = infra_config_to_env(env)
    await k8s.apply_infra_configmap(flat_env)

    if secrets_patch is not None:
        merged = {**(await k8s.read_infra_secrets()), **secrets_patch}
    else:
        merged = await k8s.read_infra_secrets()
    await k8s.apply_infra_secret(merged)

    restarted = await k8s.restart_infra_pool_deployments()
    logger.info(
        "infra_reconciler.done",
        extra={"env_keys": sorted(flat_env.keys()), "secret_keys": sorted(merged.keys())},
    )
    return restarted
