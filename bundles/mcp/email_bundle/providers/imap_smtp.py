"""IMAP read + SMTP send email provider."""

from __future__ import annotations

import asyncio
import imaplib
from email import policy
from email.parser import BytesParser
from typing import Any

from models import (
    AttachmentMeta,
    EmailSettings,
    ListMessagesResult,
    MessageDetail,
    MessageSummary,
    SendResult,
)
from utils import (
    extract_attachment_meta,
    extract_bodies,
    format_message_date,
    parse_addresses,
    resolve_credential,
    send_via_smtp,
    truncate_text,
)

from runtime_common.secrets import SecretResolver


class ImapSmtpProvider:
    def __init__(self, cfg: dict, secrets: SecretResolver) -> None:
        self._settings = EmailSettings.from_cfg(cfg)
        self._imap_cfg = dict(cfg.get("imap") or {})
        self._smtp_cfg = dict(cfg.get("smtp") or {})
        self._secrets = secrets

    def _imap_password(self) -> str:
        password = resolve_credential(self._imap_cfg, self._secrets)
        if not password:
            raise RuntimeError(
                "imap credentials missing: set source_meta.config.imap.password "
                "or imap.password_ref"
            )
        return password

    def _from_address(self) -> str:
        if self._settings.from_address:
            return self._settings.from_address
        username = self._smtp_cfg.get("username") or self._imap_cfg.get("username")
        if not username:
            raise RuntimeError("email.from_address or imap/smtp.username is required")
        return str(username)

    async def list_messages(
        self,
        *,
        folder: str | None,
        limit: int,
        cursor: str | None,
        query: str | None,
    ) -> ListMessagesResult:
        return await asyncio.to_thread(
            self._list_messages_sync,
            folder or self._settings.default_folder,
            limit,
            cursor,
            query,
        )

    async def read_message(
        self,
        *,
        message_id: str,
        include_body: bool,
        prefer: str,
    ) -> MessageDetail:
        return await asyncio.to_thread(
            self._read_message_sync,
            message_id,
            include_body,
            prefer,
        )

    async def send_message(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None,
        bcc: list[str] | None,
        reply_to_message_id: str | None,
    ) -> SendResult:
        del reply_to_message_id  # IMAP/SMTP has no native threading in v1
        return await asyncio.to_thread(
            self._send_message_sync,
            to,
            subject,
            body,
            cc or [],
            bcc or [],
        )

    def _connect_imap(self) -> imaplib.IMAP4:
        host = self._imap_cfg.get("host")
        username = self._imap_cfg.get("username")
        if not host or not username:
            raise RuntimeError("imap.host and imap.username are required")
        port = int(self._imap_cfg.get("port", 993))
        use_ssl = bool(self._imap_cfg.get("use_ssl", True))
        if use_ssl:
            client = imaplib.IMAP4_SSL(str(host), port)
        else:
            client = imaplib.IMAP4(str(host), port)
        client.login(str(username), self._imap_password())
        return client

    def _list_messages_sync(
        self,
        folder: str,
        limit: int,
        cursor: str | None,
        query: str | None,
    ) -> ListMessagesResult:
        client = self._connect_imap()
        try:
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"failed to select folder: {folder!r}")

            criteria = self._build_search_criteria(query, cursor)
            status, data = client.uid("search", None, criteria)
            if status != "OK" or not data or not data[0]:
                return ListMessagesResult(messages=[], next_cursor=None)

            uids = data[0].split()
            if cursor:
                uids = [uid for uid in uids if uid.decode() < cursor]
            selected = list(reversed(uids[-limit:]))
            messages: list[MessageSummary] = []
            for uid in selected:
                status, fetched = client.uid(
                    "fetch",
                    uid,
                    "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)] FLAGS)",
                )
                if status != "OK" or not fetched or not fetched[0]:
                    continue
                raw = self._extract_fetch_payload(fetched[0])
                msg = BytesParser(policy=policy.default).parsebytes(raw)
                flags = self._extract_flags(fetched[0])
                messages.append(
                    MessageSummary(
                        id=uid.decode(),
                        thread_id=uid.decode(),
                        from_address=parse_addresses(msg.get("From"))[0]
                        if parse_addresses(msg.get("From"))
                        else "",
                        to=parse_addresses(msg.get("To")),
                        subject=str(msg.get("Subject") or ""),
                        date=format_message_date(msg),
                        snippet=truncate_text(str(msg.get("Subject") or ""), 200),
                        is_read=b"\\Seen" in flags,
                        has_attachments=False,
                    )
                )
            next_cursor = selected[0].decode() if len(uids) > len(selected) and selected else None
            return ListMessagesResult(messages=messages, next_cursor=next_cursor)
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _read_message_sync(
        self,
        message_id: str,
        include_body: bool,
        prefer: str,
    ) -> MessageDetail:
        client = self._connect_imap()
        try:
            folder = self._settings.default_folder
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"failed to select folder: {folder!r}")

            status, fetched = client.uid("fetch", message_id, "(RFC822 FLAGS)")
            if status != "OK" or not fetched or not fetched[0]:
                raise RuntimeError(f"message not found: {message_id!r}")

            raw = self._extract_fetch_payload(fetched[0])
            msg = BytesParser(policy=policy.default).parsebytes(raw)
            flags = self._extract_flags(fetched[0])
            body_text = body_html = None
            if include_body:
                body_text, body_html = extract_bodies(
                    msg,
                    prefer=prefer,
                    max_bytes=self._settings.body_max_bytes,
                )
            attachments = [AttachmentMeta(**meta) for meta in extract_attachment_meta(msg)]
            return MessageDetail(
                id=message_id,
                thread_id=message_id,
                from_address=parse_addresses(msg.get("From"))[0]
                if parse_addresses(msg.get("From"))
                else "",
                to=parse_addresses(msg.get("To")),
                subject=str(msg.get("Subject") or ""),
                date=format_message_date(msg),
                snippet=truncate_text(str(msg.get("Subject") or ""), 200),
                is_read=b"\\Seen" in flags,
                has_attachments=bool(attachments),
                body_text=body_text,
                body_html=body_html,
                attachments=attachments,
            )
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _send_message_sync(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str],
        bcc: list[str],
    ) -> SendResult:
        send_via_smtp(
            smtp_cfg=self._smtp_cfg,
            imap_cfg=self._imap_cfg,
            secrets=self._secrets,
            from_address=self._from_address(),
            to=to,
            subject=subject,
            body=body,
            cc=cc or None,
            bcc=bcc or None,
        )
        return SendResult(id=subject, status="sent")

    @staticmethod
    def _build_search_criteria(query: str | None, cursor: str | None) -> str:
        parts = ["ALL"]
        if query:
            safe = query.replace('"', "")
            parts.append(f'(OR SUBJECT "{safe}" FROM "{safe}")')
        if cursor:
            parts.append(f"UID {cursor}:*")
        return " ".join(parts)

    @staticmethod
    def _extract_fetch_payload(item: Any) -> bytes:
        if isinstance(item, tuple):
            byte_parts = [part for part in item if isinstance(part, bytes) and part]
            if len(byte_parts) >= 2:
                return byte_parts[-1]
            if byte_parts:
                return byte_parts[-1]
        raise RuntimeError("unexpected IMAP fetch response")

    @staticmethod
    def _extract_flags(item: Any) -> bytes:
        if isinstance(item, tuple) and item and isinstance(item[0], bytes):
            return item[0]
        return b""
