# ext-authz

Envoy **HTTP ext_authz** 서비스. agent/mcp 통합 단일 서비스. 역할은 두 가지:

1. **스케줄러** (`/{path:path}` catch-all) — auth + access + resolve + pod pick. 바디 릴레이는 Envoy(C++)가 담당.
2. **MCP 발견** — `GET /v1/mcp/servers`(인증+access 필터, ext-authz direct), `GET /v1/mcp/servers/{name}/catalog`(ext_authz check + Envoy → pool `/catalog`).
3. **MCP stream auth** (`POST /v1/mcp/stream`) — Envoy ext_authz `check()`로 auth·pick 후 **Envoy가 pool `/mcp`로 relay**.

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
6. **`DeployApiClient.resolve(kind, name, version, principal)` → `source.runtime_pool` + 전체 `SourceMeta`**. 404 → 404 패스-스루.
7. **`runtime_pool` 파싱 → 모드 분기** (`parse_runtime_pool(source.runtime_pool)`):
   - **Bundle 모드** (`slug is None`): `Scheduler.pick(runtime_kind, checksum, ring_key, pool_fallback_url=...)`. warm miss 시 해당 pool ClusterIP Service URL. `ring_key`는 trace용으로만 유지.
   - **Image 모드** (`slug is not None`, `runtime_kind == "custom"`): Scheduler 미호출. Service DNS를 slug에서 derive — `{kind}-pool-custom-{slug}.{runtime_namespace}.svc.{cluster_domain}:8080`. 이 URL을 fallback addr로 사용.
8. **`x-runtime-cfg` 헤더 첨부**: `{**source.config, **user.config}` shallow merge(user wins) 결과를 `base64(json)` 인코딩. Bundle/Image 모드 공통. Envoy `max_request_headers_kb=64` 내에 안전히 들어가도록 등록 시 16 KB 상한 검증.
9. **`x-runtime-secrets-ref` 헤더**: `user_meta.secrets_ref` opaque 패스스루 (예: `vault://...`). 없으면 헤더 생략.
10. **응답** 200 + 헤더:
    - `x-pod-addr: <host:port>` — warm pod IP (없으면 pool Service host:port). Envoy Lua 필터가 `:authority`로 복사. **Image 모드는 항상 빈 값(fallback 경로 사용)**.
    - `x-pod-fallback-addr: <host:port>` — 항상 pool Service URL. Envoy가 retry 시 이 주소로 재시도.
    - `x-principal: <base64(json)>` — pool이 역직렬화해서 사용.
    - `x-runtime-cfg: <base64(json)>` — merged config.
    - `x-runtime-secrets-ref: <opaque>` — secrets ref (있을 때만).
    - `x-source-checksum`, `x-source-version`.
    - `x-grace-applied: 1` (적용됐을 때만).
    - 실패: 401 / 403 / 404 / 429 / 502 — Envoy가 클라이언트에 그대로 전달.

**Image 모드 라우팅 특성**: K8s Service DNS(`{kind}-pool-custom-{slug}.runtime.svc.cluster.local:8080`)로 직접 라우팅. warm-registry 미참여(모든 pod 동일 이미지 → 단순 LB). `minReplicas=1` 보장으로 endpoint가 항상 존재한다는 가정 유지.

### MCP 발견

- **`GET /v1/mcp/servers`**: Bearer 필수. deploy-api `source_meta`와 `Principal.access` 교집합 → `{name, version}`만 반환.
- **`GET /v1/mcp/servers/{name}/catalog`**: ext_authz `check()` → Envoy가 pool `GET /catalog` relay. 응답 `{tools, resources, prompts}`.

### MCP stream (`POST /v1/mcp/stream`)

Envoy ext_authz 필터 **활성** — invoke와 동일하게 `check()`만 호출하고 **응답 body/SSE는 Envoy → pool passthrough**.

- **`X-Mcp-Server` / `X-Mcp-Version`** 헤더로 서버 식별 (JSON-RPC body의 `server` 필드 사용 안 함).
- 성공 시 `x-pod-addr`, `x-pod-fallback-addr`, **`x-mcp-principal`** 반환 → Envoy route가 path를 **`/mcp`** 로 rewrite 후 pool relay.
- `initialize`만 있고 `X-Mcp-Server` 없으면 JWT 검증 후 **기본 mcp pool**(fastmcp Service)로 relay — handshake JSON은 pool `/mcp`가 응답.

### Envoy와의 계약

- **ext_authz HTTP** 모드. `authorization_request.allowed_headers`: `authorization`, `content-type`, `x-*` 접두사.
- `with_request_body.max_request_bytes: 65536`, `allow_partial_message: true` — 대용량 agent payload에서 413 방지.
- `authorization_response.allowed_upstream_headers`: invoke용 `x-pod-addr`, `x-principal`, … + stream용 **`x-mcp-principal`**.
- MCP **server list** (`GET /v1/mcp/servers` exact)만 `ext_authz_direct` + 필터 비활성화. **catalog/stream/invoke**는 ext_authz + `pool_dfp`.

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
| `pool_fastmcp_url` | `http://mcp-pool-fastmcp.runtime.svc.cluster.local:8080` | |
| `pool_mcp_sdk_url` | `http://mcp-pool-mcp-sdk.runtime.svc.cluster.local:8080` | |
| `pool_didim_rag_url` | `http://mcp-pool-didim-rag.runtime.svc.cluster.local:8080` | |
| `pool_t2sql_url` | `http://mcp-pool-t2sql.runtime.svc.cluster.local:8080` | |
| `runtime_namespace` | `runtime` | image 모드 Service DNS 생성 시 네임스페이스 |
| `cluster_domain` | `cluster.local` | image 모드 Service DNS 클러스터 도메인 |
| `mcp_internal_grace_sec` | `300` | `/v1/mcp/invoke-internal` grace 기간 |
| `rate_limit_per_principal` | `60` | /min |
| `rate_limit_per_resource` | `120` | /min |
| `auth_cache_ttl_sec` | `5` | AuthClient in-process verify 캐시 TTL |
| `auth_cache_max` | `1024` | AuthClient LRU 최대 엔트리 |
| `deploy_cache_ttl_sec` | `60` | DeployApiClient resolve 캐시 TTL |
| `deploy_cache_max` | `256` | DeployApiClient LRU 최대 엔트리 |

**Image 모드 URL 도출 규칙**: `pool_custom_url` / `pool_mcp_custom_url` 환경 변수는 제거됐다. Image 모드 pool Service URL은 slug에서 런타임에 derive — `http://{kind}-pool-custom-{slug}.{runtime_namespace}.svc.{cluster_domain}:8080`. 새 이미지가 등록될 때마다 ext-authz를 재시작할 필요 없음.
