"""Microsoft Graph Teams + Chat client for teams_bundle."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import msal
from models import (
    ChannelSummary,
    ChatSummary,
    CreateChatResult,
    ListChannelsResult,
    ListChatsResult,
    ListMessagesResult,
    ListTeamsResult,
    MessageSummary,
    SendMessageResult,
    TeamsSettings,
    TeamSummary,
)
from utils import clamp_limit, graph_message_to_summary, resolve_credential, truncate_text

from runtime_common.secrets import SecretResolver

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_DELEGATED_SCOPES = [
    "Team.ReadBasic.All",
    "Channel.ReadBasic.All",
    "ChannelMessage.Read.All",
    "ChannelMessage.Send",
    "Chat.ReadWrite",
    "User.Read",
    "offline_access",
]


class GraphTeamsClient:
    def __init__(self, cfg: dict, secrets: SecretResolver) -> None:
        self._settings = TeamsSettings.from_cfg(cfg)
        self._outlook_cfg = dict(cfg.get("outlook") or {})
        self._secrets = secrets

    def _require_outlook_fields(self) -> tuple[str, str, str]:
        tenant_id = self._outlook_cfg.get("tenant_id")
        client_id = self._outlook_cfg.get("client_id")
        client_secret = resolve_credential(
            self._outlook_cfg,
            self._secrets,
            value_key="client_secret",
            ref_key="client_secret_ref",
        )
        if not all([tenant_id, client_id, client_secret]):
            raise RuntimeError(
                "outlook credentials missing: set source_meta.config.outlook "
                "{tenant_id, client_id, client_secret} and "
                "user_meta.config.outlook.refresh_token"
            )
        return str(tenant_id), str(client_id), str(client_secret)

    def _acquire_token(self) -> str:
        tenant_id, client_id, client_secret = self._require_outlook_fields()
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret,
        )
        refresh_token = self._outlook_cfg.get("refresh_token")
        if not refresh_token:
            raise RuntimeError(
                "outlook refresh token missing: set user_meta.config.outlook.refresh_token"
            )
        result = app.acquire_token_by_refresh_token(
            refresh_token,
            scopes=_DELEGATED_SCOPES,
        )
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

    async def list_joined_teams(self) -> ListTeamsResult:
        data = await self._request(
            "GET",
            "/me/joinedTeams",
            params={"$select": "id,displayName,description"},
        )
        teams = [
            TeamSummary(
                id=item["id"],
                name=item.get("displayName") or "",
                description=item.get("description"),
            )
            for item in data.get("value") or []
        ]
        return ListTeamsResult(teams=teams)

    async def list_channels(self, *, team_id: str | None) -> ListChannelsResult:
        selected = team_id or self._settings.default_team_id
        if not selected:
            raise ValueError("team_id is required")
        data = await self._request(
            "GET",
            f"/teams/{selected}/channels",
            params={"$select": "id,displayName,description"},
        )
        channels = [
            ChannelSummary(
                id=item["id"],
                name=item.get("displayName") or "",
                description=item.get("description"),
            )
            for item in data.get("value") or []
        ]
        return ListChannelsResult(channels=channels)

    async def list_chats(
        self,
        *,
        limit: int,
        cursor: str | None,
        expand_members: bool,
    ) -> ListChatsResult:
        limit = clamp_limit(limit, default=self._settings.page_size)
        params: dict[str, Any] = {"$top": limit, "$orderby": "lastMessagePreview/createdDateTime desc"}
        if expand_members:
            params["$expand"] = "members"
        if cursor:
            data = await self._request("GET", cursor)
        else:
            data = await self._request("GET", "/me/chats", params=params)
        chats = [
            ChatSummary(
                id=item["id"],
                topic=item.get("topic"),
                chat_type=item.get("chatType") or "unknown",
            )
            for item in data.get("value") or []
        ]
        next_cursor = data.get("@odata.nextLink")
        if next_cursor and next_cursor.startswith(_GRAPH_BASE):
            next_cursor = next_cursor[len(_GRAPH_BASE) :]
        return ListChatsResult(chats=chats, next_cursor=next_cursor)

    async def list_channel_messages(
        self,
        *,
        team_id: str | None,
        channel_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> ListMessagesResult:
        selected_team = team_id or self._settings.default_team_id
        selected_channel = channel_id or self._settings.default_channel_id
        if not selected_team or not selected_channel:
            raise ValueError("team_id and channel_id are required")
        limit = clamp_limit(limit, default=self._settings.page_size)
        if cursor:
            data = await self._request("GET", cursor)
        else:
            path = f"/teams/{selected_team}/channels/{selected_channel}/messages"
            data = await self._request("GET", path, params={"$top": limit})
        messages = [
            MessageSummary(**graph_message_to_summary(item, max_bytes=self._settings.body_max_bytes))
            for item in data.get("value") or []
        ]
        next_cursor = data.get("@odata.nextLink")
        if next_cursor and next_cursor.startswith(_GRAPH_BASE):
            next_cursor = next_cursor[len(_GRAPH_BASE) :]
        return ListMessagesResult(messages=messages, next_cursor=next_cursor)

    async def list_chat_messages(
        self,
        *,
        chat_id: str,
        limit: int,
        cursor: str | None,
    ) -> ListMessagesResult:
        limit = clamp_limit(limit, default=self._settings.page_size)
        if cursor:
            data = await self._request("GET", cursor)
        else:
            data = await self._request(
                "GET",
                f"/chats/{chat_id}/messages",
                params={"$top": limit},
            )
        messages = [
            MessageSummary(**graph_message_to_summary(item, max_bytes=self._settings.body_max_bytes))
            for item in data.get("value") or []
        ]
        next_cursor = data.get("@odata.nextLink")
        if next_cursor and next_cursor.startswith(_GRAPH_BASE):
            next_cursor = next_cursor[len(_GRAPH_BASE) :]
        return ListMessagesResult(messages=messages, next_cursor=next_cursor)

    async def send_channel_message(
        self,
        *,
        team_id: str | None,
        channel_id: str | None,
        content: str,
        content_type: str,
    ) -> SendMessageResult:
        selected_team = team_id or self._settings.default_team_id
        selected_channel = channel_id or self._settings.default_channel_id
        if not selected_team or not selected_channel:
            raise ValueError("team_id and channel_id are required")
        ctype = "html" if content_type.lower() == "html" else "text"
        payload = {
            "body": {
                "contentType": ctype,
                "content": truncate_text(content, self._settings.body_max_bytes),
            }
        }
        path = f"/teams/{selected_team}/channels/{selected_channel}/messages"
        data = await self._request("POST", path, json_body=payload)
        return SendMessageResult(id=data.get("id") or "")

    async def send_chat_message(
        self,
        *,
        chat_id: str,
        content: str,
        content_type: str,
    ) -> SendMessageResult:
        ctype = "html" if content_type.lower() == "html" else "text"
        payload = {
            "body": {
                "contentType": ctype,
                "content": truncate_text(content, self._settings.body_max_bytes),
            }
        }
        data = await self._request(
            "POST",
            f"/chats/{chat_id}/messages",
            json_body=payload,
        )
        return SendMessageResult(id=data.get("id") or "")

    async def create_chat(self, *, member_user_id: str) -> CreateChatResult:
        me = await self._request("GET", "/me", params={"$select": "id"})
        my_id = me.get("id")
        if not my_id:
            raise RuntimeError("failed to resolve signed-in user id")
        payload = {
            "chatType": "oneOnOne",
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"{_GRAPH_BASE}/users('{my_id}')",
                },
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"{_GRAPH_BASE}/users('{member_user_id}')",
                },
            ],
        }
        data = await self._request("POST", "/chats", json_body=payload)
        return CreateChatResult(id=data.get("id") or "", web_url=data.get("webUrl"))
