# Kubernetes deployment

Kustomize layout:

```
deploy/k8s/
  base/                 # shared definitions (namespace: runtime)
    namespace.yaml
    postgres.yaml
    redis.yaml
    auth.yaml
    deploy-api.yaml
    backend.yaml
    ext-authz.yaml
    envoy.yaml
    agent-pool-compiled-graph.yaml
    agent-pool-adk.yaml
    mcp-pool-fastmcp.yaml
    mcp-pool-mcp-sdk.yaml
    ingress.yaml        # prod/stage host: agents.didim365.app
    ...
  overlays/
    dev/                # GHCR images, agents.k8s-test Ingress, replicas=1, no KEDA
    stage/
    prod/
```

Apply:

```bash
make k8s-apply-dev
```

## Image registry

Images are built by GitHub Actions on **Release publish** (see `.github/workflows/build-images.yml`) and pushed to:

`ghcr.io/yoosungung/agent-runtime/<service>:latest` (+ commit SHA tag)

The dev overlay remaps base image names to GHCR. After a release:

```bash
make k8s-rollout-restart   # pull new :latest
```

For private GHCR packages, create a pull secret:

```bash
GITHUB_USER=yoosungung GITHUB_PAT=<token> make registry-secret
```

## Dev overlay differences

| Setting | dev | stage/prod (base) |
|---------|-----|-------------------|
| Ingress host | `agents.k8s-test` | `agents.didim365.app` |
| Image registry | GHCR (`ghcr.io/yoosungung/agent-runtime/...`) | base names (overlay-specific) |
| Replicas | 1 (all Deployments) | HPA/KEDA defaults |
| KEDA ScaledObject | removed | enabled |
| Postgres | direct (pgbouncer replicas=0) | via pgbouncer |
| `ENV` / `LOG_LEVEL` | dev / DEBUG | stage or prod / INFO |

## External vs internal URLs

| Purpose | URL |
|---------|-----|
| Browser / admin SPA / `/api/*` | `https://agents.k8s-test/` (dev) |
| External agent invoke | `https://agents.k8s-test/v1/agents/...` |
| Pod-to-pod MCP (`MCP_GATEWAY_URL`) | `http://envoy.runtime.svc.cluster.local:8080` |
| Backend chat invoke (`ENVOY_URL`) | same internal envoy |

`/v1/mcp/invoke-internal` is **not** on the public Ingress — agent pools call the in-cluster envoy Service directly.

Each pool is a separate `Deployment` reusing the same base image with a different `RUNTIME_KIND` env.
