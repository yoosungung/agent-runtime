from __future__ import annotations

from contextvars import ContextVar

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

PIPELINE_AUDIT_DOMAIN = "pipeline"
PIPELINE_ROUTE_PREFIX = "/api/pipeline"

_request_ctx: ContextVar[Request | None] = ContextVar("pipeline_audit_request", default=None)


def get_request_context() -> Request | None:
    return _request_ctx.get()


class PipelineAuditContextMiddleware:
    """Stash Request for handlers that do not declare Request — BFF-only, pipeline paths."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        if method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/pipeline"):
            request = Request(scope, receive)
            token = _request_ctx.set(request)
            try:
                await self.app(scope, receive, send)
            finally:
                _request_ctx.reset(token)
            return

        await self.app(scope, receive, send)
