from __future__ import annotations

from typing import Any

from starlette.requests import Request

from backend.audit import log_event, make_audit_row
from backend.pipeline_audit.context import PIPELINE_AUDIT_DOMAIN
from runtime_common.db import session_scope
from runtime_common.schemas import Principal


async def emit_pipeline_audit(
    request: Request,
    principal: Principal,
    action: str,
    details: dict[str, Any],
) -> None:
    payload = {"domain": PIPELINE_AUDIT_DOMAIN, **details}
    factory = request.app.state.session_factory
    async with session_scope(factory) as db:
        db.add(
            make_audit_row(
                action,
                principal.user_id,
                principal.sub,
                **payload,
            )
        )
    log_event(
        action,
        actor_id=principal.user_id,
        actor=principal.sub,
        **payload,
    )
