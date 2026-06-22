"""Reconcile infra_meta & llm_presets DB state to K8s ConfigMap/Secret and restart pool pods."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from runtime_common.db.models import InfraMetaRow, LlmPresetRow
from runtime_common.infra_env import normalize_stored_env

if TYPE_CHECKING:
    from backend.k8s_client import K8sPoolManager

logger = logging.getLogger(__name__)

_GLOBAL_SCOPE = "global"
_GLOBAL_SCOPE_KEY = ""


async def reconcile_infra(
    k8s: K8sPoolManager,
    db: AsyncSession,
    *,
    secrets_patch: dict[str, str] | None = None,
    secrets_delete: list[str] | None = None,
) -> list[str]:
    """Apply infra env & presets to ConfigMap, merge secrets into Secret, restart pool Deployments.

    Fetches the global infra_meta and all llm_presets to build a consistent state.
    """
    # 1. Fetch global infra_meta
    infra_res = await db.execute(
        select(InfraMetaRow).where(
            InfraMetaRow.scope == _GLOBAL_SCOPE,
            InfraMetaRow.scope_key == _GLOBAL_SCOPE_KEY,
        )
    )
    infra_row = infra_res.scalar_one_or_none()
    db_env = infra_row.env if (infra_row and isinstance(infra_row.env, dict)) else {}
    flat_env = normalize_stored_env(db_env)

    # 2. Fetch all LLM presets
    presets_res = await db.execute(select(LlmPresetRow))
    presets = presets_res.scalars().all()

    default_preset: LlmPresetRow | None = None

    # Inject LLM Presets to flat_env
    for p in presets:
        prefix = f"LLM_PRESET_{p.name}"
        flat_env[f"{prefix}_MODE"] = p.mode
        flat_env[f"{prefix}_MODEL_ID"] = p.model_id
        if p.frontier_provider:
            flat_env[f"{prefix}_PROVIDER"] = p.frontier_provider
        if p.openai_api_base:
            flat_env[f"{prefix}_API_BASE"] = p.openai_api_base
        if p.slm_runtime:
            flat_env[f"{prefix}_SLM_RUNTIME"] = p.slm_runtime

        if p.is_default:
            default_preset = p

    # Map default preset variables for backward compatibility
    if default_preset is not None:
        p = default_preset
        if p.mode == "openai_compatible":
            flat_env["DEFAULT_LLM_MODEL"] = f"openai:{p.model_id}"
            flat_env["LLM_RUNTIME"] = p.slm_runtime or ""
            flat_env["OPENAI_API_BASE"] = p.openai_api_base or ""
        else:
            provider = p.frontier_provider or "openai"
            flat_env["DEFAULT_LLM_MODEL"] = f"{provider}:{p.model_id}"
            # Clear incompatible variables
            flat_env.pop("LLM_RUNTIME", None)
            flat_env.pop("OPENAI_API_BASE", None)
    else:
        # If no default preset, remove the legacy fallback environment variables
        flat_env.pop("DEFAULT_LLM_MODEL", None)
        flat_env.pop("LLM_RUNTIME", None)
        flat_env.pop("OPENAI_API_BASE", None)

    # Apply flat env to ConfigMap
    await k8s.apply_infra_configmap(flat_env)

    # 3. Handle secrets
    k8s_secrets = await k8s.read_infra_secrets()

    # Data Migration helper: If default preset exists and legacy key is present but no preset secret key,
    # copy the legacy key to preset key (first-time deployment migration)
    if default_preset is not None:
        p = default_preset
        preset_key_name = f"LLM_PRESET_{p.name}_API_KEY"
        if preset_key_name not in k8s_secrets and (not secrets_patch or preset_key_name not in secrets_patch):
            legacy_keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
            migrated_val = None
            for lk in legacy_keys:
                if lk in k8s_secrets:
                    migrated_val = k8s_secrets[lk]
                    break
            if migrated_val:
                if secrets_patch is None:
                    secrets_patch = {}
                secrets_patch[preset_key_name] = migrated_val
                logger.info(
                    "infra_reconciler.migrate_legacy_key_to_preset",
                    extra={"preset_key": preset_key_name},
                )

    # Apply deletions
    if secrets_delete:
        for key in secrets_delete:
            k8s_secrets.pop(key, None)

    # Apply patches
    if secrets_patch:
        for key, value in secrets_patch.items():
            if value == "":
                k8s_secrets.pop(key, None)
            else:
                k8s_secrets[key] = value

    # Clean up orphaned preset API keys
    existing_preset_names = {p.name for p in presets}
    for secret_key in list(k8s_secrets.keys()):
        if secret_key.startswith("LLM_PRESET_") and secret_key.endswith("_API_KEY"):
            # Extract preset name
            name_candidate = secret_key[len("LLM_PRESET_"):-len("_API_KEY")]
            if name_candidate not in existing_preset_names:
                k8s_secrets.pop(secret_key, None)

    # For default preset, copy API Key to target provider's default env key for backward compatibility
    if default_preset is not None:
        p = default_preset
        preset_key_name = f"LLM_PRESET_{p.name}_API_KEY"
        default_api_key = k8s_secrets.get(preset_key_name)

        if default_api_key:
            if p.mode == "openai_compatible":
                k8s_secrets["OPENAI_API_KEY"] = default_api_key
            else:
                provider = p.frontier_provider or "openai"
                if provider == "openai":
                    k8s_secrets["OPENAI_API_KEY"] = default_api_key
                elif provider == "anthropic":
                    k8s_secrets["ANTHROPIC_API_KEY"] = default_api_key
                elif provider == "google":
                    k8s_secrets["GOOGLE_API_KEY"] = default_api_key
    else:
        # Clear legacy provider keys if no default preset, unless they are global infra secrets
        global_secrets = getattr(infra_row, "secret_keys", []) or []
        if not isinstance(global_secrets, list):
            global_secrets = []
        for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]:
            if k in global_secrets:
                continue
            if secrets_patch and k in secrets_patch and secrets_patch[k] != "":
                continue
            k8s_secrets.pop(k, None)

    await k8s.apply_infra_secret(k8s_secrets)

    restarted = await k8s.restart_infra_pool_deployments()
    logger.info(
        "infra_reconciler.done",
        extra={"env_keys": sorted(flat_env.keys()), "secret_keys": sorted(k8s_secrets.keys())},
    )
    return restarted
