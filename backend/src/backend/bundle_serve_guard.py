"""Block /bundles/* downloads that arrive through a reverse proxy (public Ingress)."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


def bundle_serve_blocked_by_proxy(scope: Scope) -> bool:
    if scope.get("type") != "http":
        return False
    path = scope.get("path", "")
    if not path.startswith("/bundles/"):
        return False
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    return bool(headers.get("x-forwarded-for") or headers.get("x-forwarded-host"))


class BlockPublicBundleMiddleware:
    """Reject bundle downloads that include proxy headers (Ingress/nginx)."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if bundle_serve_blocked_by_proxy(scope):
            body = b'{"detail":"Forbidden"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self._app(scope, receive, send)
