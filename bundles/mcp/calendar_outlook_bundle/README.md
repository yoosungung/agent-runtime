# calendar_outlook_bundle — Microsoft 365 Calendar MCP

| 항목 | 값 |
|------|-----|
| kind | `mcp` |
| name | `calendar-outlook` |
| runtime_pool | `mcp:mcp_sdk` |
| entrypoint | `app:build_server` |

## MCP 툴

| 툴 | 설명 |
|----|------|
| `list_calendars` | 접근 가능한 캘린더 목록 |
| `list_events` | 기간별 이벤트 목록 |
| `get_event` | 단일 이벤트 상세 |
| `find_availability` | free/busy |
| `create_event` | 일정 생성 (Teams 온라인 미팅 옵션) |
| `update_event` | partial patch |
| `cancel_event` | 일정 취소/삭제 |

## Config

**source_meta**

```json
{
  "mcp": {"mask_error_details": true},
  "calendar": {"page_size": 25, "timezone": "Asia/Seoul"},
  "outlook": {
    "tenant_id": "...",
    "client_id": "...",
    "client_secret": "...",
    "auth": "oauth_refresh"
  }
}
```

**user_meta** (principal별)

```json
{
  "outlook": {"mailbox": "hong@company.com", "refresh_token": "..."},
  "calendar": {"default_calendar_id": "..."}
}
```

Azure AD delegated scopes: `Calendars.ReadWrite`, `User.Read`, `offline_access`.

email-server·teams-server와 **동일 Azure app** + `outlook.refresh_token` 공유 가능.

## deps

`mcp`, `httpx`, `msal`

## 테스트

```bash
uv run pytest deploy/examples/tests/test_mcp_bundles.py::TestCalendarOutlookBundle -v
```
