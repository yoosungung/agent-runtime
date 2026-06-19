# deploy

런타임의 Kubernetes 배포 매니페스트(`k8s/`) + 배포 가능한 사용자 번들 샘플(`examples/`). Kustomize 기반. 네임스페이스 `runtime`.

## 설계

- **레이아웃**: `k8s/base/` (공통 정의) + `k8s/overlays/{dev,prod}` (오버레이 패치).
- **공용 설정**: `_shared.yaml`의 ConfigMap `runtime-env` — 모든 Deployment가 `envFrom`으로 읽는다. 환경별 값은 overlay에서 JSON 패치로 교체.
- **리소스 분류**
  - 메타데이터 DB: `postgres` StatefulSet + Service (PVC 5Gi). **auth / deploy-api만 접근.**
  - **Redis**: LangGraph 체크포인터 + ext-authz warm-registry 공용.
  - 서비스: `auth`, `deploy-api`, `ext-authz`, `envoy`, `backend`
  - Agent pools (2 정적): `agent-pool-compiled-graph` / `-adk` — 동일한 `agent-base:latest` 이미지, `RUNTIME_KIND` env만 다름
  - MCP pools (2 정적): `mcp-pool-fastmcp` / `-mcp-sdk` — 동일 패턴
  - **Image 모드 pool (동적)**: admin이 `POST /api/admin/custom-images` 호출 시 backend가 K8s API로 생성. 네이밍 규칙 `{kind}-pool-custom-{slug}`. 정적 kustomize 파일 없음. (`agent-pool-custom.yaml` / `mcp-pool-custom.yaml` 삭제됨)

## 컨테이너 이미지 (GHCR)

- **레지스트리**: `ghcr.io/yoosungung/agent-runtime/<service>:latest` (+ commit SHA tag)
- **빌드**: GitHub Actions on Release publish (`.github/workflows/build-images.yml`) — push마다 빌드하지 않음
- **dev overlay**: base `agents-runtime/*` → GHCR remap, `imagePullSecrets: registry-creds` (private GHCR 시)
- **Kaniko / NCR**: deprecated — Makefile `make images`는 legacy

## Ingress 호스트

| overlay | 외부 호스트 | 용도 |
|---------|------------|------|
| dev | `http://agents.k8s-test` (HTTP only, no TLS) | admin SPA, `/api/*`, `/v1/agents/*` (agent call) |
| stage/prod (base) | `https://agents.didim365.app` | 동일 + Let's Encrypt |
| stage/prod (base) | `agents.didim365.app` | 동일 라우팅 |

Pod 간 MCP (`MCP_GATEWAY_URL`) 및 backend chat (`ENVOY_URL`)는 **클러스터 내부** `http://envoy.runtime.svc.cluster.local:8080` — Ingress 경유하지 않음.

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
- Envoy replicas: 2 (고정). data plane 확장(Envoy HPA 등)은 [ROADMAP.md](../ROADMAP.md) 참고.

### EDS / headless — 유래와 정리

**조사 결과: EDS 도입 근거가 구현과 맞물린 적이 없고, headless Service는 그에 대한 매니페스트만 남아 있었다.**

| 항목 | 유래 (initial commit, `51ce500`) | 실제 구현 |
|------|----------------------------------|-----------|
| ROADMAP “Envoy HPA / subset LB / **EDS**” | gateway 제거 후 Envoy 확장을 염두에 둔 **미구현 TODO**. “warm pod subset → Envoy subset LB”와 “EndpointSlice EDS”를 한 줄에 묶었으나 설계 문서·코드에 구체화되지 않음 | warm pick은 **Redis warm-registry + ext-authz `Scheduler.pick()`**. Envoy는 **`x-pod-addr` → `dynamic_forward_proxy`** 로 pod IP 직접 연결 |
| `agent-pool-compiled-graph-headless` | 동일 커밋에 **주석·참조 없이** ClusterIP Service와 함께 추가. 다른 pool(`-adk`, mcp)에는 없음 | 코드·Envoy·ext-authz 어디에서도 DNS/URL로 참조하지 않음. fallback은 ClusterIP `agent-pool-compiled-graph`만 사용 |

**왜 headless가 생겼는지에 대한 명시적 근거는 저장소에 없다.** ROADMAP의 EDS 항목과 시기가 같아, EDS/DNS 기반 pod 발견을 위한 **선행 매니페스트(placeholder)** 로 추정되나, Envoy xDS·subset LB·headless DNS endpoint 열거 등 **후속 작업이 없었다.**

