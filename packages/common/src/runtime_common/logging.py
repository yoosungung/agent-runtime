import logging
import sys
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

import structlog

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def bind_request_id(request_id: str | None = None) -> str:
    rid = request_id or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=rid)
    _request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id_var.get()


def configure_logging(service_name: str, level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service_name)


def make_request_id_middleware() -> Callable[..., Any]:
    """Return a Starlette-compatible middleware that binds a request_id per request."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    class RequestIdMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
            structlog.contextvars.clear_contextvars()
            rid = bind_request_id(request.headers.get("x-request-id"))
            response: Response = await call_next(request)
            response.headers["x-request-id"] = rid
            return response

    return RequestIdMiddleware
