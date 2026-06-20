"""Microsoft Graph Calendar client for calendar_outlook_bundle."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import msal
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
    graph_event_to_summary,
    normalize_attendees,
    resolve_credential,
    truncate_text,
)

from runtime_common.secrets import SecretResolver

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_CLIENT_SCOPES = ["https://graph.microsoft.com/.default"]
_DELEGATED_SCOPES = ["Calendars.ReadWrite", "User.Read", "offline_access"]


class OutlookGraphCalendarClient:
    def __init__(self, cfg: dict, secrets: SecretResolver) -> None:
        self._settings = CalendarSettings.from_cfg(cfg)
        self._outlook_cfg = dict(cfg.get("outlook") or {})
        self._secrets = secrets

    def _require_outlook_fields(self) -> tuple[str, str, str, str | None]:
        tenant_id = self._outlook_cfg.get("tenant_id")
        client_id = self._outlook_cfg.get("client_id")
        client_secret = resolve_credential(
            self._outlook_cfg,
            self._secrets,
            value_key="client_secret",
            ref_key="client_secret_ref",
        )
        mailbox = self._outlook_cfg.get("mailbox")
        auth_mode = str(self._outlook_cfg.get("auth", "client_credentials"))
        if auth_mode == "oauth_refresh":
            if not all([tenant_id, client_id, client_secret]):
                raise RuntimeError(
                    "outlook credentials missing: set source_meta.config.outlook "
                    "{tenant_id, client_id, client_secret} and "
                    "user_meta.config.outlook.refresh_token"
                )
        elif not all([tenant_id, client_id, client_secret, mailbox]):
            raise RuntimeError(
                "outlook credentials missing: set source_meta.config.outlook "
                "{tenant_id, client_id, client_secret, mailbox}"
            )
        return str(tenant_id), str(client_id), str(client_secret), (
            str(mailbox) if mailbox else None
        )

    def _acquire_token(self) -> str:
        tenant_id, client_id, client_secret, _ = self._require_outlook_fields()
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret,
        )
        auth_mode = str(self._outlook_cfg.get("auth", "client_credentials"))
        if auth_mode == "oauth_refresh":
            refresh_token = self._outlook_cfg.get("refresh_token")
            if not refresh_token:
                raise RuntimeError(
                    "outlook refresh token missing: set user_meta.config.outlook.refresh_token"
                )
            result = app.acquire_token_by_refresh_token(
                refresh_token,
                scopes=_DELEGATED_SCOPES,
            )
        else:
            result = app.acquire_token_for_client(scopes=_CLIENT_SCOPES)
        if not result or "access_token" not in result:
            raise RuntimeError("failed to acquire Microsoft Graph access token")
        return str(result["access_token"])

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        token = await asyncio.to_thread(self._acquire_token)
        url = f"{_GRAPH_BASE}{path}" if path.startswith("/") else path
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
                retry_after = int(response.headers.get("Retry-After", "1"))
                await asyncio.sleep(retry_after)
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

    def _user_path(self) -> str:
        _, _, _, mailbox = self._require_outlook_fields()
        auth_mode = str(self._outlook_cfg.get("auth", "client_credentials"))
        if auth_mode == "oauth_refresh":
            return "/me"
        return f"/users/{mailbox}"

    def _calendar_segment(self, calendar_id: str | None) -> str:
        selected = calendar_id or self._settings.default_calendar_id
        if selected:
            return f"/calendars/{selected}"
        return "/calendar"

    async def list_calendars(self) -> ListCalendarsResult:
        data = await self._request(
            "GET",
            f"{self._user_path()}/calendars",
            params={"$select": "id,name,isDefaultCalendar"},
        )
        calendars = [
            CalendarSummary(
                id=item["id"],
                name=item.get("name") or "",
                is_default=bool(item.get("isDefaultCalendar")),
            )
            for item in data.get("value") or []
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
        if cursor:
            data = await self._request("GET", cursor)
        else:
            params: dict[str, Any] = {
                "startDateTime": time_min,
                "endDateTime": time_max,
                "$top": limit,
                "$orderby": "start/dateTime",
                "$select": (
                    "id,subject,start,end,organizer,attendees,location,"
                    "isOnlineMeeting,onlineMeeting,webLink"
                ),
            }
            path = f"{self._user_path()}{self._calendar_segment(calendar_id)}/calendarView"
            data = await self._request("GET", path, params=params)
        events: list[EventSummary] = []
        for item in data.get("value") or []:
            raw = graph_event_to_summary(item)
            events.append(
                EventSummary(
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
            )
        next_cursor = data.get("@odata.nextLink")
        if next_cursor and next_cursor.startswith(_GRAPH_BASE):
            next_cursor = next_cursor[len(_GRAPH_BASE) :]
        return ListEventsResult(events=events, next_cursor=next_cursor)

    async def get_event(
        self,
        *,
        event_id: str,
        calendar_id: str | None,
    ) -> EventDetail:
        if calendar_id:
            path = f"{self._user_path()}/calendars/{calendar_id}/events/{event_id}"
        else:
            path = f"{self._user_path()}/events/{event_id}"
        data = await self._request(
            "GET",
            path,
            params={
                "$select": (
                    "id,subject,start,end,organizer,attendees,location,"
                    "isOnlineMeeting,onlineMeeting,webLink,body"
                )
            },
        )
        raw = graph_event_to_summary(data)
        body = (data.get("body") or {}).get("content")
        if body:
            body = truncate_text(str(body), self._settings.body_max_bytes)
        return EventDetail(
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
            is_online=raw.get("is_online", False),
            web_link=raw.get("web_link"),
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
        payload: dict[str, Any] = {
            "schedules": emails,
            "startTime": {"dateTime": time_min, "timeZone": self._settings.timezone},
            "endTime": {"dateTime": time_max, "timeZone": self._settings.timezone},
            "availabilityViewInterval": duration_minutes or 30,
        }
        data = await self._request(
            "POST",
            f"{self._user_path()}/calendar/getSchedule",
            json_body=payload,
        )
        result: list[AttendeeAvailability] = []
        for item in data.get("value") or []:
            email = (item.get("scheduleId") or "").lower()
            slots = [
                AvailabilitySlot(
                    start=si.get("start", {}).get("dateTime", ""),
                    end=si.get("end", {}).get("dateTime", ""),
                    status=si.get("status") or "unknown",
                )
                for si in item.get("scheduleItems") or []
            ]
            result.append(AttendeeAvailability(email=email, slots=slots))
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
            "subject": subject,
            "start": {"dateTime": start, "timeZone": tz},
            "end": {"dateTime": end, "timeZone": tz},
        }
        if body:
            payload["body"] = {
                "contentType": "Text",
                "content": truncate_text(body, self._settings.body_max_bytes),
            }
        if location:
            payload["location"] = {"displayName": location}
        if attendees:
            payload["attendees"] = [
                {
                    "emailAddress": {"address": email},
                    "type": "required",
                }
                for email in normalize_attendees(attendees)
            ]
        if is_online_meeting:
            payload["isOnlineMeeting"] = True
            payload["onlineMeetingProvider"] = "teamsForBusiness"
        if calendar_id:
            path = f"{self._user_path()}/calendars/{calendar_id}/events"
        else:
            path = f"{self._user_path()}/events"
        data = await self._request("POST", path, json_body=payload)
        return MutateEventResult(
            id=data.get("id") or "",
            status="created",
            web_link=data.get("webLink"),
        )

    async def update_event(
        self,
        *,
        event_id: str,
        patch: dict[str, Any],
    ) -> MutateEventResult:
        if not patch:
            raise ValueError("patch is required")
        graph_patch = self._build_graph_patch(patch)
        path = f"{self._user_path()}/events/{event_id}"
        data = await self._request("PATCH", path, json_body=graph_patch)
        return MutateEventResult(
            id=data.get("id") or event_id,
            status="updated",
            web_link=data.get("webLink"),
        )

    async def cancel_event(
        self,
        *,
        event_id: str,
        calendar_id: str | None,
        send_cancellation: bool,
    ) -> MutateEventResult:
        if calendar_id:
            path = f"{self._user_path()}/calendars/{calendar_id}/events/{event_id}"
        else:
            path = f"{self._user_path()}/events/{event_id}"
        params = {"sendCancellation": str(send_cancellation).lower()}
        await self._request("DELETE", path, params=params)
        return MutateEventResult(id=event_id, status="cancelled")

    def _build_graph_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        tz = self._settings.timezone
        graph: dict[str, Any] = {}
        if "subject" in patch:
            graph["subject"] = patch["subject"]
        if "start" in patch:
            graph["start"] = {"dateTime": patch["start"], "timeZone": tz}
        if "end" in patch:
            graph["end"] = {"dateTime": patch["end"], "timeZone": tz}
        if "body" in patch:
            graph["body"] = {
                "contentType": "Text",
                "content": truncate_text(str(patch["body"]), self._settings.body_max_bytes),
            }
        if "location" in patch:
            graph["location"] = {"displayName": patch["location"]}
        if "attendees" in patch:
            graph["attendees"] = [
                {"emailAddress": {"address": email}, "type": "required"}
                for email in normalize_attendees(patch["attendees"])
            ]
        if patch.get("is_online_meeting"):
            graph["isOnlineMeeting"] = True
            graph["onlineMeetingProvider"] = "teamsForBusiness"
        return graph
