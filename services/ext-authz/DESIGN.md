# ext-authz

Envoy **HTTP ext_authz** 서비스. agent/mcp 통합 단일 서비스. 역할은 두 가지:

1. **스케줄러** (`/{path:path}` catch-all) — auth + access + resolve + pod pick. 바디 릴레이는 Envoy(C++)가 담당.
2. **MCP 발견·스트림 프록시** (`GET /v1/mcp/servers*`, `POST /v1/mcp/stream`) — Envoy의 ext_authz 필터를 우회해 ext-authz가 직접 처리.

`kind` (agent | mcp)과 grace_sec (edge 0 / internal `MCP_INTERNAL_GRACE_SEC`)은 요청 경로(`:path`)로 판정한다.

## 설계

### check() — ext_authz 스케줄러 (`POST /v1/agents/invoke`, `POST /v1/mcp/invoke`, `POST /v1/mcp/invoke-internal`)

1. **경로 → `(kind, grace_sec)`**:
   - `/v1/agents/invoke` → (`agent`, 0)
   - `/v1/mcp/invoke-internal` → (`mcp`, `MCP_INTERNAL_GRACE_SEC`)  ← 순서 중요, `/invoke`보다 먼저 매칭
   - `/v1/mcp/invoke` → (`mcp`, 0)
   - 그 외 → 403
2. **JWT 추출 + 검증**: `Authorization: Bearer <jwt>`. `AuthClient.verify(token, grace_sec)` → `Principal`.
3. **리소스 식별자**: `x-runtime-name` 헤더 우선. 없으면 body JSON에서 `agent`/`server` + `version` 파싱(하위호환 폴백). 헤더만 있으면 빈 body도 허용.
4. **Access 검사**: `principal.can_access(kind, name)` — 실패 시 403.
5. **Rate limit**: principal 단위(기본 60/min) + resource 단위(기본 120/min). 초과 시 429.
6. **`DeployApiClient.resolve(kind, name, version)` → `source.runtime_pool` + `checksum`**. 404 → 404 패스-스루.
7. **pod pick**: `Scheduler.pick(runtime_kind, checksum, ring_key)`. `ring_key = "{kind}:{name}:{version}:{checksum}"` (kind prefix 포함).
8. **응답** 200 + 헤더:
   - `x-pod-addr: <host:port>` — warm pod IP (없으면 pool Service host:port). Envoy Lua 필터가 `:authority`로 복사.
   - `x-pod-fallback-addr: <host:port>` — 항상 pool Service URL. Envoy가 retry 시 이 주소로 재시도.
   - `x-principal: <base64(json)>` — pool이 역직렬화해서 사용.
   - `x-source-checksum`, `x-source-version`.
   - `x-grace-applied: 1` (적용됐을 때만).
   - 실패: 401 / 403 / 404 / 429 / 502 — Envoy가 클라이언트에 그대로 전달.

### MCP 발견 + 스트림 (`GET /v1/mcp/servers`, `GET /v1/mcp/servers/{name}/tools`, `POST /v1/mcp/stream`)

Envoy가 이 경로를 `ext_authz_direct` 클러스터로 직접 라우팅한다(ext_authz 필터 비활성화 per-route).

- **`GET /v1/mcp/servers`**: deploy-api `/v1/source-meta?kind=mcp` 프록시. 인증 불필요.
- **`GET /v1/mcp/servers/{name}/tools`**: Bearer 토큰 검증 → access 검사 → resolve → warm pod pick → pool `/tools` 프록시.
- **`POST /v1/mcp/stream`**: Bearer 검증 → `X-Mcp-Server` 헤더로 서버 식별 → resolve → warm pod pick → pool `/mcp` 프록시(SSE 스트리밍 포함). 서버 헤더 없으면 JSON-RPC 2.0 `initialize` 응답 반환(MCP 프로토콜 핸드셰이크 지원).

### Envoy와의 계약

- **ext_authz HTTP** 모드. `authorization_request.allowed_headers`: `authorization`, `content-type`, `x-*` 접두사.
- `with_request_body.max_request_bytes: 65536`, `allow_partial_message: true` — 대용량 agent payload에서 413 방지.
- `authorization_response.allowed_upstream_headers`: `x-pod-addr`, `x-pod-fallback-addr`, `x-principal`, `x-source-checksum`, `x-source-version`, `x-grace-applied`.
- MCP discovery/stream 라우트는 `typed_per_filter_config`로 ext_authz 필터 비활성화 + `ext_authz_direct` 클러스터로 직접 라우팅.

### Envoy 필터 체인 (invoke 경로)

```
envoy.filters.http.ext_authz        ← auth + access + resolve + pod pick
envoy.filters.http.lua              ← :authority ← x-pod-addr (retry 시 x-pod-fallback-addr)
envoy.filters.http.dynamic_forward_proxy
envoy.filters.http.router           ← cluster: pool_dfp
```

Lua 필터: `x-envoy-attempt-count > 1`이면 `:authority`를 `x-pod-fallback-addr`(pool Service URL)로 교체. 최초 시도는 warm pod IP 사용. `/v1/agents/` 라우트에 `retry_policy: connect-failure,refused-stream, num_retries: 1`.

### 공용 컴포넌트

- `AuthClient`, `DeployApiClient`, `RegistrySubscriber`(agent + mcp 각 1개), `RegistryQuery`, `Scheduler` × 2, `RateLimiter` × 2(principal/resource), `httpx.AsyncClient`(MCP 프록시용) — 모두 `runtime_common` 기존 구현.
- 두 RegistrySubscriber는 lifespan에서 병렬 기동, 하나만 unhealthy여도 `/readyz` NotReady.

### 설정

| 변수 | 기본값 | 용도 |
|---|---|---|
| `pool_compiled_graph_url` | `http://agent-pool-compiled-graph.runtime.svc.cluster.local:8080` | agent:compiled_graph 폴백 |
| `pool_adk_url` | `http://agent-pool-adk.runtime.svc.cluster.local:8080` | |
| `pool_custom_url` | `http://agent-pool-custom.runtime.svc.cluster.local:8080` | |
| `pool_fastmcp_url` | `http://mcp-pool-fastmcp.runtime.svc.cluster.local:8080` | |
| `pool_mcp_sdk_url` | `http://mcp-pool-mcp-sdk.runtime.svc.cluster.local:8080` | |
| `pool_didim_rag_url` | `http://mcp-pool-didim-rag.runtime.svc.cluster.local:8080` | |
| `pool_t2sql_url` | `http://mcp-pool-t2sql.runtime.svc.cluster.local:8080` | |
| `mcp_internal_grace_sec` | `300` | `/v1/mcp/invoke-internal` grace 기간 |
| `rate_limit_per_principal` | `60` | /min |
| `rate_limit_per_resource` | `120` | /min |
