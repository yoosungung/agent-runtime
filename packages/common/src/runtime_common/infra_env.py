"""infra_meta env validation — flat container env var names (comprehensive API)."""

from __future__ import annotations

import re

# Env var names for infra_meta (UPPER_SNAKE — matches pool env convention).
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Keys reserved by the platform — must not appear in infra_meta env or secrets.
RESERVED_INFRA_ENV_KEYS: frozenset[str] = frozenset(
    {
        "RUNTIME_POOL",
        "DEPLOY_API_URL",
        "POD_NAME",
        "POD_IP",
        "POD_PORT",
        "RUNTIME_KIND",
        "SERVICE_NAME",
        "HOSTNAME",
    }
)

# Legacy InfraConfig (snake_case) → flat env — normalize on read/write migration.
_LEGACY_ENV_ALIASES: dict[str, str] = {
    "opik_url": "OPIK_URL",
    "opik_workspace": "OPIK_WORKSPACE",
    "default_llm_model": "DEFAULT_LLM_MODEL",
    "openai_api_base": "OPENAI_API_BASE",
    "llm_runtime": "LLM_RUNTIME",
    "otlp_endpoint": "OTLP_ENDPOINT",
}


def validate_infra_env_key(key: str) -> None:
    if key in RESERVED_INFRA_ENV_KEYS:
        raise ValueError(f"env key {key!r} is reserved by the platform")
    if not _ENV_KEY_RE.match(key):
        raise ValueError(f"env key {key!r} must match [A-Z][A-Z0-9_]* (container env var name)")


def normalize_stored_env(env: dict) -> dict[str, str]:
    """Return flat UPPER_SNAKE env, migrating legacy snake_case keys if present."""
    flat: dict[str, str] = {}
    for key, value in env.items():
        if value is None:
            continue
        out_key = _LEGACY_ENV_ALIASES.get(key, key)
        validate_infra_env_key(out_key)
        flat[out_key] = str(value)
    return flat


def validate_infra_env_patch(patch: dict) -> dict[str, str]:
    """Validate a partial env patch (flat container env var names)."""
    validated: dict[str, str] = {}
    for key, value in patch.items():
        validate_infra_env_key(key)
        if value is None:
            validated[key] = ""
        elif not isinstance(value, str):
            raise ValueError(f"env value for {key!r} must be a string")
        else:
            validated[key] = value
    return validated


def merge_infra_env(existing: dict, patch: dict[str, str]) -> dict[str, str]:
    """Shallow merge env patch into existing flat env. Empty string removes a key."""
    merged = dict(existing)
    for key, value in patch.items():
        if value == "":
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def validate_infra_secret_keys(keys: list[str]) -> list[str]:
    """Ensure secret env var names are valid (no whitelist — comprehensive API)."""
    normalized: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        validate_infra_env_key(key)
        seen.add(key)
        normalized.append(key)
    return normalized


def validate_infra_secrets_input(secrets: dict[str, str]) -> dict[str, str]:
    """Validate PUT body secrets dict (key → plaintext value for K8s only)."""
    if not secrets:
        return {}
    validated: dict[str, str] = {}
    for key, value in secrets.items():
        validate_infra_env_key(key)
        if not isinstance(value, str):
            raise ValueError(f"secret value for {key!r} must be a string")
        validated[key] = value
    return validated
