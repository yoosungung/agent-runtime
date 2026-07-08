# deploy

런타임의 Kubernetes 배포 매니페스트(`k8s/`) + 배포 가능한 사용자 번들 샘플(`examples/`). Kustomize 기반. 네임스페이스 `runtime`(Garage object store 포함).

## K8s 디렉터리 (`k8s/`)

```
deploy/k8s/
  garage/               # 내장 S3 호환 번들 저장소 (base에서 runtime NS로 포함)
    statefulset.yaml    # Garage v2.3 --single-node --default-bucket
    service.yaml        # garage-s3 :3900
    garage-secrets.env  # dev 기본 access key / bucket (prod overlay에서 교체)
    # backend s3-creds: deploy/k8s/base/s3-creds.env (garage-secrets.env와 key 동기화)
  base/                 # 공통 정의 (namespace: runtime)
    namespace.yaml
    postgres.yaml
    redis.yaml
    auth.yaml
    deploy-api.yaml
    backend.yaml        # BUNDLE_STORAGE_BACKEND=s3 (s3-creds secret)
    ext-authz.yaml
    envoy.yaml
    agent-pool-compiled-graph.yaml
    agent-pool-adk.yaml
    mcp-pool-fastmcp.yaml
    mcp-pool-mcp-sdk.yaml
    ingress.yaml        # prod/stage: agents.didim365.app
    ...
  overlays/
    dev/                # GHCR images, agents.k8s-test Ingress, replicas=1, no KEDA
    stage/
    prod/
```

적용:

```bash
make k8s-apply-dev          # IMAGE_TAG=git rev-parse HEAD (default)
make k8s-redeploy-dev       # GHA build → apply with current HEAD SHA
```

