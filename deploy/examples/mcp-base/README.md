# mcp-base 예제 번들

각 디렉토리는 배포 가능한 MCP 서버 번들의 **학습용** 대표 예제다.

> **운영 번들** (email, 사내 API 연동 등)은 [`bundles/mcp/`](../../../bundles/mcp/) 에 둔다. 같은 zip·`source_meta` 계약이지만 CI·온보딩 친화적 코드만 이 디렉토리에 유지한다.

**런타임 계약**

- factory 시그니처: `def build_server(cfg: dict, secrets: SecretResolver) -> NativeObj`
- factory 는 `(checksum, principal_id, user.updated_at)` 조합당 1회 호출 — 서버 객체 재사용.
- mcp-base 의 runner ([runtimes/mcp-base/src/mcp_base/runner.py](../../../runtimes/mcp-base/src/mcp_base/runner.py)) 가 `runtime_kind` 별로 호출 규약을 다르게 적용:
  - `fastmcp` : `await instance.call_tool(tool, args)` + `await instance.list_tools()`
  - `mcp_sdk` : `await instance.dispatch(tool, args)` + `await instance.list_tools()` (커스텀 어댑터 객체 필요)
- **API 키는 `source_meta.config`** 에 직접 둔다 (shared credential). **principal별 identity** (mailbox, OAuth refresh) 는 `user_meta.config`. 인프라 DSN 은 `secrets_ref` 경유. 층 정의: [ARCHITECTURE.md](../../../ARCHITECTURE.md) §5.

---

## source vs user — 번들별 예시

config 층 정의는 [ARCHITECTURE.md](../../../ARCHITECTURE.md) §5. 아래는 이 디렉터리 번들에 적용한 **구체 예시**다.

| 번들 | source_meta (기동·공통) | user_meta (invoke·개인) |
|------|-------------------------|-------------------------|
| search-server ([`bundles/mcp/search_bundle/`](../../../bundles/mcp/search_bundle/)) | `naver.client_id`, `client_secret` — 모두 shared | 보통 없음 |
| email-server ([`bundles/mcp/email_bundle/`](../../../bundles/mcp/email_bundle/)) | `email.provider`, `outlook.tenant_id`, `client_secret` | `outlook.mailbox`, `refresh_token`, `email.from_address` |
| calendar-outlook ([`bundles/mcp/calendar_outlook_bundle/`](../../../bundles/mcp/calendar_outlook_bundle/)) | `outlook.tenant_id`, `client_secret`, `calendar.timezone` | `outlook.refresh_token`, `calendar.default_calendar_id` |
| calendar-google ([`bundles/mcp/calendar_google_bundle/`](../../../bundles/mcp/calendar_google_bundle/)) | `google.client_id`, `client_secret` | `google.refresh_token`, `calendar.default_calendar_id` |
| teams-server ([`bundles/mcp/teams_bundle/`](../../../bundles/mcp/teams_bundle/)) | `outlook.tenant_id`, `client_secret`, `teams.page_size` | `outlook.refresh_token`, `teams.default_team_id`, `teams.default_channel_id` |

Tool argument (`folder`, `limit`, `query`) 는 invoke payload — user_meta 가 아님.

---

## fastmcp_bundle — FastMCP 유틸리티 서버

`@mcp.tool` 데코레이터로 두 툴 등록:

| 툴 | 설명 |
|----|------|
| `calculate(expression)` | ast 기반 안전 산술 평가 (`+ - * / // % **`) |
| `fetch_url(url, timeout_seconds)` | HTTP GET, 본문 8KB cap |

타입 힌트로 inputSchema 자동 생성. agent 들이 자기 코드에 같은 이름의 툴을 두는 대신 이 서버를 호출하게 할 수 있음.

**번들 deps**: `httpx>=0.27` (FastMCP 자체는 베이스 이미지에 포함).

**source_meta.config 예시**

```json
{
  "fastmcp": {
    "strict_input_validation": true,
    "mask_error_details": true,
    "list_page_size": 50,
    "task_queue": "memory"
  }
}
```

**시크릿** (인프라 DSN, 옵션)

기본 사용 시 없음. `task_queue: "redis"` 면 `TASK_REDIS_DSN`, `session_state_store: "redis"` 면 `SESSION_REDIS_DSN`.

**source_meta 등록**

```sql
INSERT INTO source_meta (kind, name, version, runtime_pool, entrypoint, bundle_uri, checksum, config)
VALUES (
  'mcp', 'utility-server', 'v1', 'mcp:fastmcp',
  'app:build_server', 's3://bundles/utility-server-v1.zip', 'sha256:<…>',
  '{"fastmcp":{"strict_input_validation":true,"mask_error_details":true}}'::jsonb
);
```

---

## mcp_sdk_bundle — Naver search 튜토리얼 (학습용)

> **운영 번들**은 [`bundles/mcp/search_bundle/`](../../../bundles/mcp/search_bundle/) — SSRF 차단·blog/news·config 스키마 포함. 아래는 최소 MCP SDK 예제.

`mcp.server.lowlevel.Server` + `@server.list_tools()` / `@server.call_tool()` 데코레이터. SDK Server 가 stdio/HTTP 전용이라 `_Adapter` 가 mcp-base 의 `dispatch()` / `list_tools()` 컨트랙트로 브릿지.

| 툴 | 설명 |
|----|------|
| `naver_search(query, display)` | 네이버 웹 검색 (`<b>` 태그 제거 후 `[{title, link}]` 반환) |
| `fetch_url(url, timeout_seconds)` | HTTP GET, 본문 8KB cap |

agent 번들 (DeepAgent / ADK) 이 `mcp_server: "search-server"` 로 이 번들을 호출.

**번들 deps**: `mcp>=1.27`, `httpx>=0.27`.

**Naver 키는 `source_meta.config.naver`** 로 전달 (secrets_ref 아님)

```json
{
  "mcp": {"mask_error_details": false},
  "naver": {
    "client_id":     "<naver app client id>",
    "client_secret": "<naver app client secret>"
  }
}
```

`naver` 블록이 없으면 `naver_search` 호출 시 `RuntimeError("naver credentials missing: ...")` 발생. `fetch_url` 은 키 무관하게 동작.

[Naver Developers](https://developers.naver.com/) 에서 애플리케이션 등록 → 검색 API 사용 신청 → Client ID / Secret 발급.

**source_meta 등록**

```sql
INSERT INTO source_meta (kind, name, version, runtime_pool, entrypoint, bundle_uri, checksum, config)
VALUES (
  'mcp', 'search-server', 'v1', 'mcp:mcp_sdk',
  'app:build_server', 's3://bundles/search-server-v1.zip', 'sha256:<…>',
  '{"mcp":{"mask_error_details":false},"naver":{"client_id":"...","client_secret":"..."}}'::jsonb
);
```

---

## 배포 절차 (양 번들 공통)

1. 디렉토리 내용을 zip 으로 묶는다 (`app.py` 가 아카이브 루트).
2. S3 / OCI / file / http URI 에 업로드.
3. admin backend `POST /admin/source-meta` 로 등록.
4. principal 별 override 는 admin backend `POST /admin/user-meta`.

---

## didim_rag / t2sql

내부 인프라(DidimRAG 스토리지, PostgreSQL pgvector) 에 직접 연결하는 서버. runner 가 `await instance.call(tool, args)` 호출. 번들에 클라이언트 코드 포함, 접속 정보는 `secrets_ref`. 별도 운영 문서 참조.
