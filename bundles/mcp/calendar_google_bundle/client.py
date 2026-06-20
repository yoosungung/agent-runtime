"""Google Calendar API client for calendar_google_bundle."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import credentials as oauth_credentials
from google.oauth2 import service_account
from models import (
    Attendee,
    AttendeeAvailability,
    AvailabilitySlot,
    CalendarSettings,
    CalendarSummary,
    EventDetail,
    EventSummary,
    EventTime,
    FreeBusyResult,
    ListCalendarsResult,
    ListEventsResult,
    MutateEventResult,
)
from utils import (
    clamp_limit,
    google_event_to_summary,
    normalize_attendees,
    resolve_credential,
    truncate_text,
)

from runtime_common.secrets import SecretResolver

_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleCalendarClient:
    def __init__(self, cfg: dict, secrets: SecretResolver) -> None:
        self._settings = CalendarSettings.from_cfg(cfg)
        self._google_cfg = dict(cfg.get("google") or {})
        self._secrets = secrets

    def _require_client_credentials(self) -> tuple[str, str]:
        client_id = self._google_cfg.get("client_id")
        client_secret = resolve_credential(
            self._google_cfg,
            self._secrets,
            value_key="client_secret",
            ref_key="client_secret_ref",
        )
        if not client_id or not client_secret:
            raise RuntimeError(
                "google credentials missing: set source_meta.config.google."
                "{client_id, client_secret}"
            )
        return str(client_id), str(client_secret)

    def _acquire_token(self) -> str:
        auth_mode = str(self._google_cfg.get("auth", "oauth_refresh"))
        if auth_mode == "oauth_refresh":
            client_id, client_secret = self._require_client_credentials()
            refresh_token = self._google_cfg.get("refresh_token")
            if not refresh_token:
                raise RuntimeError(
                    "google refresh token missing: set user_meta.config.google.refresh_token"
                )
            creds = oauth_credentials.Credentials(
                token=None,
                refresh_token=str(refresh_token),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=_SCOPES,
            )
            creds.refresh(Request())
            return str(creds.token)

        service_account_info = self._google_cfg.get("service_account")
        subject_email = self._google_cfg.get("subject_email")
        if not service_account_info or not subject_email:
            raise RuntimeError(
                "google service account missing: set google.service_account and "
                "google.subject_email"
            )
        if isinstance(service_account_info, str):
            service_account_info = json.loads(service_account_info)
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=_SCOPES,
            subject=str(subject_email),
        )
        creds.refresh(Request())
        return str(creds.token)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        token = await asyncio.to_thread(self._acquire_token)
        url = path if path.startswith("http") else f"{_CALENDAR_BASE}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
            )
            if response.status_code == 429:
                await asyncio.sleep(1)
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )
            response.raise_for_status()
            if response.status_code in (202, 204) or not response.content:
                return {}
            return response.json()

    def _calendar_id(self, calendar_id: str | None) -> str:
        return calendar_id or self._settings.default_calendar_id or "primary"

    def _event_from_raw(self, item: dict[str, Any]) -> EventSummary:
        raw = google_event_to_summary(item)
        return EventSummary(
            id=raw["id"],
            subject=raw["subject"],
            start=EventTime(
                datetime=raw["start"]["datetime"],
                timezone=raw["start"].get("timezone"),
            ),
            end=EventTime(
                datetime=raw["end"]["datetime"],
                timezone=raw["end"].get("timezone"),
            ),
            organizer=raw["organizer"],
            attendees=[
                Attendee(
                    email=a["email"],
                    name=a.get("name"),
                    response_status=a.get("response_status"),
                )
                for a in raw.get("attendees") or []
            ],
            location=raw.get("location"),
            is_online=bool(raw.get("is_online")),
            web_link=raw.get("web_link"),
        )

    async def list_calendars(self) -> ListCalendarsResult:
        data = await self._request("GET", "/users/me/calendarList")
        calendars = [
            CalendarSummary(
                id=item["id"],
                name=item.get("summary") or "",
                is_default=bool(item.get("primary")),
            )
            for item in data.get("items") or []
        ]
        return ListCalendarsResult(calendars=calendars)

    async def list_events(
        self,
        *,
        time_min: str,
        time_max: str,
        calendar_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> ListEventsResult:
        limit = clamp_limit(limit, default=self._settings.page_size)
        cal = quote(self._calendar_id(calendar_id), safe="")
        if cursor:
            data = await self._request("GET", cursor)
        else:
            params: dict[str, Any] = {
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": limit,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            data = await self._request("GET", f"/calendars/{cal}/events", params=params)
        events = [self._event_from_raw(item) for item in data.get("items") or []]
        next_cursor = data.get("nextPageToken")
        if next_cursor:
            next_cursor = (
                f"/calendars/{cal}/events?"
                f"timeMin={quote(time_min)}&timeMax={quote(time_max)}"
                f"&maxResults={limit}&singleEvents=true&orderBy=startTime"
                f"&pageToken={quote(next_cursor)}"
            )
        return ListEventsResult(events=events, next_cursor=next_cursor)

    async def get_event(
        self,
        *,
        event_id: str,
        calendar_id: str | None,
    ) -> EventDetail:
        cal = quote(self._calendar_id(calendar_id), safe="")
        data = await self._request("GET", f"/calendars/{cal}/events/{quote(event_id, safe='')}")
        summary = self._event_from_raw(data)
        body = data.get("description")
        if body:
            body = truncate_text(str(body), self._settings.body_max_bytes)
        return EventDetail(
            id=summary.id,
            subject=summary.subject,
            start=summary.start,
            end=summary.end,
            organizer=summary.organizer,
            attendees=summary.attendees,
            location=summary.location,
            is_online=summary.is_online,
            web_link=summary.web_link,
            body=body,
        )

    async def find_availability(
        self,
        *,
        attendees: list[str],
        time_min: str,
        time_max: str,
        duration_minutes: int | None,
    ) -> FreeBusyResult:
        emails = normalize_attendees(attendees)
        if not emails:
            raise ValueError("attendees is required")
        payload = {
            "timeMin": time_min,
            "timeMax": time_max,
            "timeZone": self._settings.timezone,
            "items": [{"id": email} for email in emails],
        }
        data = await self._request("POST", "/freeBusy", json_body=payload)
        calendars = data.get("calendars") or {}
        result: list[AttendeeAvailability] = []
        for email in emails:
            info = calendars.get(email) or {}
            slots = [
                AvailabilitySlot(
                    start=busy.get("start", ""),
                    end=busy.get("end", ""),
                    status="busy",
                )
                for busy in info.get("busy") or []
            ]
            result.append(AttendeeAvailability(email=email, slots=slots))
        del duration_minutes  # Google freeBusy returns busy blocks only
        return FreeBusyResult(attendees=result)

    async def create_event(
        self,
        *,
        subject: str,
        start: str,
        end: str,
        attendees: list[str] | None,
        body: str | None,
        location: str | None,
        calendar_id: str | None,
        is_online_meeting: bool,
    ) -> MutateEventResult:
        tz = self._settings.timezone
        payload: dict[str, Any] = {
            "summary": subject,
            "start": {"dateTime": start, "timeZone": tz},
            "end": {"dateTime": end, "timeZone": tz},
        }
        if body:
            payload["description"] = truncate_text(body, self._settings.body_max_bytes)
        if location:
            payload["location"] = location
        if attendees:
            payload["attendees"] = [{"email": email} for email in normalize_attendees(attendees)]
        if is_online_meeting or self._settings.create_meet_link:
            payload["conferenceData"] = {
                "createRequest": {
                    "requestId": f"meet-{subject[:20]}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        cal = quote(self._calendar_id(calendar_id), safe="")
        params = {"conferenceDataVersion": 1} if "conferenceData" in payload else None
        data = await self._request(
            "POST",
            f"/calendars/{cal}/events",
            params=params,
            json_body=payload,
        )
        return MutateEventResult(
            id=data.get("id") or "",
            status="created",
            web_link=data.get("htmlLink"),
        )

    async def update_event(
        self,
        *,
        event_id: str,
        patch: dict[str, Any],
    ) -> MutateEventResult:
        if not patch:
            raise ValueError("patch is required")
        cal = quote(self._calendar_id(None), safe="")
        google_patch = self._build_google_patch(patch)
        data = await self._request(
            "PATCH",
            f"/calendars/{cal}/events/{quote(event_id, safe='')}",
            json_body=google_patch,
        )
        return MutateEventResult(
            id=data.get("id") or event_id,
            status="updated",
            web_link=data.get("htmlLink"),
        )

    async def cancel_event(
        self,
        *,
        event_id: str,
        calendar_id: str | None,
        send_cancellation: bool,
    ) -> MutateEventResult:
        del send_cancellation  # Google delete always notifies attendees when applicable
        cal = quote(self._calendar_id(calendar_id), safe="")
        await self._request("DELETE", f"/calendars/{cal}/events/{quote(event_id, safe='')}")
        return MutateEventResult(id=event_id, status="cancelled")

    def _build_google_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        tz = self._settings.timezone
        google: dict[str, Any] = {}
        if "subject" in patch:
            google["summary"] = patch["subject"]
        if "start" in patch:
            google["start"] = {"dateTime": patch["start"], "timeZone": tz}
        if "end" in patch:
            google["end"] = {"dateTime": patch["end"], "timeZone": tz}
        if "body" in patch:
            google["description"] = truncate_text(str(patch["body"]), self._settings.body_max_bytes)
        if "location" in patch:
            google["location"] = patch["location"]
        if "attendees" in patch:
            google["attendees"] = [{"email": email} for email in normalize_attendees(patch["attendees"])]
        if patch.get("is_online_meeting"):
            google["conferenceData"] = {
                "createRequest": {
                    "requestId": "meet-update",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        return google
