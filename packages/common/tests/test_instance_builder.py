"""Tests for runtime_common.instance_builder."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from runtime_common.instance_builder import build_secrets_resolver, get_or_build_cached_instance
from runtime_common.instance_cache import InstanceCache
from runtime_common.schemas import SourceMeta, UserMeta
from runtime_common.secrets import EnvSecretResolver


def _source(**overrides) -> SourceMeta:
    defaults = dict(
        kind="mcp",
        name="email-server",
        version="v1",
        runtime_pool="mcp:mcp_sdk",
        entrypoint="app:build_server",
        bundle_uri="file:///tmp/b.zip",
        checksum="sha256:abc",
        config={"email": {"provider": "outlook"}},
    )
    defaults.update(overrides)
    return SourceMeta(**defaults)


class _FakeLoader:
    def __init__(self) -> None:
        self.calls = 0

    def load(self, meta: SourceMeta):
        self.calls += 1

        def factory(cfg, secrets):
            return {"cfg": cfg, "secrets": secrets, "checksum": meta.checksum}

        return factory

    async def aload(self, meta: SourceMeta):
        return self.load(meta)


@pytest.mark.asyncio
async def test_source_only_shares_cache_entry():
    cache = InstanceCache(max_entries=4)
    loader = _FakeLoader()
    source = _source()
    secrets = EnvSecretResolver()

    inst1 = await get_or_build_cached_instance(
        cache, source, None, loader, secrets, source_only=True
    )
    inst2 = await get_or_build_cached_instance(
        cache, source, None, loader, secrets, source_only=True
    )
    assert inst1 is inst2
    assert loader.calls == 1


@pytest.mark.asyncio
async def test_different_principals_get_separate_entries():
    cache = InstanceCache(max_entries=8)
    loader = _FakeLoader()
    source = _source()
    secrets = EnvSecretResolver()
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    user_a = UserMeta(
        principal_id="user-a",
        config={"outlook": {"mailbox": "a@co.com"}},
        updated_at=ts,
    )
    user_b = UserMeta(
        principal_id="user-b",
        config={"outlook": {"mailbox": "b@co.com"}},
        updated_at=ts,
    )

    inst_a = await get_or_build_cached_instance(cache, source, user_a, loader, secrets)
    inst_b = await get_or_build_cached_instance(cache, source, user_b, loader, secrets)
    assert inst_a is not inst_b
    assert inst_a["cfg"]["outlook"]["mailbox"] == "a@co.com"
    assert inst_b["cfg"]["outlook"]["mailbox"] == "b@co.com"
    assert loader.calls == 2


@pytest.mark.asyncio
async def test_no_user_meta_shares_entry_across_principals():
    cache = InstanceCache(max_entries=4)
    loader = _FakeLoader()
    source = _source()
    secrets = EnvSecretResolver()

    inst1 = await get_or_build_cached_instance(cache, source, None, loader, secrets)
    inst2 = await get_or_build_cached_instance(cache, source, None, loader, secrets)
    assert inst1 is inst2
    assert loader.calls == 1


def test_build_secrets_resolver_returns_env_resolver():
    assert isinstance(build_secrets_resolver(None), EnvSecretResolver)
    user = UserMeta(principal_id="u1", secrets_ref="vault://secrets/u1")
    assert isinstance(build_secrets_resolver(user), EnvSecretResolver)
