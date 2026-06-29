"""Helpers for building and caching factory instances in pool runtimes."""

from __future__ import annotations

from runtime_common.factory import call_factory, merge_configs
from runtime_common.instance_cache import InstanceCache, make_instance_key
from runtime_common.loader import BundleLoader
from runtime_common.schemas import SourceMeta, UserMeta
from runtime_common.secrets import EnvSecretResolver, SecretResolver


def build_secrets_resolver(user: UserMeta | None) -> SecretResolver:
    """Return a SecretResolver for factory invocation.

    Bundle factories resolve credential refs (e.g. ``client_secret_ref``) via
    ``SecretResolver.resolve(env_var_name)``. ``user_meta.secrets_ref`` is an
    opaque URI for custom-image / ext-authz passthrough; pool bundle mode uses
    ``EnvSecretResolver`` and per-field refs inside merged config.
    """
    _ = user
    return EnvSecretResolver()


def source_instance_key(source: SourceMeta) -> str | None:
    """Cache checksum for a source row; general agents have no bundle checksum."""
    if source.checksum:
        return source.checksum
    if source.deploy_mode == "general":
        return f"general:{source.name}:{source.version}"
    if source.deploy_mode == "hermes_general":
        return f"hermes:{source.name}:{source.version}"
    return source.checksum


async def get_or_build_cached_instance(
    cache: InstanceCache,
    source: SourceMeta,
    user: UserMeta | None,
    loader: BundleLoader,
    secrets: SecretResolver,
    *,
    source_only: bool = False,
) -> object:
    """Build or reuse a cached factory instance.

    When ``source_only`` is True (tool schema discovery), only ``source.config``
    is passed and the cache key omits principal — all users share one entry.
    """
    if source_only:
        cfg = source.config
        key = make_instance_key(source_instance_key(source), None, None)
    else:
        cfg = merge_configs(source.config, user.config if user else None)
        key = make_instance_key(
            source_instance_key(source),
            user.principal_id if user else None,
            user.updated_at if user else None,
        )

    async def builder() -> object:
        factory = await loader.aload(source)
        return call_factory(factory, cfg, secrets)

    return await cache.get_or_build(key, builder)
