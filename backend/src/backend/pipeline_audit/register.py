from __future__ import annotations

from functools import wraps
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.requests import Request

from backend.pipeline_audit.actions import build_audit_details, resolve_audit_action
from backend.pipeline_audit.context import PipelineAuditContextMiddleware, get_request_context
from backend.pipeline_audit.emitter import emit_pipeline_audit
from runtime_common.schemas import Principal


def _find_principal(kwargs: dict[str, Any]) -> Principal | None:
    principal = kwargs.get("principal")
    if isinstance(principal, Principal):
        return principal
    for value in kwargs.values():
        if isinstance(value, Principal):
            return value
    return None


def _find_request(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Request | None:
    request = kwargs.get("request")
    if isinstance(request, Request):
        return request
    for value in args:
        if isinstance(value, Request):
            return value
    return get_request_context()


def _wrap_route(route: APIRoute) -> None:
    action = resolve_audit_action(set(route.methods), route.path)
    if action is None:
        return

    original = route.endpoint
    if getattr(original, "_pipeline_audit_wrapped", False):
        return

    @wraps(original)
    async def audited_endpoint(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        principal = _find_principal(kwargs)
        request = _find_request(args, kwargs)
        if principal is None or request is None:
            return result
        details = build_audit_details(
            action,
            kwargs=kwargs,
            result=result,
            principal=principal,
        )
        await emit_pipeline_audit(request, principal, action, details)
        return result

    audited_endpoint._pipeline_audit_wrapped = True  # type: ignore[attr-defined]

    route.endpoint = audited_endpoint
    route.app = route.get_route_handler()


def install_pipeline_console_audit(app: FastAPI, *routers: APIRouter) -> None:
    """Register pipeline BFF audit hooks. Call only when PIPELINE_CONSOLE_ENABLED."""
    for router in routers:
        for route in router.routes:
            if isinstance(route, APIRoute):
                _wrap_route(route)
    app.add_middleware(PipelineAuditContextMiddleware)  # type: ignore[arg-type]
