# agents-runtime

Runtime platform for **LLM agents** and **MCP servers** on Kubernetes. Base images run as long-lived pods; user code (agent graphs, MCP tools) is deployed *dynamically* at invoke time — similar to AWS Lambda — without rebuilding images.

Out of scope (lives in sibling repos / external infra):
- LLM serving (API / vLLM)
- RAG stack (DidimRAG, pgvector)
- OpenTelemetry collector / storage
- User-facing Chat UI

## Components

```
services/
  auth/            AuthN/AuthZ — /login (JWT issue), /verify (RBAC check)
  deploy-api/      Runtime meta read-only — /v1/resolve returns source_meta + user_meta
  agent-gateway/   Agent select-gateway (Phase 1) — auth → access → pod pick → proxy
  mcp-gateway/     MCP select-gateway (Phase 1)  — same pattern, internal grace period
  ext-authz/       Envoy HTTP ext_authz (Phase 2) — agent+mcp unified, path-based kind/grace

runtimes/
  agent-base/      Agent-Pool base image — RUNTIME_KIND ∈ {compiled_graph, adk, custom}
  mcp-base/        MCP-Pool base image   — RUNTIME_KIND ∈ {fastmcp, mcp_sdk, didim_rag, t2sql}

packages/
  common/          Shared lib: schemas, db, auth client, deploy client, loader, factory,
                   secrets, registry, scheduling, telemetry, logging, settings

backend/           Admin console BFF (FastAPI) — REST API for the SPA
frontend/          Admin console SPA (React + Vite + Tailwind)

deploy/k8s/        Kustomize base + overlays (dev / stage / prod)
```

Architecture diagram: [`agent-runtime.d2`](agent-runtime.d2) → rendered to `agent-runtime.png` via `make diagram`.

## Admin Console

A web UI (`/`) served by the backend BFF at the same origin as the API. Features:

| Page | Path | Access |
|---|---|---|
| Dashboard | `/` | Admin |
| Agents | `/agents` | Admin |
| MCP Servers | `/mcp-servers` | Admin |
| Users | `/users` | Admin |
| Audit Log | `/audit` | Admin |
| Chat | `/chat` | All authenticated |
| My Profile | `/me` | All authenticated |

