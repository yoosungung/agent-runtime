"""infra_meta env flattening and validation helpers."""

from __future__ import annotations

from runtime_common.config_schema import InfraConfig

# Whitelisted secret env var names (values live in K8s Secret only).
INFRA_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "OPIK_API_KEY",
    }
)

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

_INFRA_CONFIG_TO_ENV: tuple[tuple[str, str], ...] = (
    ("opik_url", "OPIK_URL"),
    ("opik_workspace", "OPIK_WORKSPACE"),
    ("default_llm_model", "DEFAULT_LLM_MODEL"),
    ("otlp_endpoint", "OTLP_ENDPOINT"),
)


def validate_infra_env_raw(env: dict) -> dict:
    """Validate structured infra env dict and return normalized InfraConfig dump."""
    return InfraConfig.model_validate(env).model_dump(
        exclude_none=True,
        exclude_defaults=True,
    )


def validate_infra_secret_keys(keys: list[str]) -> list[str]:
    """Ensure secret key names are whitelisted and not reserved."""
    normalized: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        if key in RESERVED_INFRA_ENV_KEYS:
            raise ValueError(f"env key {key!r} is reserved by the platform")
        if key not in INFRA_SECRET_KEYS:
            raise ValueError(f"secret key {key!r} is not allowed")
        seen.add(key)
        normalized.append(key)
    return normalized


def validate_infra_secrets_input(secrets: dict[str, str]) -> dict[str, str]:
    """Validate PUT body secrets dict (key → plaintext value for K8s only)."""
    if not secrets:
        return {}
    for key in secrets:
        if key in RESERVED_INFRA_ENV_KEYS:
            raise ValueError(f"env key {key!r} is reserved by the platform")
        if key not in INFRA_SECRET_KEYS:
            raise ValueError(f"secret key {key!r} is not allowed")
    return dict(secrets)


def infra_config_to_env(env: dict) -> dict[str, str]:
    """Flatten validated InfraConfig dict to container env vars."""
    cfg = InfraConfig.model_validate(env)
    flat: dict[str, str] = {}
    data = cfg.model_dump(exclude_none=True, exclude_defaults=True)
    for src_key, env_key in _INFRA_CONFIG_TO_ENV:
        value = data.get(src_key)
        if value is not None:
            flat[env_key] = str(value)
    return flat