컨테이너 이미지 빌드·GHCR push는 GitHub Actions — [## Commands](#commands) 참조.

`k8s-apply-*`는 overlay 한 번으로 **Garage + runtime 스택**을 함께 적용한다. `jwt-keys`·`registry-creds` secret이 없으면 idempotent하게 생성한다. **`s3-creds`**는 kustomize가 Garage bootstrap credential과 함께 생성한다 — 외부 S3 사용 시 `make s3-secret`으로 덮어쓴다. `registry-creds`는 `GITHUB_USER`/`GITHUB_PAT`가 없을 때 `gh auth token --user $(GHCR_USER)`로 시도(`REGISTRY`의 GHCR owner, 기본 `yoosungung`). 수동 갱신: `GITHUB_USER=... GITHUB_PAT=... make registry-secret`

### Garage (기본 번들 object store)

| 항목 | 값 |
|------|-----|
| NS | `runtime` |
| S3 API | `http://garage-s3.runtime.svc.cluster.local:3900` |
| Bucket | `runtime-bundles` |
| Bootstrap | Garage v2.3 `--single-node --default-bucket` (layout/ bucket/key 자동) |
| backend secret | `runtime/s3-creds` (`BUNDLE_STORAGE_BACKEND=s3` + endpoint + key) |
| dev credentials | `deploy/k8s/garage/*.env` — **k8s-test 전용**, prod는 overlay secret 교체 |

**외부 S3로 교체** (NCP·AWS 등):

```bash
# .s3-config.json 작성 후
S3_BUCKET=my-bucket make s3-secret
kubectl -n runtime rollout restart deployment/backend
```

Garage StatefulSet은 그대로 두거나 `kubectl -n runtime scale sts/garage --replicas=0`으로 중지. 예전 `garage` NS에 남은 리소스는 `kubectl delete namespace garage`로 정리.

**prod HA (RF=3)**: overlay에서 `garage` StatefulSet `replicas`·`replication_factor`·zone layout을 수동/Job으로 확장 — base는 dev 단일 노드(RF=1).

### dev overlay 차이

| 설정 | dev | stage/prod (base) |
|------|-----|-------------------|
| Ingress | `agents.k8s-test`, HTTP only (no TLS) | `agents.didim365.app` + Let's Encrypt |
| Image registry | GHCR remap + `imagePullSecrets` | overlay별 |
| Replicas | 1 (모든 Deployment) | HPA/KEDA 기본값 |
| KEDA ScaledObject | 제거 | 활성 |
| Postgres | direct (`pgbouncer` replicas=0) | pgbouncer 경유 |
| `ENV` / `LOG_LEVEL` | dev / DEBUG | stage·prod / INFO |

### 외부 vs 클러스터 내부 URL

| 용도 | URL |
|------|-----|
| Browser / admin SPA / `/api/*` | `http://agents.k8s-test/` (dev, `/etc/hosts`) |
| Chat UI agent invoke | `http://agents.k8s-test/v1/agents/invoke` (Ingress → Envoy, BFF 미경유) |
| External agent invoke | `http://agents.k8s-test/v1/agents/...` |
| Pod-to-pod MCP (`MCP_GATEWAY_URL`) | `http://envoy.runtime.svc.cluster.local:8080` |
| Backend legacy chat proxy (`ENVOY_URL`) | 동일 internal envoy ( `/api/chat/invoke` 전용) |

`/v1/mcp/invoke-internal`·`/v1/agents/invoke-internal`은 공개 Ingress에 없음 — agent pool이 클러스터 내 envoy Service로 직접 호출.

각 pool은 동일 base image + 다른 `RUNTIME_KIND` env의 별도 `Deployment`.

## 설계

- **레이아웃**: `k8s/base/` (공통 정의) + `k8s/overlays/{dev,prod}` (오버레이 패치).
- **공용 설정**: `_shared.yaml`의 ConfigMap `runtime-env` — bootstrap 정적 env (서비스 URL, REDIS_URL). 환경별 값은 overlay에서 JSON 패치.
- **Pipeline lifecycle (backend)**: ConfigMap `runtime-env`에 `NEBULA_*`(호스트/포트). Secret `pipeline-infra-secrets`에 `PATH_GRAPH_DSN`·`NEBULA_PASSWORD`. dev overlay는 pgbouncer 미사용 시 `PATH_GRAPH_DSN`을 postgres 직접 DSN으로 패치. 벡터 검색은 runtime Postgres **17 + pgvector** (`pgvector/pgvector:pg17`, `path_graph.chunks.embedding`).
- **동적 플랫폼 infra**: ConfigMap `runtime-infra` + Secret `runtime-infra-secrets` — admin `PUT /api/infra-meta` 후 backend reconciler가 생성·갱신. pool Deployment 4종 + custom image pool이 `envFrom`(optional)으로 마운트.
- **리소스 분류**
  - 메타데이터 DB: `postgres` StatefulSet + Service (PVC 5Gi, **PostgreSQL 17 + pgvector**). **auth / deploy-api / path_graph 스키마 공유.**
  - **Redis**: LangGraph 체크포인터 + ext-authz warm-registry 공용.
  - 서비스: `auth`, `deploy-api`, `ext-authz`, `envoy`, `backend`
- Agent pools (3 정적): `agent-pool-compiled-graph` / `-adk` (`agent-base` 이미지) + `agent-pool-hermes` (`hermes-base`)
  - MCP pools (2 정적): `mcp-pool-fastmcp` / `-mcp-sdk` — 동일 패턴
  - **Image 모드 pool (동적)**: admin이 `POST /api/admin/custom-images` 호출 시 backend가 K8s API로 생성. 네이밍 규칙 `{kind}-pool-custom-{slug}`. 정적 kustomize 파일 없음. (`agent-pool-custom.yaml` / `mcp-pool-custom.yaml` 삭제됨)

## 컨테이너 이미지 (GHCR)

- **레지스트리**: `ghcr.io/yoosungung/agent-runtime/<service>:<git-sha>` — **`:latest` 미사용**. 배포 시 `IMAGE_TAG`(`git rev-parse HEAD` 기본)로 kustomize `__IMAGE_TAG__` 치환(`make k8s-apply-*`). base overlay의 모든 runtime `Deployment`는 `imagePullPolicy: IfNotPresent` — immutable tag이므로 노드 캐시 안전.
- **빌드**: GitHub Actions (`.github/workflows/build-images.yml`) — Release publish 또는 `workflow_dispatch`
- **overlays**: `components/ghcr-images`로 GHCR remap + tag placeholder. dev/stage/prod 공통.

## Ingress 호스트

| overlay | 외부 호스트 | 용도 |
|---------|------------|------|
| dev | `http://agents.k8s-test` (HTTP only, no TLS) | admin SPA, `/api/*`, `/v1/agents/*`, `/v1/mcp/invoke` |
| stage/prod (base) | `https://agents.didim365.app` | 동일 + Let's Encrypt |
| stage/prod (base) | `agents.didim365.app` | 동일 라우팅 |

### 공개 Ingress 경로 (dev~prod 공통)

| 경로 | 백엔드 | 비고 |
|------|--------|------|
| `/v1/agents/*` | envoy | ext_authz — agent invoke |
| `/v1/mcp/invoke` | envoy | ext_authz — MCP invoke |
| `/` | backend | SPA + `/api/*` (BFF, 세션·CSRF) |
| `/bundles/*` | backend (catch-all) | **403** — `BlockPublicBundleMiddleware` (proxy headers) |
| `/v1/source-meta`, `/v1/user-meta` | — | **미노출** — admin은 `/api/*` BFF |
| `/v1/mcp/servers`, `/v1/mcp/stream` | — | **미노출** — backend·pool은 in-cluster envoy |

Pod 간 MCP (`MCP_GATEWAY_URL`) 및 backend 레거시 chat proxy (`ENVOY_URL`, `/api/chat/invoke`)는 **클러스터 내부** `http://envoy.runtime.svc.cluster.local:8080` — Ingress 경유하지 않음. **Chat UI는 Ingress `/v1/agents/*`를 same-origin으로 호출**한다. Pool bundle fetch는 `BUNDLE_PUBLIC_BASE_URL=http://backend.runtime.svc.cluster.local:8000/bundles`.

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
| `GET /v1/mcp/servers` (exact) | — | `ext_authz_direct` | MCP 서버 목록 (JWT + access, name/version) |
| `GET /v1/mcp/servers/*/catalog` | 활성 | `pool_dfp` + `/catalog` rewrite | tools/resources/prompts catalog |
| `POST /v1/mcp/stream` | 활성 | `pool_dfp` + `/mcp` rewrite | MCP JSON-RPC/SSE |
| `/v1/agents/jobs` 및 `/v1/agents/jobs/*` | 활성 | `pool_dfp` + retry | async job submit/poll. `path_separated_prefix` → `/jobs` rewrite (invoke 규칙보다 우선) |
| `/v1/agents/*` (jobs 제외) | 활성 | `pool_dfp` + retry | agent invoke. `:path` → `/invoke` rewrite |
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

### KEDA pool autoscale (`keda.yaml`)

- 신호: pool pod OTEL gauge `pool_active_requests` (Prometheus).
- 트리거: **`max(pool_active_requests{service_name=...})`** ≥ threshold (기본 24 = `MAX_CONCURRENT=32` × 75%). pool **평균**이 아닌 **hot-spot pod** 기준 — 단일 busy pod만으로도 scale-up.
- `minReplicaCount=2`, `maxReplicaCount=10` per pool. ext-authz **spillover/soft_spill**과 함께 쓰면 새 pod가 cold spill을 받아 warm 확장.

## env 배선

- `POSTGRES_DSN`은 **auth / deploy-api에만** 주입. gateway·pool은 받지 않는다.
- ext-authz에는 `DEPLOY_API_URL`, `AUTH_URL`, `REDIS_URL` + bundle 모드 pool 서비스 URL 환경 변수. `POOL_CUSTOM_URL`/`POOL_MCP_CUSTOM_URL`은 삭제 — image 모드 URL은 slug에서 동적 derive.
- pool에는 `DEPLOY_API_URL`, `REDIS_URL`, `POD_NAME`, `POD_IP`, `POD_PORT`, `MAX_CONCURRENT`, `REGISTRY_HEARTBEAT_INTERVAL_SEC=2`, `REGISTRY_TTL_SEC=3`.
- **agent-pool-compiled-graph (general tier, PG-3 wiki VFS)**: `VFS_DSN` + `ADMIN_BACKEND_URL` → `http://backend.runtime.svc.cluster.local:8000` (binding resolve; wiki는 PG `vfs_wiki_files` read-only mount).
- backend(BFF)에는 `ENVOY_URL=http://envoy.runtime.svc.cluster.local:8080` — 레거시 `/api/chat/invoke` 프록시용. SPA 빌드 시 `VITE_AGENTS_INVOKE_URL=/v1/agents/invoke`(Dockerfile ARG).

## RBAC

`backend-k8s-rbac.yaml`에서 backend ServiceAccount(`backend-admin`)에 `runtime` 네임스페이스 한정 Role+RoleBinding 정의:

- 대상 리소스: `deployments`, `services`, `scaledobjects.keda.sh`, `poddisruptionbudgets`
- 권한: `create`, `update`, `delete`, `get`, `list`, `patch`

backend SA는 `automountServiceAccountToken: true` (in-cluster K8s API 접근용). ext-authz는 K8s 권한 불필요 — slug 기반 DNS derive로 동작.

## NetworkPolicy 요약

| 수신자 | 허용 송신자 |
|---|---|
| postgres | auth, deploy-api, backend, pgbouncer, migration-job |
| redis | `runtime/role: pool` 라벨 pod (정적+동적 통합), ext-authz, backend |
| garage S3 (:3900) | backend, `runtime/role: pool`, agent-pool, mcp-pool (presigned redirect 후 직접 fetch) |
| deploy-api | `runtime/role: pool` 라벨 pod, ext-authz |
| auth | ext-authz, backend |
| ext-authz | envoy만 |
| envoy | 모든 클러스터 내 (포트 8080) |
| pool (`runtime/role: pool`) ingress | envoy만 (:8080) |
| pool (`runtime/role: pool`) egress | kube-system DNS, deploy-api, redis, pgbouncer-rw, envoy, backend (:8000 bundles), garage (:3900), monitoring OTLP (:4317), `opik` namespace Opik frontend (:5173, `OPIK_URL` trace ingest), llm-serving (:30000), 외부 HTTPS (:443) |

**`runtime/role: pool` 라벨**: 정적 bundle 모드 pool Deployment와 backend가 동적으로 생성하는 image 모드 pool pod 모두 이 라벨을 가진다. NetworkPolicy selector가 pod 이름 패턴이 아닌 라벨 기반이므로 신규 image pool 등록 시 NetworkPolicy 변경 불필요.

## examples/ vs bundles/

| | `deploy/examples/` | `bundles/` (repo root) |
|---|---|---|
| 목적 | 런타임·프레임워크 **학습용** 샘플 | **운영** 업무 번들 |
| MCP | `mcp-base/` (fastmcp, mcp_sdk 튜토리얼) | `bundles/mcp/` (email 등 외부 연동) |
| Agent | `agent-base/` (DeepAgent, ADK 데모) | `bundles/agent/` (업무 agent) |

배포·factory·`source_meta` 계약은 동일. zip → upload → admin 등록. 번들 테스트 로더는 examples를 먼저, 없으면 `bundles/` 를 탐색 ([conftest.py](examples/tests/conftest.py)).

## examples/

`deploy/examples/custom-image/` — image 모드 raw contract를 만족하는 Dockerfile 예제:

- `python-agent/` — FastAPI + `POST /invoke` + `/healthz` + `/readyz`
- `python-mcp/` — 동일 구조, MCP 서버 역할
- `path-graph-rag-mcp/` — path-graph hybrid search (`search` tool). Image 모드 등록 — [README](custom-image/path-graph-rag-mcp/README.md)
- `go-agent/` — Go `net/http` 구현 예제 (멀티스테이지 빌드, alpine 최종 이미지)

## Commands

### 컨테이너 이미지 빌드 (GitHub Actions → GHCR)

워크플로: [`.github/workflows/build-images.yml`](../.github/workflows/build-images.yml)

| 트리거 | 용도 |
|--------|------|
| `workflow_dispatch` | dev/stage 배포용 — **커밋 push 후** 수동 실행 (일반적) |
| Release **published** | 태그 릴리스와 함께 빌드 |

빌드 대상(8종): `backend`, `agent-base`, `mcp-base`, `hermes-base`, `path-graph-rag-mcp`, `auth`, `deploy-api`, `ext-authz`

**hermes-base** (runtime-slim):

| 단계 | 내용 |
|------|------|
| `hermes-gates` job | `scripts/hermes/check-hermes-install-policy.sh` + `test_oci_runtime_slim.py` |
| Docker build | `GIT_SHA`, `HERMES_REVISION` build-arg; vendor stage `vendor-hermes.sh` + prune |
| Size gate | `scripts/hermes/check-hermes-image-size.sh` (default max 1200 MiB) |

PR/push: [`.github/workflows/hermes-base-oci.yml`](../.github/workflows/hermes-base-oci.yml) — policy + unit + local docker build (push 없음).

**path-graph-rag-mcp** — PR/push 시 unit + docker build; `main` push·`workflow_dispatch` 시 GHCR push. 전체 8종과 함께 빌드할 때는 `build-images` matrix에도 포함.

| 트리거 | 워크플로 | push |
|--------|----------|------|
| PR (path 필터) | [`path-graph-rag-mcp.yml`](../.github/workflows/path-graph-rag-mcp.yml) | 없음 (build 검증만) |
| `main` push / `workflow_dispatch` | 동일 | `:<git-sha>` |
| `workflow_dispatch` / Release | `build-images.yml` (8종 일괄) | `:<git-sha>` |

```bash
make build-path-graph-rag-mcp      # MCP 이미지만 빠르게 GHCR push
make build-path-graph-rag-mcp-wait
```

`backend`·`agent-base`·`path-graph-rag-mcp`는 `path-graph` Python wheel이 필요하다. **release wheel URL pin** (`path-graph==0.1.6` + GitHub Release asset). GHA/Docker는 `UV_INDEX_GITHUB_*`로 private release 다운로드 후 `uv sync`/`uv pip install` — path-graph repo checkout·`path-graph/pipeline` staging 없음. 로컬 sibling 개발: `cp uv.override.toml.example uv.override.toml`. 로컬 Docker: `docker build` 시 `--build-arg UV_INDEX_GITHUB_PASSWORD=$(gh auth token)` (backend·agent-base·path-graph-rag-mcp).

태그: `ghcr.io/yoosungung/agent-runtime/<service>:<git-sha>` (`:latest` push 없음)

```bash
# 1) 변경분을 원격에 push (GHA는 checkout ref 기준)
git push origin main

# 2) 워크플로 실행 (Makefile 래퍼)
make build-images
make build-images-wait   # 또는 gh run watch <run-id>

# 3) 클러스터에 반영 (IMAGE_TAG 기본값 = 현재 HEAD SHA)
make k8s-apply-dev
# 또는 빌드+적용 일괄:
make k8s-redeploy-dev

# 특정 커밋 태그로 배포:
IMAGE_TAG=abc123... make k8s-apply-dev
```

Release publish로 빌드:

```bash
gh release create v0.2.0 --title "v0.2.0" --target main
```

로컬 `docker build` + `docker push`는 GHCR `write:packages` PAT가 필요하다. pull 전용 PAT(`registry-creds`)로는 push 불가 — **GHA 사용을 권장**.
