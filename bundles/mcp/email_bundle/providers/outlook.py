"""Microsoft Graph (Outlook) email provider."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import msal
from models import (
    AttachmentMeta,
    EmailSettings,
    ListMessagesResult,
    MessageDetail,
    MessageSummary,
    SendResult,
)
from utils import resolve_credential, truncate_text

from runtime_common.secrets import SecretResolver

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_CLIENT_SCOPES = ["https://graph.microsoft.com/.default"]
_DELEGATED_SCOPES = ["Mail.Read", "Mail.Send", "offline_access"]


class OutlookGraphProvider:
    def __init__(self, cfg: dict, secrets: SecretResolver) -> None:
        self._settings = EmailSettings.from_cfg(cfg)
        self._outlook_cfg = dict(cfg.get("outlook") or {})
        self._secrets = secrets

    def _require_outlook_fields(self) -> tuple[str, str, str, str]:
        tenant_id = self._outlook_cfg.get("tenant_id")
        client_id = self._outlook_cfg.get("client_id")
        client_secret = resolve_credential(
            self._outlook_cfg,
            self._secrets,
            value_key="client_secret",
            ref_key="client_secret_ref",
        )
        mailbox = self._outlook_cfg.get("mailbox")
        if not all([tenant_id, client_id, client_secret, mailbox]):
            raise RuntimeError(
                "outlook credentials missing: set source_meta.config.outlook "
                "{tenant_id, client_id, client_secret} and user_meta.config.outlook "
                "{mailbox} (or source mailbox for client_credentials mode)"
            )
        return str(tenant_id), str(client_id), str(client_secret), str(mailbox)

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
                    "outlook refresh token missing: set user_meta.config.outlook.refresh_token "
                    "(source_meta provides tenant_id, client_id, client_secret)"
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
        url = f"{_GRAPH_BASE}{path}"
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
            if response.status_code == 202 or not response.content:
                return {}
            return response.json()

    def _mailbox_path(self) -> str:
        _, _, _, mailbox = self._require_outlook_fields()
        auth_mode = str(self._outlook_cfg.get("auth", "client_credentials"))
        if auth_mode == "oauth_refresh":
            return "/me"
        return f"/users/{mailbox}"

    def _folder_segment(self, folder: str | None) -> str:
        selected = folder or self._settings.default_folder
        if selected.upper() == "INBOX":
            return "inbox"
        return selected

    async def list_messages(
        self,
        *,
        folder: str | None,
        limit: int,
        cursor: str | None,
        query: str | None,
    ) -> ListMessagesResult:
        folder_id = self._folder_segment(folder)
        params: dict[str, Any] = {
            "$top": limit,
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,conversationId,subject,from,toRecipients,receivedDateTime,"
                "bodyPreview,isRead,hasAttachments"
            ),
        }
        if query:
            params["$search"] = f'"{query}"'
        if cursor:
            data = await self._request("GET", cursor)
        else:
            path = f"{self._mailbox_path()}/mailFolders/{folder_id}/messages"
            data = await self._request("GET", path, params=params)
        messages = [
            MessageSummary(
                id=item["id"],
                thread_id=item.get("conversationId") or item["id"],
                from_address=(item.get("from") or {}).get("emailAddress", {}).get("address", ""),
                to=[
                    r.get("emailAddress", {}).get("address", "")
                    for r in item.get("toRecipients") or []
                    if r.get("emailAddress", {}).get("address")
                ],
                subject=item.get("subject") or "",
                date=item.get("receivedDateTime") or "",
                snippet=item.get("bodyPreview") or "",
                is_read=bool(item.get("isRead")),
                has_attachments=bool(item.get("hasAttachments")),
            )
            for item in data.get("value") or []
        ]
        next_cursor = data.get("@odata.nextLink")
        if next_cursor and next_cursor.startswith(_GRAPH_BASE):
            next_cursor = next_cursor[len(_GRAPH_BASE) :]
        return ListMessagesResult(messages=messages, next_cursor=next_cursor)

    async def read_message(
        self,
        *,
        message_id: str,
        include_body: bool,
        prefer: str,
    ) -> MessageDetail:
        path = f"{self._mailbox_path()}/messages/{message_id}"
        params = None
        if include_body:
            params = {"$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,body,isRead,hasAttachments,attachments"}  # noqa: E501
        data = await self._request("GET", path, params=params)
        body = data.get("body") or {}
        content = body.get("content") or ""
        content_type = (body.get("contentType") or "text").lower()
        body_text = body_html = None
        if include_body:
            if content_type == "html":
                body_html = truncate_text(content, self._settings.body_max_bytes)
                if prefer == "text":
                    from utils import strip_html

                    body_text = truncate_text(strip_html(content), self._settings.body_max_bytes)
            else:
                body_text = truncate_text(content, self._settings.body_max_bytes)
        attachments = [
            AttachmentMeta(
                name=a.get("name") or "attachment",
                size=int(a.get("size") or 0),
                content_type=a.get("contentType") or "application/octet-stream",
            )
            for a in data.get("attachments") or []
            if not a.get("isInline")
        ]
        return MessageDetail(
            id=data["id"],
            thread_id=data.get("conversationId") or data["id"],
            from_address=(data.get("from") or {}).get("emailAddress", {}).get("address", ""),
            to=[
                r.get("emailAddress", {}).get("address", "")
                for r in data.get("toRecipients") or []
                if r.get("emailAddress", {}).get("address")
            ],
            subject=data.get("subject") or "",
            date=data.get("receivedDateTime") or "",
            snippet=truncate_text(data.get("subject") or "", 200),
            is_read=bool(data.get("isRead")),
            has_attachments=bool(data.get("hasAttachments")),
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
        del bcc  # Graph sendMail uses explicit recipients in message only
        payload: dict[str, Any] = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
            },
            "saveToSentItems": True,
        }
        if cc:
            payload["message"]["ccRecipients"] = [
                {"emailAddress": {"address": addr}} for addr in cc
            ]
        if reply_to_message_id:
            payload["message"]["conversationId"] = reply_to_message_id
        path = f"{self._mailbox_path()}/sendMail"
        await self._request("POST", path, json_body=payload)
        return SendResult(id=subject, status="sent")
