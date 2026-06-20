"""POP3 read + SMTP send email provider."""

from __future__ import annotations

import asyncio
import poplib
from email import policy
from email.parser import BytesParser

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


class Pop3SmtpProvider:
    def __init__(self, cfg: dict, secrets: SecretResolver) -> None:
        self._settings = EmailSettings.from_cfg(cfg)
        self._pop3_cfg = dict(cfg.get("pop3") or {})
        self._smtp_cfg = dict(cfg.get("smtp") or {})
        self._secrets = secrets
        self._imap_cfg = dict(cfg.get("imap") or {})

    def _password(self) -> str:
        password = resolve_credential(self._pop3_cfg, self._secrets)
        if not password:
            raise RuntimeError(
                "pop3 credentials missing: set source_meta.config.pop3.password "
                "or pop3.password_ref"
            )
        return password

    def _connect_pop3(self) -> poplib.POP3:
        host = self._pop3_cfg.get("host")
        username = self._pop3_cfg.get("username")
        if not host or not username:
            raise RuntimeError("pop3.host and pop3.username are required")
        port = int(self._pop3_cfg.get("port", 995))
        use_ssl = bool(self._pop3_cfg.get("use_ssl", True))
        if use_ssl:
            client = poplib.POP3_SSL(str(host), port, timeout=30)
        else:
            client = poplib.POP3(str(host), port, timeout=30)
        client.user(str(username))
        client.pass_(self._password())
        return client

    async def list_messages(
        self,
        *,
        folder: str | None,
        limit: int,
        cursor: str | None,
        query: str | None,
    ) -> ListMessagesResult:
        del folder  # POP3 is INBOX-only
        return await asyncio.to_thread(self._list_messages_sync, limit, cursor, query)

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

    def _from_address(self) -> str:
        if self._settings.from_address:
            return self._settings.from_address
        username = self._smtp_cfg.get("username") or self._pop3_cfg.get("username")
        if not username:
            raise RuntimeError("email.from_address or pop3/smtp.username is required")
        return str(username)

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
        del reply_to_message_id
        return await asyncio.to_thread(
            self._send_message_sync,
            to,
            subject,
            body,
            cc or [],
            bcc or [],
        )

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

    def _list_messages_sync(
        self,
        limit: int,
        cursor: str | None,
        query: str | None,
    ) -> ListMessagesResult:
        client = self._connect_pop3()
        try:
            _, listings, _ = client.uidl()
            entries = [
                (index.decode(), uid.decode())
                for index, uid in (line.decode().split() for line in listings)
            ]
            if cursor:
                entries = [(idx, uid) for idx, uid in entries if uid < cursor]
            selected = list(reversed(entries[-limit:]))
            messages: list[MessageSummary] = []
            for index, uid in selected:
                _, lines, _ = client.top(index, 0)
                raw = b"\n".join(lines) + b"\n"
                msg = BytesParser(policy=policy.default).parsebytes(raw)
                subject = str(msg.get("Subject") or "")
                if query and query.lower() not in subject.lower():
                    continue
                messages.append(
                    MessageSummary(
                        id=uid,
                        thread_id=uid,
                        from_address=parse_addresses(msg.get("From"))[0]
                        if parse_addresses(msg.get("From"))
                        else "",
                        to=parse_addresses(msg.get("To")),
                        subject=subject,
                        date=format_message_date(msg),
                        snippet=truncate_text(subject, 200),
                        is_read=True,
                        has_attachments=False,
                    )
                )
            next_cursor = selected[0][1] if len(entries) > len(selected) and selected else None
            return ListMessagesResult(messages=messages, next_cursor=next_cursor)
        finally:
            try:
                client.quit()
            except Exception:
                pass

    def _read_message_sync(
        self,
        message_id: str,
        include_body: bool,
        prefer: str,
    ) -> MessageDetail:
        client = self._connect_pop3()
        try:
            _, listings, _ = client.uidl()
            index = None
            for raw_index, uid in (line.decode().split() for line in listings):
                if uid == message_id:
                    index = raw_index
                    break
            if index is None:
                raise RuntimeError(f"message not found: {message_id!r}")

            _, lines, _ = client.retr(int(index))
            raw = b"\r\n".join(lines)
            msg = BytesParser(policy=policy.default).parsebytes(raw)
            body_text = body_html = None
            if include_body:
                body_text, body_html = extract_bodies(
                    msg,
                    prefer=prefer,
                    max_bytes=self._settings.body_max_bytes,
                )
            attachments = [
                AttachmentMeta(**meta) for meta in extract_attachment_meta(msg)
            ]
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
                is_read=True,
                has_attachments=bool(attachments),
                body_text=body_text,
                body_html=body_html,
                attachments=attachments,
            )
        finally:
            try:
                client.quit()
            except Exception:
                pass
