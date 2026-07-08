# Telepresence 로컬 디버그 가이드

`runtimes/*` 코드(agent-base, mcp-base, hermes-base)를 **dev k8s 클러스터(*`*runtime` **namespace)와 연결된 상태**에서 Mac에서 디버깅할 때 쓰는 방법.

> pool runtime — 클러스터 pod가 받는 트래픽을 로컬 프로세스로 넘겨 브레이크포인트로 디버깅.

---

## 1. 사전 준비

### 1.1 도구

```bash
# Telepresence CLI (v2.29+ 권장)
telepresence version

# kubectl — dev cluster context 연결
kubectl config current-context
kubectl -n runtime get deploy agent-pool-compiled-graph

# Python 워크스pace
make sync
```

- 클러스터에 **Telepresence Traffic Manager**가 설치·동작해야 한다. `telepresence connect` 시 Traffic Manager에 연결되는지 확인.
- `telepresence list`에서 대상 deployment가 `ready to engage` 또는 intercept 가능 상태인지 확인.



### 1.2 Cursor MCP (선택)

에이전트가 CLI로 Telepresence를 다루게 하려면:

```bash
cd /path/to/agents-runtime
telepresence mcp cursor enable --workspace
```

설정은 `[.cursor/mcp.json](../.cursor/mcp.json)`의 `telepresence` 서버(`telepresence mcp start`). 제거: `telepresence mcp cursor disable --workspace`.

### 1.3 로컬 포트 맵 (pool)


| runtime_kind     | Deployment / Service        | 로컬 디버그 포트 | pod 포트 |
| ---------------- | --------------------------- | --------- | ------ |
| `compiled_graph` | `agent-pool-compiled-graph` | **8091**  | 8080   |
| `adk`            | `agent-pool-adk`            | 8092      | 8080   |
| `hermes`         | `agent-pool-hermes`         | 8095      | 8080   |
| `fastmcp`        | `mcp-pool-fastmcp`          | 8093      | 8080   |
| `mcp_sdk`        | `mcp-pool-mcp-sdk`          | 8094      | 8080   |


로컬 포트는 pool마다 겹치지 않게 고정. Telepresence intercept는 `로컬:pod` → 예: `8091:8080`.

---



## 2. VS Code / Cursor 디버그 (권장)



### 2.1 agent-base (`compiled_graph`) — Telepresence 연동 완료

1. Run and Debug → `Debug: agent-pool (compiled_graph)` 선택
2. F5

자동 실행 순서:

1. `telepresence connect -n runtime`
2. `telepresence intercept agent-pool-compiled-graph -p 8091:8080 --env-file .env.telepresence-compiled_graph`
3. debugpy + uvicorn `agent_base.app:app --port 8091` (로컬 `runtimes/agent-base/src` 코드)
4. 디버그 종료 → `telepresence leave agent-pool-compiled-graph`

관련 파일:


| 파일                                                                        | 역할                                        |
| ------------------------------------------------------------------------- | ----------------------------------------- |
| `[.vscode/launch.json](../.vscode/launch.json)`                           | 디버그 설정, `envFile`, pre/post task          |
| `[.vscode/tasks.json](../.vscode/tasks.json)`                             | `telepresence-pool-compiled_graph` 등 task |
| `[scripts/telepresence-pool-dev.sh](../scripts/telepresence-pool-dev.sh)` | connect / intercept / leave               |


`launch.json`에서 로컬만 덮어쓰는 env:

- `PYTHONPATH` → `runtimes/agent-base/src` (자기 코드)
- `BUNDLE_CACHE_DIR` → `.wire-dev/agent-bundles` (로컬 번들 캐시)
- `POD_PORT` → 로컬 uvicorn 포트(8091)

나머지(`VFS_DSN`, `REDIS_URL`, `MCP_GATEWAY_URL`, `CHECKPOINTER_DSN` 등)는 pod env에서 가져온다.

### 2.2 다른 pool (adk, hermes, mcp)

모든 pool 디버그 설정은 `compiled_graph`와 동일한 Telepresence 패턴을 사용한다.

