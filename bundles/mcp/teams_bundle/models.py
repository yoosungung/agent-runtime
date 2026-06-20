"""Shared Teams data models for teams_bundle."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass
class TeamSummary:
    id: str
    name: str
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {"id": self.id, "name": self.name}
        if self.description is not None:
            data["description"] = self.description
        return data


@dataclass
class ChannelSummary:
    id: str
    name: str
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {"id": self.id, "name": self.name}
        if self.description is not None:
            data["description"] = self.description
        return data


@dataclass
class ChatSummary:
    id: str
    topic: str | None
    chat_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "chat_type": self.chat_type,
        }


@dataclass
class MessageSummary:
    id: str
    from_name: str
    from_email: str
    created_at: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ListTeamsResult:
    teams: list[TeamSummary]

    def to_dict(self) -> dict[str, Any]:
        return {"teams": [t.to_dict() for t in self.teams]}


@dataclass
class ListChannelsResult:
    channels: list[ChannelSummary]

    def to_dict(self) -> dict[str, Any]:
        return {"channels": [c.to_dict() for c in self.channels]}


@dataclass
class ListChatsResult:
    chats: list[ChatSummary]
    next_cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chats": [c.to_dict() for c in self.chats],
            "next_cursor": self.next_cursor,
        }


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
class SendMessageResult:
    id: str
    status: Literal["sent"] = "sent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CreateChatResult:
    id: str
    web_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id}
        if self.web_url is not None:
            data["web_url"] = self.web_url
        return data


@dataclass
class TeamsSettings:
    page_size: int = 25
    body_max_bytes: int = 8192
    default_team_id: str | None = None
    default_channel_id: str | None = None

    @classmethod
    def from_cfg(cls, cfg: dict) -> TeamsSettings:
        section = cfg.get("teams") or {}
        return cls(
            page_size=int(section.get("page_size", 25)),
            body_max_bytes=int(section.get("body_max_bytes", 8192)),
            default_team_id=section.get("default_team_id"),
            default_channel_id=section.get("default_channel_id"),
        )
