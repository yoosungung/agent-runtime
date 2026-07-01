# path-graph-rag-mcp — hybrid search Container MCP

path-graph `hybrid_search`(PG FTS + Qdrant RRF)를 **전용 OCI 이미지**로 제공한다. mcp-base pool·번들 zip 불필요.

## Build (GHA — 표준)

`:latest` 배포 없음. 태그 = **git SHA** (`ghcr.io/yoosungung/agent-runtime/path-graph-rag-mcp:<sha>`).

```bash
git push origin main
make build-images
make build-images-wait
```

워크플로: [`.github/workflows/build-images.yml`](../../../../.github/workflows/build-images.yml) matrix `path-graph-rag-mcp`. `yoosungung/path-graph` `main`의 `pipeline/`을 stage한 뒤 빌드한다.

### 로컬 Docker (선택)

```bash
# agents-runtime repo root
make sync-path-graph-docker
docker build -f deploy/examples/custom-image/path-graph-rag-mcp/Dockerfile \
  -t ghcr.io/yoosungung/agent-runtime/path-graph-rag-mcp:local .
```

## Register (Admin API)

`POST /api/admin/custom-images`:

```json
{
  "kind": "mcp",
  "name": "path-graph-rag",
  "version": "v1",
  "image_uri": "ghcr.io/yoosungung/agent-runtime/path-graph-rag-mcp:<git-sha>",
  "config": {
    "knowledge": {"requires_project": true},
    "path_graph_rag": {"default_top_k": 10}
  },
  "env": {
    "PATH_GRAPH_DSN": "postgresql://runtime:runtime@postgres.runtime.svc.cluster.local:5432/runtime",
    "QDRANT_URL": "http://qdrant.qdrant.svc.cluster.local:6333",
    "EMBEDDING_BASE_URL": "http://bge-m3-tei.llm-serving.svc.cluster.local:8080"
  }
}
```

`image_uri`는 GHA가 push한 **현재 배포 SHA**를 쓴다 (`make build-images` 후 `git rev-parse HEAD`). backend가 `mcp-pool-custom-{slug}` Deployment·Service를 생성한다. `runtime_pool`은 `mcp:custom:path-graph-rag-v1` 형태.

## Tool

| name | args (scoped) | response |
|------|---------------|----------|
| `search` | `query`, `tenant`, `project_id`, `project_slug`, optional `top_k` | `{results: [...]}` |

General agent에 `knowledge_project_ids` + 이 MCP server 연결. multi-project RRF는 agents-runtime `invoke_scoped_retrieval`이 담당.

## Env (pool env / infra)

| 변수 | 용도 |
|------|------|
| `PATH_GRAPH_DSN` | PG FTS |
| `QDRANT_URL`, `QDRANT_API_KEY` | vector search |
| `EMBEDDING_*` | query embed |

계약: [path-graph pipeline/DESIGN.md §Hybrid search](../../../../path-graph/pipeline/DESIGN.md)