**Key flows**
- Register a new agent/MCP bundle via ZIP upload (in-browser sha256, decompressed-size hint) or external URI (s3://, oci://)
- Verify bundle integrity (`POST /api/source-meta/{id}/verify` — sha256 recompute + signature recheck)
- Manage user accounts, reset passwords, grant/revoke access per agent or MCP server (bulk revoke)
- Audit log: every create/update/delete/retire/login event is recorded atomically alongside the operation
- Chat with any agent you have access to (streaming, session-based)

## Quickstart

### Prerequisites

- Python 3.12 (`uv` manages the venv — see `.python-version`)
- Node 20 (for frontend dev; the Docker build handles this automatically)
- A running Postgres instance (see `backend/migrations/0001_init.sql`)

### Install & run tests

```bash
uv sync --all-packages       # install all workspace packages in a single venv
make test                    # pytest (248 tests)
make typecheck               # mypy
make lint                    # ruff check
make fmt                     # ruff format
```

### Frontend dev

```bash
cd frontend
npm ci
npm run dev      # Vite dev server on :5173, proxies /api/* → localhost:8000
npm test         # vitest unit tests
npm run e2e      # Playwright smoke tests (requires a running backend, see E2E_ env vars)
```

### Run a single service locally

```bash
# Backend (admin console BFF)
uv run uvicorn backend.app:app --reload --port 8000

# Auth
uv run uvicorn auth.app:app --reload --port 8001

# Deploy API
uv run uvicorn deploy_api.app:app --reload --port 8002
```

### Build & deploy

```bash
make images            # build all Docker images (Kaniko jobs run in cluster, non-blocking)
make k8s-apply-dev     # apply dev overlay (namespace: runtime)
make db-migrate        # apply backend/migrations/0001_init.sql to dev Postgres
```

`make ...-image` submits a Kaniko `Job` and returns immediately. Tail progress with the printed `kubectl logs ... -f` hint, or `kubectl get jobs -n runtime`.

### First-run admin bootstrap

On startup the backend seeds an initial admin user **only if the `users` table is empty**. The password is read from `INITIAL_ADMIN_PASSWORD_FILE` (mounted Secret) or `INITIAL_ADMIN_PASSWORD` (env). Without one of these, bootstrap is skipped and login will return 401 for every credential.

```bash
# 1. create the Secret (one-time; pick your own password)
kubectl create secret generic initial-admin-password -n runtime \
  --from-literal=password=agent-admin-password

# 2. apply the dev overlay (the Secret is mounted by backend.yaml)
make k8s-apply-dev

# 3. backend logs should report:
#    INFO:backend.bootstrap:Bootstrap: created initial admin user 'admin' (id=1)
```

The seeded user is `admin` (override with `INITIAL_ADMIN_USERNAME`), `is_admin=true`, `must_change_password=true` — the SPA will force a password change on first login. The Secret is mounted with `optional: true`, so missing-secret in stage/prod doesn't crash the pod; rotate or remove it after the first admin has logged in.

## How dynamic deployment works

1. An operator registers a bundle via the admin console (ZIP upload or external URI).
2. The backend writes `source_meta` to Postgres: `{kind, name, version, runtime_pool, entrypoint, bundle_uri, checksum}`.
3. A user invokes an agent through the gateway.
4. The gateway verifies the JWT, checks `user_resource_access`, and calls deploy-api `/v1/resolve`.
5. Deploy-api returns `{source, user}` — the pool picks up the bundle, imports the entrypoint factory, and serves the request.
6. `factory(cfg, secrets)` receives a shallow-merged config: `source_meta.config` ← overridden by `user_meta.config`.

## Bundle signing (production)

Pools verify the SHA-256 checksum of every downloaded bundle. For stronger guarantees, enable signature verification so only bundles signed by your CI pipeline can be loaded.

### 1. Generate a key pair (once)

```bash
cosign generate-key-pair   # → cosign.key (private), cosign.pub (public)
```

Store `cosign.key` in CI secrets. Mount `cosign.pub` in pool pods via a Kubernetes Secret.

### 2. Sign in CI

```bash
cosign sign-blob --key cosign.key bundle.zip > bundle.zip.sig
```

### 3. Register via admin console

Upload the ZIP and `.sig` in the "ZIP Upload" tab, or set `bundle_uri` + `sig_uri` for external artifacts.

### 4. Enable verification on pool pods

```yaml
env:
  - name: BUNDLE_VERIFY_SIGNATURES
    value: "true"
  - name: BUNDLE_SIGNING_PUBLIC_KEY
    valueFrom:
      secretKeyRef:
        name: bundle-signing-pubkey
        key: cosign.pub
```

### Supported key types

| Type | How to generate |
|---|---|
| ECDSA P-256 | `cosign generate-key-pair` (default) |
| Ed25519 | `openssl genpkey -algorithm ed25519` |

If `sig_uri` is absent but `BUNDLE_VERIFY_SIGNATURES=true`, the pod rejects the bundle. Set `sig_uri` on every registered bundle before enabling the flag in production.

## Write ownership

All DB writes go through the admin backend. Runtime services are read-only:

| Table | Writer | Readers |
|---|---|---|
| `source_meta` | admin backend | deploy-api |
| `user_meta` | admin backend | deploy-api |
| `users` | admin backend | auth |
| `user_resource_access` | admin backend | auth |
| `refresh_tokens` | auth (exception) | auth |
| `audit_log` | admin backend (atomic) | admin backend |

When the admin backend changes a password or deactivates an account it calls `POST /admin/revoke-tokens` on the auth service to invalidate existing refresh tokens.

## Design documents

Each component has a detailed `DESIGN.md`:

- [Top-level architecture](DESIGN.md)
- [packages/common](packages/common/DESIGN.md)
- [services/auth](services/auth/DESIGN.md)
- [services/deploy-api](services/deploy-api/DESIGN.md)
- [services/agent-gateway](services/agent-gateway/DESIGN.md)
- [services/mcp-gateway](services/mcp-gateway/DESIGN.md)
- [services/ext-authz](services/ext-authz/DESIGN.md)
- [runtimes/agent-base](runtimes/agent-base/DESIGN.md)
- [runtimes/mcp-base](runtimes/mcp-base/DESIGN.md)
- [backend (admin BFF)](backend/DESIGN.md)
- [frontend (admin SPA)](frontend/DESIGN.md)
- [deploy/k8s](deploy/DESIGN.md)
