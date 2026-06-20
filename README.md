# agents-runtime

저장소 방문자·기여자용 소개와 로컬 quickstart. 계약·내부 설계는 [ARCHITECTURE.md](ARCHITECTURE.md)와 각 컴포넌트 `DESIGN.md`를 본다. 에이전트·기여 워크플로는 [AGENTS.md](AGENTS.md).

Runtime platform for **LLM agents** and **MCP servers** on Kubernetes. Base images run as long-lived pods; user code (agent graphs, MCP tools) is deployed *dynamically* at invoke time — similar to AWS Lambda — without rebuilding images.

Out of scope (lives in sibling repos / external infra):
- LLM serving (API / vLLM)
- RAG stack (DidimRAG, pgvector)
- OpenTelemetry collector / storage
- User-facing Chat UI (admin console in this repo is the exception)

Architecture contracts and cross-component schemas: [ARCHITECTURE.md](ARCHITECTURE.md). Roadmap: [ROADMAP.md](ROADMAP.md).

Architecture diagram: [`agent-runtime.d2`](agent-runtime.d2) → `make diagram` renders `agent-runtime.png`.

## Quickstart

### Prerequisites

- Python 3.12 (`uv` manages the venv — see `.python-version`)
- Node 20 (for frontend dev; Docker build handles this automatically)
- A running Postgres instance (see `backend/migrations/0001_init.sql`)

### Install & run tests

```bash
uv sync --all-packages
make test
make typecheck
make lint
make fmt
```

### Frontend dev

```bash
cd frontend
npm ci
npm run dev      # Vite :5173, proxies /api/* → localhost:8000
npm test
npm run e2e      # Playwright (requires running backend)
```

### Run a single service locally

```bash
uv run uvicorn backend.app:app --reload --port 8000   # admin BFF
uv run uvicorn auth.app:app --reload --port 8001
uv run uvicorn deploy_api.app:app --reload --port 8002
```

### Build & deploy

Images are built by **GitHub Actions** on **GitHub Release** publish (`.github/workflows/build-images.yml`). Tags: `:latest` and commit SHA on `ghcr.io/yoosungung/agent-runtime/<service>`.

```bash
gh release create v0.1.0 --title "dev 0.1.0" --target main
make k8s-apply-dev
make db-migrate-all
make k8s-rollout-restart
```

Private GHCR: `GITHUB_USER=... GITHUB_PAT=... make registry-secret`

K8s 배포·Ingress·bootstrap 상세는 [deploy/DESIGN.md](deploy/DESIGN.md) 참조.

## Bundles & examples

| 목적 | README |
|------|--------|
| 운영 번들 (email 등) | [bundles/README.md](bundles/README.md) |
| 학습용 예제 번들 | [deploy/examples/agent-base/README.md](deploy/examples/agent-base/README.md), [deploy/examples/mcp-base/README.md](deploy/examples/mcp-base/README.md) |
| 클러스터 e2e 스모크 | [deploy/examples/tests/e2e/README.md](deploy/examples/tests/e2e/README.md) |

배포 절차 정본: [deploy/examples/mcp-base/README.md](deploy/examples/mcp-base/README.md) (zip → upload → `source_meta` 등록).

## Component design documents

| Component | DESIGN.md |
|---|---|
| Cross-component contracts | [ARCHITECTURE.md](ARCHITECTURE.md) |
| packages/common | [packages/common/DESIGN.md](packages/common/DESIGN.md) |
| services/auth | [services/auth/DESIGN.md](services/auth/DESIGN.md) |
| services/deploy-api | [services/deploy-api/DESIGN.md](services/deploy-api/DESIGN.md) |
| services/ext-authz | [services/ext-authz/DESIGN.md](services/ext-authz/DESIGN.md) |
| runtimes/agent-base | [runtimes/agent-base/DESIGN.md](runtimes/agent-base/DESIGN.md) |
| runtimes/mcp-base | [runtimes/mcp-base/DESIGN.md](runtimes/mcp-base/DESIGN.md) |
| backend (admin BFF) | [backend/DESIGN.md](backend/DESIGN.md) |
| frontend (admin SPA) | [frontend/DESIGN.md](frontend/DESIGN.md) |
| deploy/k8s | [deploy/DESIGN.md](deploy/DESIGN.md) |
