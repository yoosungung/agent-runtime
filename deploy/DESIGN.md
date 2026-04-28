# deploy

런타임의 Kubernetes 배포 매니페스트(`k8s/`) + 배포 가능한 사용자 번들 샘플(`examples/`). Kustomize 기반. 네임스페이스 `runtime`.

## 설계

- **레이아웃**: `k8s/base/` (공통 정의) + `k8s/overlays/{dev,prod}` (오버레이 패치).
- **공용 설정**: `_shared.yaml`의 ConfigMap `runtime-env` — 모든 Deployment가 `envFrom`으로 읽는다. 환경별 값은 overlay에서 JSON 패치로 교체.
- **리소스 분류**
  - 메타데이터 DB: `postgres` StatefulSet + Service (PVC 5Gi). **auth / deploy-api만 접근.**
  - **Redis**: LangGraph 체크포인터 + ext-authz warm-registry 공용.
  - 서비스: `auth`, `deploy-api`, `ext-authz`, `envoy`, `backend`
  - Agent pools (3): `agent-pool-compiled-graph` / `-adk` / `-custom` — 동일한 `agent-base:latest` 이미지, `RUNTIME_KIND` env만 다름
  - MCP pools (4): `mcp-pool-fastmcp` / `-mcp-sdk` / `-didim-rag` / `-t2sql` — 동일 패턴

## Envoy 데이터플레인

Envoy가 모든 `/v1/agents/*` + `/v1/mcp/*` 트래픽을 처리한다. agent-gateway·mcp-gateway는 제거됐다.

### 필터 체인 (invoke 경로)

```
ext_authz filter  →  ext-authz 서비스 (auth+access+resolve+pick)
Lua filter        →  :authority ← x-pod-addr (retry 시 x-pod-fallback-addr)
dynamic_forward_proxy
router            →  pool_dfp cluster
```

### 라우트 테이블

| 경로 | ext_authz | 목적지 | 비고 |
|---|---|---|---|
| `GET /v1/mcp/servers*` | 비활성(per-route) | `ext_authz_direct` | MCP 서버 목록/도구 조회 |
| `POST /v1/mcp/stream` | 비활성(per-route) | `ext_authz_direct` | MCP JSON-RPC 스트리밍 |
| `/v1/agents/*` | 활성 | `pool_dfp` + retry | agent invoke. `:path` → `/invoke` rewrite |
| `/v1/mcp/*` | 활성 | `pool_dfp` | mcp invoke. `:path` → `/invoke` rewrite |
| `/healthz` | — | direct 200 | |

### 클러스터

- `ext_authz_cluster`: ext-authz 서비스 (ext_authz 필터가 check 호출에 사용)
- `ext_authz_direct`: ext-authz 서비스 (discovery/stream 직접 라우팅용 — 동일 주소, 의미 구분)
- `pool_dfp`: `dynamic_forward_proxy` — Lua가 설정한 `:authority`(pod IP 또는 Service URL)로 직접 연결

### warm pod fallback retry

ext-authz가 `x-pod-addr`(warm pod IP)과 함께 `x-pod-fallback-addr`(pool Service URL)을 응답 헤더로 반환. Lua filter가 `x-envoy-attempt-count > 1`이면 `:authority`를 fallback addr로 교체. `/v1/agents/` 라우트에 `retry_policy: connect-failure,refused-stream, num_retries: 1`.

### 주요 설정값

- `with_request_body.max_request_bytes: 65536`, `allow_partial_message: true`
- `stream_idle_timeout: 0s`, `request_timeout: 0s` — SSE 스트리밍 패스스루
- Envoy replicas: 2 (고정). HPA/EDS 전환은 향후 계획.

## env 배선

- `POSTGRES_DSN`은 **auth / deploy-api에만** 주입. gateway·pool은 받지 않는다.
- ext-authz에는 `DEPLOY_API_URL`, `AUTH_URL`, `REDIS_URL` + pool 서비스 URL 환경 변수.
- pool에는 `DEPLOY_API_URL`, `REDIS_URL`, `POD_NAME`, `POD_IP`, `POD_PORT`, `MAX_CONCURRENT`, `REGISTRY_HEARTBEAT_INTERVAL_SEC=2`, `REGISTRY_TTL_SEC=3`.
- backend(BFF)에는 `ENVOY_URL=http://envoy.runtime.svc.cluster.local:8080` — chat invoke 시 Envoy를 직접 호출.

## NetworkPolicy 요약

| 수신자 | 허용 송신자 |
|---|---|
| postgres | auth, deploy-api, backend, pgbouncer, migration-job |
| redis | agent-pool, mcp-pool, ext-authz |
| deploy-api | agent-pool, mcp-pool, ext-authz + ingress-nginx |
| auth | ext-authz, backend |
| ext-authz | envoy만 |
| envoy | 모든 클러스터 내 (포트 8080) |
