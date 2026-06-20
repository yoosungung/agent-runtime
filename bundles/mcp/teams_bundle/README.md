# teams_bundle — Microsoft Teams MCP

| 항목 | 값 |
|------|-----|
| kind | `mcp` |
| name | `teams-server` |
| runtime_pool | `mcp:mcp_sdk` |
| entrypoint | `app:build_server` |

## MCP 툴

| 툴 | 설명 |
|----|------|
| `list_joined_teams` | 가입 팀 목록 |
| `list_channels` | 팀 채널 목록 |
| `list_chats` | 1:1·그룹 채팅 목록 |
| `list_channel_messages` | 채널 최근 메시지 |
| `list_chat_messages` | 채팅 최근 메시지 |
| `send_channel_message` | 채널 메시지 발송 |
| `send_chat_message` | 채팅 메시지 발송 |
| `create_chat` | 1:1 채팅 생성 |

Delegated auth only (MVP). 메시지 send는 tenant DLP·ACL에 주의.

## Config

**source_meta**

```json
{
  "mcp": {"mask_error_details": true},
  "teams": {"page_size": 25, "body_max_bytes": 8192},
  "outlook": {
    "tenant_id": "...",
    "client_id": "...",
    "client_secret": "...",
    "auth": "oauth_refresh"
  }
}
```

**user_meta**

```json
{
  "outlook": {"mailbox": "hong@company.com", "refresh_token": "..."},
  "teams": {"default_team_id": "...", "default_channel_id": "..."}
}
```

Delegated scopes: `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Read.All`, `ChannelMessage.Send`, `Chat.ReadWrite`, `offline_access`.

## deps

`mcp`, `httpx`, `msal`

## 테스트

```bash
uv run pytest deploy/examples/tests/test_mcp_bundles.py::TestTeamsBundle -v
```