| Launch 이름 | runtime_kind | envFile | 로컬 포트 |
| ----------- | ------------ | ------- | ------- |
| `Debug: agent-pool (compiled_graph)` | `compiled_graph` | `.env.telepresence-compiled_graph` | 8091 |
| `Debug: agent-pool (adk)` | `adk` | `.env.telepresence-adk` | 8092 |
| `Debug: agent-pool (Hermes)` | `hermes` | `.env.telepresence-hermes` | 8095 |
| `Debug: mcp-pool (fastmcp)` | `fastmcp` | `.env.telepresence-fastmcp` | 8093 |
| `Debug: mcp-pool (mcp_sdk)` | `mcp_sdk` | `.env.telepresence-mcp_sdk` | 8094 |

### 2.3 core 서비스 (auth, deploy-api, ext-authz, backend)

pool과 동일하게 F5 시 `telepresence connect` → intercept → debugpy → 종료 시 leave.

| Launch 이름 | k8s Service | envFile | 로컬 포트 |
| ----------- | ----------- | ------- | ------- |
| `Debug: auth` | `auth` | `.env.telepresence-auth` | 8081 |
| `Debug: deploy-api` | `deploy-api` | `.env.telepresence-deploy-api` | 8082 |
| `Debug: ext-authz` | `ext-authz` | `.env.telepresence-ext-authz` | 8083 |
| `Debug: backend` | `backend` | `.env.telepresence-backend` | 8000 |

스크립트: [`scripts/telepresence-service-dev.sh`](../scripts/telepresence-service-dev.sh), task: `telepresence-service-*` / `telepresence-leave-*`.

---



## 3. CLI 수동 실행

```bash
# 1) 연결
telepresence connect -n runtime

# 2) intercept + pod env 덤프
./scripts/telepresence-pool-dev.sh intercept compiled_graph
# → .env.telepresence-compiled_graph 생성

# 3) 로컬 pool 기동 (다른 터미널)
export $(grep -v '^#' .env.telepresence-compiled_graph | xargs)  # 참고용; VS Code는 envFile 사용
PYTHONPATH=runtimes/agent-base/src \
  SERVICE_NAME=agent-pool-compiled-graph \
  RUNTIME_KIND=compiled_graph \
  POD_PORT=8091 \
  BUNDLE_CACHE_DIR=.wire-dev/agent-bundles \
  uv run uvicorn agent_base.app:app --port 8091

# 4) 종료
./scripts/telepresence-pool-dev.sh leave compiled_graph
# 또는
telepresence leave agent-pool-compiled-graph -n runtime
```

상태 확인:

```bash
telepresence status
telepresence list
telepresence mcp cursor list --config-path .cursor/mcp.json   # MCP 설정 확인
```

---



## 4. `runtimes/*` 작업 시 알아둘 것



### 4.1 코드 위치


| 경로                                    | 역할                     | 디버그 launch 이름                                 |
| ------------------------------------- | ---------------------- | --------------------------------------------- |
| `runtimes/agent-base/src/agent_base/` | LangGraph/ADK pool     | `Debug: agent-pool (compiled_graph)`, `(adk)` |
| `runtimes/hermes-base/src/hermes_base/` | Hermes profile pool  | `Debug: agent-pool (Hermes)`                  |
| `runtimes/mcp-base/src/mcp_base/`     | FastMCP / MCP SDK pool | `Debug: mcp-pool (fastmcp)`, `(mcp_sdk)`      |


공용 로직은 `packages/common/src/runtime_common/` — pool과 함께 import되므로 breakpoint 가능.

### 4.2 invoke 흐름 (agent-base)

1. 클라이언트 → Envoy `/v1/agents/invoke`
2. ext-authz → pool scheduler (Redis registry)
3. **intercept 시** → `agent-pool-compiled-graph:8080` 트래픽이 Mac `:8091`로
4. 로컬 `POST /invoke` → `DeployApiClient.resolve` → `BundleLoader` → runner

