"""Shared helpers for calendar_outlook_bundle."""

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


def normalize_attendees(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(v).strip() for v in value if str(v).strip()]


def graph_event_to_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Graph calendar event JSON object to EventSummary fields."""
    organizer = (item.get("organizer") or {}).get("emailAddress") or {}
    attendees = []
    for raw in item.get("attendees") or []:
        addr = (raw.get("emailAddress") or {}).get("address")
        if not addr:
            continue
        attendees.append(
            {
                "email": addr,
                "name": (raw.get("emailAddress") or {}).get("name"),
                "response_status": (raw.get("status") or {}).get("response"),
            }
        )
    start = item.get("start") or {}
    end = item.get("end") or {}
    online = item.get("onlineMeeting") or {}
    return {
        "id": item["id"],
        "subject": item.get("subject") or "",
        "start": {
            "datetime": start.get("dateTime") or "",
            "timezone": start.get("timeZone"),
        },
        "end": {
            "datetime": end.get("dateTime") or "",
            "timezone": end.get("timeZone"),
        },
        "organizer": organizer.get("address") or "",
        "attendees": attendees,
        "location": (item.get("location") or {}).get("displayName"),
        "is_online": bool(online.get("joinUrl") or item.get("isOnlineMeeting")),
        "web_link": item.get("webLink"),
    }
