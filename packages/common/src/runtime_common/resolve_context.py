"""Resolve snapshot passed from ext-authz to pool pods via upstream headers."""

from __future__ import annotations

import base64
import json

from runtime_common.schemas import ResolveResponse

_RESOLVE_HEADER = "x-resolve"


def encode_resolve_header(resolved: ResolveResponse) -> str:
    """Base64-encode a ResolveResponse for the ``x-resolve`` upstream header."""
    payload = resolved.model_dump_json(by_alias=False)
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def decode_resolve_header(value: str | None) -> ResolveResponse | None:
    """Decode ``x-resolve`` header; return None when absent or invalid."""
    if not value:
        return None
    try:
        raw = base64.b64decode(value)
        return ResolveResponse.model_validate_json(raw)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def resolve_header_name() -> str:
    return _RESOLVE_HEADER
