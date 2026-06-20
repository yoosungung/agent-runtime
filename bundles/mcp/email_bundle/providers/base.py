"""Email provider protocol."""

from __future__ import annotations

from typing import Protocol

from models import ListMessagesResult, MessageDetail, SendResult


class EmailProvider(Protocol):
    async def list_messages(
        self,
        *,
        folder: str | None,
        limit: int,
        cursor: str | None,
        query: str | None,
    ) -> ListMessagesResult: ...

    async def read_message(
        self,
        *,
        message_id: str,
        include_body: bool,
        prefer: str,
    ) -> MessageDetail: ...

    async def send_message(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None,
        bcc: list[str] | None,
        reply_to_message_id: str | None,
    ) -> SendResult: ...
