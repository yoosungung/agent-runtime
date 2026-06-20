"""Shared helpers for teams_bundle."""

from __future__ import annotations

from typing import Any

from runtime_common.secrets import SecretResolver


def resolve_credential(
    block: dict,
    secrets: SecretResolver,
    *,
    value_key: str = "password",
    ref_key: str = "password_ref",
) -> str | None:
    ref = block.get(ref_key)
    if ref:
        return secrets.resolve(str(ref))
    value = block.get(value_key)
    return str(value) if value is not None else None


def truncate_text(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    while truncated and (truncated[-1] & 0xC0) == 0x80:
        truncated = truncated[:-1]
    return truncated.decode("utf-8", errors="ignore") + "…"


def clamp_limit(limit: int, *, default: int, maximum: int = 50) -> int:
    if limit <= 0:
        return default
    return min(limit, maximum)


def extract_message_content(item: dict[str, Any]) -> str:
    body = item.get("body") or {}
    return str(body.get("content") or "")


def graph_message_to_summary(item: dict[str, Any], *, max_bytes: int) -> dict[str, Any]:
    sender = (item.get("from") or {}).get("user") or {}
    email = sender.get("email") or sender.get("userPrincipalName") or ""
    return {
        "id": item["id"],
        "from_name": sender.get("displayName") or "",
        "from_email": email,
        "created_at": item.get("createdDateTime") or "",
        "content": truncate_text(extract_message_content(item), max_bytes),
    }
