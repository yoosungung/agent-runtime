# search_bundle — 운영 MCP 검색 서버

Agent가 **Naver 웹 검색**과 **URL 본문 fetch**를 할 수 있는 MCP SDK 번들. `source_meta` / `user_meta` 층: [ARCHITECTURE.md](../../../ARCHITECTURE.md) §5.

| 항목 | 값 |
|------|-----|
| kind | `mcp` |
| name (예) | `search-server` |
| runtime_pool | `mcp:mcp_sdk` |
| entrypoint | `app:build_server` |

## MCP 툴

| 툴 | 설명 |
|----|------|
| `naver_search` | Naver OpenAPI 검색 (`web` / `blog` / `news`) |
| `fetch_url` | HTTP GET, SSRF 차단, 본문 truncate |

## Config 예시

```json
{
  "mcp": {"mask_error_details": true},
  "search": {"max_display": 10, "default_category": "web"},
  "naver": {
    "client_id": "<naver-app-client-id>",
    "client_secret": "<naver-app-client-secret>"
  },
  "fetch": {
    "max_bytes": 8192,
    "user_agent": "company-bot/1.0",
    "allow_private_network": false
  }
}
```

비밀번호 대신 env 참조: `"client_secret_ref": "NAVER_CLIENT_SECRET"` → `secrets.resolve()`.

`user_meta`는 보통 없음 — Naver API 키는 배포 단위 shared credential ([mcp-base README](../../../deploy/examples/mcp-base/README.md)).

## Naver 한도

- 일 25,000쿼리/앱 ([웹문서 검색 API](https://developers.naver.com/docs/serviceapi/search/web/web.md))
- `display` 최대 100 (기본 config 상한 10 — 하위호환)

## fetch_url 보안

- `http`/`https`만 허용
- localhost·사설 IP·link-local·metadata IP 차단 (DNS resolve 후 재검증)
- redirect 최대 5회, 각 hop 재검증
- 사내망 fetch 필요 시 `fetch.allow_private_network: true`로 명시 opt-in

## 배포

[deploy/examples/mcp-base/README.md](../../../deploy/examples/mcp-base/README.md) 와 동일:

1. 디렉토리를 zip (`app.py` 가 아카이브 루트, `providers/`·`models.py`·`utils.py` 포함)
2. 업로드 후 `POST /api/source-meta/bundle` 등록
3. `user_resource_access` 부여

## deps

번들 `pyproject.toml`: `mcp`, `httpx`, `runtime-common`.

## 테스트

```bash
uv run pytest deploy/examples/tests/test_mcp_bundles.py::TestSearchBundle -v
```