번들 zip은 deploy-api가 제공. 로컬 캐시 디렉터리(`BUNDLE_CACHE_DIR`)에 저장된다. cluster S3/Garage에 직접 붙는 env는 pod env에 포함.

### 4.3 packages/common 변경

pool만 Telepresence로 띄워도 `runtime_common` 수정은 hot reload 없이 **디버거 재시작** 필요. `--reload`는 launch.json pool 설정에 없음(debugpy 안정성).

### 4.4 테스트

단위/통합 테스트는 클러스터 없이:

```bash
make test                                    # 전체
uv run pytest runtimes/agent-base/tests/     # pool 단위
```

Telepresence 디버그는 E2E에 가깝다 — 실제 tenant/agent invoke, MCP gateway, Postgres checkpointer 등 cluster infra 사용.

---



## 5. 트러블슈팅


| 증상                                                                      | 조치                                                                                             |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `Cluster configuration changed, please quit telepresence and reconnect` | `telepresence quit -s` 후 재시도                                                                   |
| intercept 실패 / Traffic Manager Not connected                            | Traffic Manager 설치·RBAC 확인, `telepresence connect -n runtime`                                  |
| `ready to engage (traffic-agent not yet installed)`                     | 첫 intercept 시 agent 자동 설치 대기; 실패 시 cluster admin에 Traffic Manager/agent 확인                     |
| 로컬 포트 in use                                                            | `lsof -i :8091`로 프로세스 종료 또는 `pool_local_port` 변경(스크립트 + launch.json + uvicorn args 일괄)         |
| env 파일 없음                                                               | intercept를 먼저 실행 (`preLaunchTask` 또는 `telepresence-pool-dev.sh intercept`)                     |
| DB 연결 실패                                                                | `telepresence connect` 상태인지 확인. wire-dev port-forward(127.0.0.1)와 **혼용하지 말 것** — DSN 호스트가 다름   |
| 디버그 종료 후 트래픽 이상                                                         | `telepresence leave <service> -n runtime` 또는 `./scripts/telepresence-pool-dev.sh leave <kind>` |


---



## 6. 관련 문서

- [runtimes/agent-base/DESIGN.md](../runtimes/agent-base/DESIGN.md) — pool 동작, env, `/invoke` contract
- [runtimes/mcp-base/DESIGN.md](../runtimes/mcp-base/DESIGN.md) — MCP pool
- [scripts/wire-dev.sh](../scripts/wire-dev.sh) — port-forward 기반 대안
- [Telepresence intercept CLI](https://telepresence.io/docs/reference/cli/telepresence_intercept)
- [Telepresence MCP](https://telepresence.io/docs/reference/cli/telepresence_mcp)

---



## 별첨: wire-dev vs Telepresence


|             | wire-dev `pool-isolate`                     | Telepresence `intercept`                                             |
| ----------- | ------------------------------------------- | -------------------------------------------------------------------- |
| 클러스터 pool   | replica **0**으로 scale down                  | replica 유지, 트래픽만 로컬로                                                 |
| DB/Redis 접근 | localhost port-forward (`127.0.0.1:5432` 등) | `telepresence connect` 후 cluster DNS (`*.runtime.svc.cluster.local`) |
| env         | `.env.dev.local` (`wire-dev.sh env`)        | pod env 스냅샷 `.env.telepresence-<kind>`                               |
| 트래픽 경로      | 수동 `POST http://127.0.0.1:<port>/invoke` 위주 | Envoy → pool Service 트래픽이 로컬로                                        |
| VS Code     | `wire-pool-*` / `wire-dev-up` preLaunchTask                 | `telepresence-pool-*` / `telepresence-service-*` preLaunchTask |


**언제 Telepresence?** pool 코드(`runtimes/agent-base`, `runtimes/mcp-base`)를 수정하고 **실제 클러스터 invoke 경로**(Envoy → ext-authz → pool)로 검증할 때.

**언제 wire-dev?** pool을 cluster와 분리해 localhost만 두고 빠르게 돌리거나, backend/auth와 함께 port-forward 기반으로 작업할 때.