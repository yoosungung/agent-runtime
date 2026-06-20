"""Gmail API email provider."""

from __future__ import annotations

import asyncio
import base64
import json
from email import policy
from email.parser import BytesParser
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import credentials as oauth_credentials
from google.oauth2 import service_account
from models import (
    AttachmentMeta,
    EmailSettings,
    ListMessagesResult,
    MessageDetail,
    MessageSummary,
    SendResult,
)
from utils import (
    build_plain_email,
    extract_attachment_meta,
    extract_bodies,
    format_message_date,
    parse_addresses,
    resolve_credential,
)

from runtime_common.secrets import SecretResolver

_GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users"
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailApiProvider:
    def __init__(self, cfg: dict, secrets: SecretResolver) -> None:
        self._settings = EmailSettings.from_cfg(cfg)
        self._gmail_cfg = dict(cfg.get("gmail") or {})
        self._secrets = secrets

    def _user_id(self) -> str:
        auth_mode = str(self._gmail_cfg.get("auth", "service_account"))
        if auth_mode == "oauth_refresh":
            return "me"
        return str(self._gmail_cfg.get("subject_email") or "me")

    def _require_client_credentials(self) -> tuple[str, str]:
        client_id = self._gmail_cfg.get("client_id")
        client_secret = resolve_credential(
            self._gmail_cfg,
            self._secrets,
            value_key="client_secret",
            ref_key="client_secret_ref",
        )
        if not client_id or not client_secret:
            raise RuntimeError(
                "gmail credentials missing: set source_meta.config.gmail.{client_id, client_secret}"
            )
        return str(client_id), str(client_secret)

    def _acquire_token(self) -> str:
        auth_mode = str(self._gmail_cfg.get("auth", "service_account"))
        if auth_mode == "oauth_refresh":
            client_id, client_secret = self._require_client_credentials()
            refresh_token = self._gmail_cfg.get("refresh_token")
            if not refresh_token:
                raise RuntimeError(
                    "gmail refresh token missing: set user_meta.config.gmail.refresh_token "
                    "(source_meta provides client_id, client_secret)"
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

        service_account_info = self._gmail_cfg.get("service_account")
        subject_email = self._gmail_cfg.get("subject_email")
        if not service_account_info or not subject_email:
            raise RuntimeError(
                "gmail service account missing: set gmail.service_account and gmail.subject_email"
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
        url = f"{_GMAIL_BASE}/{path}"
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
            if not response.content:
                return {}
            return response.json()

    async def list_messages(
        self,
        *,
        folder: str | None,
        limit: int,
        cursor: str | None,
        query: str | None,
    ) -> ListMessagesResult:
        user = self._user_id()
        params: dict[str, Any] = {"maxResults": limit}
        label = folder or self._settings.default_folder
        if label:
            params["labelIds"] = label
        if query:
            params["q"] = query
        if cursor:
            params["pageToken"] = cursor
        data = await self._request("GET", f"{user}/messages", params=params)
        summaries: list[MessageSummary] = []
        for item in data.get("messages") or []:
            detail = await self._request(
                "GET",
                f"{user}/messages/{item['id']}",
                params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]},  # noqa: E501
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in detail.get("payload", {}).get("headers") or []
            }
            summaries.append(
                MessageSummary(
                    id=detail["id"],
                    thread_id=detail.get("threadId") or detail["id"],
                    from_address=parse_addresses(headers.get("from"))[0]
                    if parse_addresses(headers.get("from"))
                    else "",
                    to=parse_addresses(headers.get("to")),
                    subject=headers.get("subject") or "",
                    date=headers.get("date") or "",
                    snippet=detail.get("snippet") or "",
                    is_read="UNREAD" not in (detail.get("labelIds") or []),
                    has_attachments=bool(detail.get("payload", {}).get("parts")),
                )
            )
        return ListMessagesResult(messages=summaries, next_cursor=data.get("nextPageToken"))

    async def read_message(
        self,
        *,
        message_id: str,
        include_body: bool,
        prefer: str,
    ) -> MessageDetail:
        user = self._user_id()
        detail = await self._request(
            "GET",
            f"{user}/messages/{message_id}",
            params={"format": "full"},
        )
        raw = self._extract_raw_message(detail)
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        body_text = body_html = None
        if include_body:
            body_text, body_html = extract_bodies(
                msg,
                prefer=prefer,
                max_bytes=self._settings.body_max_bytes,
            )
        attachments = [AttachmentMeta(**meta) for meta in extract_attachment_meta(msg)]
        headers = {
            h["name"].lower(): h["value"] for h in detail.get("payload", {}).get("headers") or []
        }
        return MessageDetail(
            id=detail["id"],
            thread_id=detail.get("threadId") or detail["id"],
            from_address=parse_addresses(headers.get("from"))[0]
            if parse_addresses(headers.get("from"))
            else "",
            to=parse_addresses(headers.get("to")),
            subject=headers.get("subject") or "",
            date=format_message_date(msg) or headers.get("date") or "",
            snippet=detail.get("snippet") or "",
            is_read="UNREAD" not in (detail.get("labelIds") or []),
            has_attachments=bool(attachments),
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
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
        del reply_to_message_id
        from_address = self._settings.from_address or self._user_id()
        message = build_plain_email(
            from_address=str(from_address),
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
        )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        user = self._user_id()
        result = await self._request(
            "POST",
            f"{user}/messages/send",
            json_body={"raw": raw},
        )
        return SendResult(id=result.get("id") or subject, status="sent")

    @staticmethod
    def _extract_raw_message(detail: dict[str, Any]) -> bytes:
        payload = detail.get("payload") or {}
        if "body" in payload and payload["body"].get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"] + "==")
        parts = payload.get("parts") or []
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"] + "==")
        for part in parts:
            if part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"] + "==")
        raise RuntimeError("unable to decode Gmail message body")
