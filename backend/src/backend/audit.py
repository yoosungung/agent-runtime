from __future__ import annotations

import logging
from typing import Any

from runtime_common.db.models import AuditLogRow

audit_logger = logging.getLogger("audit")

# LogRecord reserved attributes — passing any of these via `extra=` raises
# KeyError("Attempt to overwrite ... in LogRecord"). Domain fields like `name`
# collide naturally, so we prefix collisions instead of asking every caller
# to remember the list.
_LOGRECORD_RESERVED = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    }
)


def _safe_extra(fields: dict[str, Any]) -> dict[str, Any]:
    return {(f"event_{k}" if k in _LOGRECORD_RESERVED else k): v for k, v in fields.items()}


def log_event(action: str, actor_id: int, actor: str, **kwargs: Any) -> None:
    audit_logger.info(
        action,
        extra=_safe_extra({"actor_id": actor_id, "actor": actor, **kwargs}),
    )


def make_audit_row(action: str, actor_id: int, actor: str, **kwargs: Any) -> AuditLogRow:
    return AuditLogRow(action=action, actor_id=actor_id, actor=actor, details=kwargs)
