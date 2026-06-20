"""Tests for runtime_common.resolve_context and pool_resolve."""

from __future__ import annotations

import pytest

from runtime_common.pool_resolve import ResolveHeaderMismatchError, resolve_for_invoke
from runtime_common.resolve_context import decode_resolve_header, encode_resolve_header
from runtime_common.schemas import ResolveResponse, SourceMeta, UserMeta


def _source(**overrides) -> SourceMeta:
    defaults = dict(
        kind="agent",
        name="bot",
        version="v1",
        runtime_pool="agent:compiled_graph",
        entrypoint="app:factory",
        bundle_uri="file:///tmp/b.zip",
        checksum="sha256:abc",
    )
    defaults.update(overrides)
    return SourceMeta(**defaults)


def test_encode_decode_resolve_roundtrip():
    resolved = ResolveResponse(
        source=_source(),
        user=UserMeta(principal_id="42", config={"k": "v"}),
    )
    encoded = encode_resolve_header(resolved)
    decoded = decode_resolve_header(encoded)
    assert decoded is not None
    assert decoded.source.name == "bot"
    assert decoded.user is not None
    assert decoded.user.principal_id == "42"


@pytest.mark.asyncio
async def test_resolve_for_invoke_uses_header():
    class _Deploy:
        async def resolve(self, **kwargs):
            raise AssertionError("deploy-api should not be called")

    resolved = ResolveResponse(source=_source(), user=None)
    header = encode_resolve_header(resolved)
    out = await resolve_for_invoke(
        _Deploy(),  # type: ignore[arg-type]
        kind="agent",
        name="bot",
        version=None,
        principal="42",
        x_resolve=header,
    )
    assert out.source.checksum == "sha256:abc"


@pytest.mark.asyncio
async def test_resolve_for_invoke_header_mismatch():
    class _Deploy:
        async def resolve(self, **kwargs):
            raise AssertionError("should not be called")

    resolved = ResolveResponse(source=_source(name="other"), user=None)
    header = encode_resolve_header(resolved)
    with pytest.raises(ResolveHeaderMismatchError):
        await resolve_for_invoke(
            _Deploy(),  # type: ignore[arg-type]
            kind="agent",
            name="bot",
            version=None,
            principal="42",
            x_resolve=header,
        )


@pytest.mark.asyncio
async def test_resolve_for_invoke_falls_back_to_deploy():
    class _Deploy:
        def __init__(self) -> None:
            self.called = False

        async def resolve(self, **kwargs):
            self.called = True
            return ResolveResponse(source=_source(), user=None)

    deploy = _Deploy()
    out = await resolve_for_invoke(
        deploy,  # type: ignore[arg-type]
        kind="agent",
        name="bot",
        version=None,
        principal="42",
        x_resolve=None,
    )
    assert deploy.called is True
    assert out.source.name == "bot"
