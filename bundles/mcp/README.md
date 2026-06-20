# bundles/mcp — 운영 MCP 서버

외부 시스템과 연동하는 MCP 서버 번들. mcp-base pool(`mcp:fastmcp`, `mcp:mcp_sdk`, …)에 배포한다.

**런타임 계약** — [deploy/examples/mcp-base/README.md](../../deploy/examples/mcp-base/README.md) 와 동일:

- `def build_server(cfg: dict, secrets: SecretResolver) -> NativeObj`
- tool별 API 키 → `source_meta.config` (예: `cfg["naver"]`, `cfg["microsoft"]`)
- 인프라 DSN → `secrets_ref`

## 예정 / 운영 번들

### outlook_bundle (예정)

Microsoft Graph — shared mailbox 기준 메일 읽기·발송.

| 툴 | 설명 |
|----|------|
| `list_messages` | 받은편지함 목록 |
| `get_message` | 본문 조회 |
| `send_mail` | 메일 발송 |

```json
{
  "mcp": {"mask_error_details": true},
  "microsoft": {
    "tenant_id": "...",
    "client_id": "...",
    "client_secret": "..."
  },
  "mailbox": "shared-inbox@company.com"
}
```

1차: application permission + shared mailbox. 개인 받은편함(delegated)은 `secrets_ref` refresh token 으로 확장.

**deps**: `mcp>=1.27`, `httpx>=0.27`, `msal`

---

학습용 FastMCP / MCP SDK 튜토리얼은 [deploy/examples/mcp-base/](../../deploy/examples/mcp-base/) 를 본다.
