"""Pool-side resolve: prefer ext-authz snapshot header, fall back to deploy-api."""

from __future__ import annotations

from runtime_common.deploy_client import DeployApiClient
from runtime_common.resolve_context import decode_resolve_header
from runtime_common.schemas import ResolveResponse


class ResolveHeaderMismatchError(ValueError):
    """``x-resolve`` payload does not match the invoke identifiers."""


async def resolve_for_invoke(
    deploy: DeployApiClient,
    *,
    kind: str,
    name: str,
    version: str | None,
    principal: str,
    x_resolve: str | None,
) -> ResolveResponse:
    """Return meta for an invoke, using ``x-resolve`` when ext-authz provided it."""
    resolved = decode_resolve_header(x_resolve)
    if resolved is not None:
        source = resolved.source
        if source.kind != kind or source.name != name:
            raise ResolveHeaderMismatchError(
                f"resolve header kind/name mismatch: {source.kind}:{source.name} != {kind}:{name}"
            )
        if version is not None and source.version != version:
            raise ResolveHeaderMismatchError(
                f"resolve header version mismatch: {source.version} != {version}"
            )
        if source.status == "pending":
            raise ResolveHeaderMismatchError("resolve header points at pending source_meta")
        return resolved

    return await deploy.resolve(kind=kind, name=name, version=version, principal=principal)
