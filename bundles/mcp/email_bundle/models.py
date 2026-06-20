"""Shared email data models for email_bundle providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class AttachmentMeta:
    name: str
    size: int
    content_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MessageSummary:
    id: str
    thread_id: str
    from_address: str
    to: list[str]
    subject: str
    date: str
    snippet: str
    is_read: bool
    has_attachments: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "from": self.from_address,
            "to": self.to,
            "subject": self.subject,
            "date": self.date,
            "snippet": self.snippet,
            "is_read": self.is_read,
            "has_attachments": self.has_attachments,
        }


@dataclass
class MessageDetail(MessageSummary):
    body_text: str | None = None
    body_html: str | None = None
    attachments: list[AttachmentMeta] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        if self.body_text is not None:
            data["body_text"] = self.body_text
        if self.body_html is not None:
            data["body_html"] = self.body_html
        data["attachments"] = [a.to_dict() for a in self.attachments]
        return data


@dataclass
class ListMessagesResult:
    messages: list[MessageSummary]
    next_cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": [m.to_dict() for m in self.messages],
            "next_cursor": self.next_cursor,
        }


@dataclass
class SendResult:
    id: str
    status: Literal["sent"] = "sent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EmailSettings:
    provider: str
    default_folder: str = "INBOX"
    page_size: int = 25
    body_max_bytes: int = 32768
    from_address: str | None = None

    @classmethod
    def from_cfg(cls, cfg: dict) -> EmailSettings:
        section = cfg.get("email") or {}
        return cls(
            provider=str(section.get("provider", "")),
            default_folder=str(section.get("default_folder", "INBOX")),
            page_size=int(section.get("page_size", 25)),
            body_max_bytes=int(section.get("body_max_bytes", 32768)),
            from_address=section.get("from_address"),
        )