**조치 (배포·코드):**

- 미사용 `agent-pool-compiled-graph-headless` Service **삭제** (`agent-pool-compiled-graph.yaml`).
- `Scheduler.pick()` cold-start는 **해당 pool의 ClusterIP Service URL**(`pool_fallback_url`)만 사용. 제거된 headless/ring-hash endpoint 열거 경로 없음. 구현: `packages/common/scheduling.py`, `services/ext-authz/app.py`.

**현재 규모에서는 EDS가 필요하지 않다.**

- EDS endpoint 수 = pool **pod** 수(HPA/KEDA `maxReplicas` ~10/pool). agent/MCP 정의 수와 무관.
- warm affinity는 앱 레이어(Redis) 책임. EDS subset LB로 checksum별 라우팅을 옮기는 방안은 agent 수에 비례해 xDS가 비대해져 **채택하지 않음**.
- `dynamic_forward_proxy` + `max_hosts: 1024`로 현재 pool 규모에 충분.

**조치:** pool당 ClusterIP Service 하나만 유지. cold-start는 `Scheduler.pick(..., pool_fallback_url=)` → ext-authz `x-pod-addr`.

향후 pool pod가 수백 개 이상이거나 Envoy data plane 자체를 수평 확장해야 할 때만 EDS·Envoy HPA를 별도 검토([ROADMAP.md](../ROADMAP.md)). warm 스케줄링은 ext-authz + Redis 유지.

## env 배선

- `POSTGRES_DSN`은 **auth / deploy-api에만** 주입. gateway·pool은 받지 않는다.
- ext-authz에는 `DEPLOY_API_URL`, `AUTH_URL`, `REDIS_URL` + bundle 모드 pool 서비스 URL 환경 변수. `POOL_CUSTOM_URL`/`POOL_MCP_CUSTOM_URL`은 삭제 — image 모드 URL은 slug에서 동적 derive.
- pool에는 `DEPLOY_API_URL`, `REDIS_URL`, `POD_NAME`, `POD_IP`, `POD_PORT`, `MAX_CONCURRENT`, `REGISTRY_HEARTBEAT_INTERVAL_SEC=2`, `REGISTRY_TTL_SEC=3`.
- backend(BFF)에는 `ENVOY_URL=http://envoy.runtime.svc.cluster.local:8080` — chat invoke 시 Envoy를 직접 호출.

## RBAC

`backend-k8s-rbac.yaml`에서 backend ServiceAccount(`backend-admin`)에 `runtime` 네임스페이스 한정 Role+RoleBinding 정의:

- 대상 리소스: `deployments`, `services`, `scaledobjects.keda.sh`, `poddisruptionbudgets`
- 권한: `create`, `update`, `delete`, `get`, `list`, `patch`

backend SA는 `automountServiceAccountToken: true` (in-cluster K8s API 접근용). ext-authz는 K8s 권한 불필요 — slug 기반 DNS derive로 동작.

## NetworkPolicy 요약

| 수신자 | 허용 송신자 |
|---|---|
| postgres | auth, deploy-api, backend, pgbouncer, migration-job |
| redis | `runtime/role: pool` 라벨 pod (정적+동적 통합), ext-authz |
| deploy-api | `runtime/role: pool` 라벨 pod, ext-authz + ingress-nginx |
| auth | ext-authz, backend |
| ext-authz | envoy만 |
| envoy | 모든 클러스터 내 (포트 8080) |

**`runtime/role: pool` 라벨**: 정적 bundle 모드 pool Deployment와 backend가 동적으로 생성하는 image 모드 pool pod 모두 이 라벨을 가진다. NetworkPolicy selector가 pod 이름 패턴이 아닌 라벨 기반이므로 신규 image pool 등록 시 NetworkPolicy 변경 불필요.

## examples/

`deploy/examples/custom-image/` — image 모드 raw contract를 만족하는 Dockerfile 예제:

- `python-agent/` — FastAPI + `POST /invoke` + `/healthz` + `/readyz`
- `python-mcp/` — 동일 구조, MCP 서버 역할
- `go-agent/` — Go `net/http` 구현 예제 (멀티스테이지 빌드, alpine 최종 이미지)
