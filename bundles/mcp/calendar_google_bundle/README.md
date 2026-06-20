# calendar_google_bundle — Google Calendar MCP

| 항목 | 값 |
|------|-----|
| kind | `mcp` |
| name | `calendar-google` |
| runtime_pool | `mcp:mcp_sdk` |
| entrypoint | `app:build_server` |

## MCP 툴

`calendar-outlook` 과 **동일 tool name·schema** (agent 호환).

## Config

**source_meta**

```json
{
  "mcp": {"mask_error_details": true},
  "calendar": {"timezone": "Asia/Seoul", "create_meet_link": true},
  "google": {
    "client_id": "...",
    "client_secret": "...",
    "auth": "oauth_refresh"
  }
}
```

**user_meta**

```json
{
  "google": {"refresh_token": "..."},
  "calendar": {"default_calendar_id": "primary"}
}
```

Google OAuth scopes: `calendar`, `calendar.events`. email `gmail` 블록과 분리 (`google` 블록 사용).

Service account + domain delegation: `auth: service_account`, `subject_email`, `service_account` JSON.

## deps

`mcp`, `httpx`, `google-auth`, `google-api-python-client`

## 테스트

```bash
uv run pytest deploy/examples/tests/test_mcp_bundles.py::TestCalendarGoogleBundle -v
```
