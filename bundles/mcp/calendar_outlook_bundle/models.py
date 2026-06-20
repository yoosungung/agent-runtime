"""Shared calendar data models for calendar_outlook_bundle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class CalendarSummary:
    id: str
    name: str
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Attendee:
    email: str
    name: str | None = None
    response_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"email": self.email}
        if self.name is not None:
            data["name"] = self.name
        if self.response_status is not None:
            data["response_status"] = self.response_status
        return data


@dataclass
class EventTime:
    datetime: str
    timezone: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"datetime": self.datetime}
        if self.timezone is not None:
            data["timezone"] = self.timezone
        return data


@dataclass
class EventSummary:
    id: str
    subject: str
    start: EventTime
    end: EventTime
    organizer: str
    attendees: list[Attendee] = field(default_factory=list)
    location: str | None = None
    is_online: bool = False
    web_link: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "organizer": self.organizer,
            "attendees": [a.to_dict() for a in self.attendees],
            "location": self.location,
            "is_online": self.is_online,
            "web_link": self.web_link,
        }


@dataclass
class EventDetail(EventSummary):
    body: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        if self.body is not None:
            data["body"] = self.body
        return data


@dataclass
class ListCalendarsResult:
    calendars: list[CalendarSummary]

    def to_dict(self) -> dict[str, Any]:
        return {"calendars": [c.to_dict() for c in self.calendars]}


@dataclass
class ListEventsResult:
    events: list[EventSummary]
    next_cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "next_cursor": self.next_cursor,
        }


@dataclass
class AvailabilitySlot:
    start: str
    end: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AttendeeAvailability:
    email: str
    slots: list[AvailabilitySlot]

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "slots": [s.to_dict() for s in self.slots],
        }


@dataclass
class FreeBusyResult:
    attendees: list[AttendeeAvailability]

    def to_dict(self) -> dict[str, Any]:
        return {"attendees": [a.to_dict() for a in self.attendees]}


@dataclass
class MutateEventResult:
    id: str
    status: Literal["created", "updated", "cancelled"]
    web_link: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "status": self.status}
        if self.web_link is not None:
            data["web_link"] = self.web_link
        return data


@dataclass
class CalendarSettings:
    page_size: int = 25
    body_max_bytes: int = 32768
    timezone: str = "Asia/Seoul"
    default_calendar_id: str | None = None

    @classmethod
    def from_cfg(cls, cfg: dict) -> CalendarSettings:
        section = cfg.get("calendar") or {}
        return cls(
            page_size=int(section.get("page_size", 25)),
            body_max_bytes=int(section.get("body_max_bytes", 32768)),
            timezone=str(section.get("timezone", "Asia/Seoul")),
            default_calendar_id=section.get("default_calendar_id"),
        )
