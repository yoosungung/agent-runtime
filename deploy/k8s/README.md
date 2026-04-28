# Kubernetes deployment

Kustomize layout:

```
deploy/k8s/
  base/                 # namespace-agnostic definitions
    namespace.yaml
    postgres.yaml       # Postgres StatefulSet for source_meta (infra pgvector lives elsewhere)
    auth.yaml
    deploy-api.yaml
    agent-gateway.yaml
    mcp-gateway.yaml
    agent-pool-compiled-graph.yaml
    agent-pool-adk.yaml
    agent-pool-custom.yaml
    mcp-pool-fastmcp.yaml
    mcp-pool-mcp-sdk.yaml
    mcp-pool-didim-rag.yaml
    mcp-pool-t2sql.yaml
    kustomization.yaml
  overlays/
    dev/                # local / kind / minikube
    stage/
    prod/
```

Apply:

```bash
kubectl apply -k deploy/k8s/overlays/dev
```

Each pool is a separate `Deployment` that reuses the same base image but sets
`RUNTIME_KIND` to the kind it hosts. Horizontal scale is per-pool.
