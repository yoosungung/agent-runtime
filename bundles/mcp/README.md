# bundles/mcp — 운영 MCP 서버

외부 시스템과 연동하는 MCP 서버 번들. mcp-base pool(`mcp:fastmcp`, `mcp:mcp_sdk`, …)에 배포한다.

**런타임 계약** — [deploy/examples/mcp-base/README.md](../../deploy/examples/mcp-base/README.md) 와 동일:

- `def build_server(cfg: dict, secrets: SecretResolver) -> NativeObj`
- **source_meta.config** / **user_meta.config** / **secrets_ref** — 층 정의는 [ARCHITECTURE.md](../../ARCHITECTURE.md) §5. email-server 예시는 아래 및 [`email_bundle/README.md`](email_bundle/README.md).

## email_bundle — IMAP / POP3 / Outlook / Gmail

[`email_bundle/`](email_bundle/) — `list_messages`, `read_message`, `send_message`.

| 툴 | 설명 |
|----|------|
| `list_messages` | 폴더별 메일 목록 |
| `read_message` | 본문 조회 |
| `send_message` | plain-text 발송 |

**deps**: `mcp>=1.27`, `httpx>=0.27`, `msal` (Outlook), `google-auth` (Gmail), `email-validator`

**source_meta 등록 (Outlook + oauth_refresh 예시)**

```json
{
  "mcp": {"mask_error_details": true},
  "email": {"provider": "outlook", "page_size": 25},
  "outlook": {
    "tenant_id": "<azure-tenant-id>",
    "client_id": "<app-client-id>",
    "client_secret": "<app-secret>",
    "auth": "oauth_refresh"
  }
}
```

```sql
INSERT INTO source_meta (kind, name, version, runtime_pool, entrypoint, bundle_uri, checksum, config)
VALUES (
  'mcp', 'email-server', 'v1', 'mcp:mcp_sdk',
  'app:build_server', 's3://bundles/email-server-v1.zip', 'sha256:<…>',
  '{"mcp":{"mask_error_details":true},"email":{"provider":"outlook"},"outlook":{"tenant_id":"...","client_id":"...","client_secret":"...","auth":"oauth_refresh"}}'::jsonb
);
```

**user_meta upsert (principal별 mailbox)**

```json
{
  "email": {"from_address": "hong@company.com"},
  "outlook": {
    "mailbox": "hong@company.com",
    "refresh_token": "<delegated-oauth-refresh-token>"
  }
}
```

Admin: `PUT /api/user-meta` with `source_meta_id`, `principal_id`, `config`.

## search_bundle — Naver Search + URL fetch

[`search_bundle/`](search_bundle/) — `naver_search`, `fetch_url`.

| 툴 | 설명 |
|----|------|
| `naver_search` | Naver 웹/블로그/뉴스 검색 |
| `fetch_url` | HTTP GET (SSRF 차단, 8KB 기본 cap) |

**deps**: `mcp>=1.27`, `httpx>=0.27`

**source_meta 등록 예시**

```json
{
  "mcp": {"mask_error_details": true},
  "search": {"max_display": 10},
  "naver": {
    "client_id": "<naver-app-client-id>",
    "client_secret": "<naver-app-client-secret>"
  },
  "fetch": {"max_bytes": 8192}
}
```

```sql
INSERT INTO source_meta (kind, name, version, runtime_pool, entrypoint, bundle_uri, checksum, config)
VALUES (
  'mcp', 'search-server', 'v1', 'mcp:mcp_sdk',
  'app:build_server', 's3://bundles/search-server-v1.zip', 'sha256:<…>',
  '{"mcp":{"mask_error_details":true},"naver":{"client_id":"...","client_secret":"..."}}'::jsonb
);
```

API 키는 shared이므로 `user_meta` 없이도 동작. 상세: [`search_bundle/README.md`](search_bundle/README.md).

---

학습용 FastMCP / MCP SDK 튜토리얼은 [deploy/examples/mcp-base/](../../deploy/examples/mcp-base/) 를 본다.
