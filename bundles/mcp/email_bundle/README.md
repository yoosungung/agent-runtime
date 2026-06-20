# email_bundle — 운영 MCP 메일 서버

Agent가 메일함을 **list / read / send** 할 수 있는 MCP SDK 번들. `source_meta` / `user_meta` 층: [ARCHITECTURE.md](../../../ARCHITECTURE.md) §5.

| 항목 | 값 |
|------|-----|
| kind | `mcp` |
| name (예) | `email-server` |
| runtime_pool | `mcp:mcp_sdk` |
| entrypoint | `app:build_server` |

## MCP 툴

| 툴 | 설명 |
|----|------|
| `list_messages` | 폴더 내 메일 목록 (페이지네이션·검색) |
| `read_message` | 단일 메일 본문·첨부 메타 조회 |
| `send_message` | plain-text 메일 발송 |

## Provider

`source_meta.config.email.provider` 로 백엔드를 선택한다 (배포당 1 provider).

| provider | 읽기 | 발송 | 1차 인증 | 2차 인증 |
|----------|------|------|----------|----------|
| `imap` | IMAP | SMTP | config username/password | `user_meta.config` password override |
| `pop3` | POP3 (INBOX) | SMTP | 동일 | 동일 |
| `outlook` | Microsoft Graph | Graph sendMail | app permission + shared mailbox | `auth: oauth_refresh` + `refresh_token` |
| `gmail` | Gmail API | Gmail API send | service account + domain delegation | `auth: oauth_refresh` + `refresh_token` |

## Config 예시

### 공통

```json
{
  "mcp": {"mask_error_details": true},
  "email": {
    "provider": "imap",
    "default_folder": "INBOX",
    "page_size": 25,
    "body_max_bytes": 32768,
    "from_address": "bot@company.com"
  }
}
```

### IMAP + SMTP

```json
{
  "imap": {
    "host": "imap.example.com",
    "port": 993,
    "use_ssl": true,
    "username": "bot@company.com",
    "password": "..."
  },
  "smtp": {
    "host": "smtp.example.com",
    "port": 587,
    "use_starttls": true,
    "username": "bot@company.com",
    "password": "..."
  }
}
```

비밀번호 대신 env 참조: `"password_ref": "EMAIL_IMAP_PASSWORD"` → `secrets.resolve()`.

### Outlook (Microsoft Graph)

```json
{
  "email": {"provider": "outlook"},
  "outlook": {
    "tenant_id": "...",
    "client_id": "...",
    "client_secret": "...",
    "mailbox": "shared-inbox@company.com",
    "auth": "client_credentials"
  }
}
```

Delegated OAuth (principal별 refresh token — `user_meta.config` merge):

```json
{
  "outlook": {
    "auth": "oauth_refresh",
    "refresh_token": "..."
  }
}
```

### Gmail API

Service account + domain-wide delegation:

```json
{
  "email": {"provider": "gmail"},
  "gmail": {
    "auth": "service_account",
    "subject_email": "bot@company.com",
    "service_account": { "...": "..." }
  }
}
```

## 배포

[deploy/examples/mcp-base/README.md](../../../deploy/examples/mcp-base/README.md) 와 동일:

1. 디렉토리를 zip (`app.py` 가 아카이브 루트, `providers/`·`models.py`·`utils.py` 포함)
2. 업로드 후 `POST /api/source-meta/bundle` 등록
3. `user_resource_access` 부여

## deps

번들 `pyproject.toml` 및 mcp-base 이미지: `mcp`, `httpx`, `msal`, `google-auth`, `google-api-python-client`, `email-validator`.

## 테스트

```bash
uv run --package mcp-base pytest deploy/examples/tests/test_mcp_bundles.py::TestEmailBundle -v
```
