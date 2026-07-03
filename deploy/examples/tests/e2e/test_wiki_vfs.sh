#!/usr/bin/env bash
# PG-3 — Wiki VFS cluster E2E (general agent + PG vfs_wiki_files mount).
#
# Prerequisites:
#   - dev cluster: agents-runtime k8s applied, agent-pool-compiled-graph has VFS_DSN
#   - admin login password (INITIAL_ADMIN_PASSWORD secret)
#   - utility-server MCP registered (run ./run.sh once, or this script registers it)
#
# Usage:
#   ADMIN_PASSWORD='...' ./test_wiki_vfs.sh
#   PROJECT_ID='...' PROJECT_SLUG='default' TENANT='didim' ./test_wiki_vfs.sh

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=lib.sh
source ./lib.sh

: "${TENANT:=didim}"
: "${PROJECT_ID:=}"
: "${PROJECT_SLUG:=default}"
: "${AGENT_NAME:=wiki-vfs-e2e}"
: "${AGENT_VERSION:=v1}"
: "${MCP_SERVER:=utility-server}"
: "${WIKI_MARKER:=PG-3 Wiki VFS E2E fixture}"
: "${WIKI_PAGE:=pg3-e2e-page.md}"
: "${LLM_MODEL:=openai:nmilosev/gemma-4-12B-it-quantized.w4a16}"

E2E_PY="${REPO_ROOT}/../path-graph/.venv/bin/python3"
if [[ ! -x "$E2E_PY" ]]; then
  E2E_PY="$(command -v python3)"
fi

require_kubectl() {
  command -v kubectl >/dev/null 2>&1 || fail "kubectl required"
}

assert_agent_pool_vfs_env() {
  log "check agent-pool VFS_DSN"
  local dsn
  dsn=$(kubectl -n runtime exec deploy/agent-pool-compiled-graph -- printenv VFS_DSN 2>/dev/null \
    || true)
  [[ -n "$dsn" ]] || fail "VFS_DSN unset on agent-pool — apply k8s + rollout restart"
  ok "agent-pool VFS_DSN configured"
}

seed_wiki_fixture() {
  log "seed wiki fixture in vfs_wiki_files (tenant=$TENANT project=$PROJECT_ID)"
  local slug="${WIKI_PAGE%.md}"
  kubectl exec -n runtime postgres-0 -- psql -U runtime -d runtime -v ON_ERROR_STOP=1 <<SQL
INSERT INTO vfs_wiki_files (
  tenant, project_id, path, parent_path, name, is_dir, size, content, encoding
) VALUES (
  '${TENANT}',
  '${PROJECT_ID}'::uuid,
  '/${slug}.md',
  '/',
  '${slug}.md',
  FALSE,
  length('# ${WIKI_MARKER}\n\nCluster E2E wiki mount verification.\n'),
  convert_to('# ${WIKI_MARKER}\n\nCluster E2E wiki mount verification.\n', 'UTF8'),
  'utf-8'
)
ON CONFLICT (tenant, project_id, path) DO UPDATE SET
  content = EXCLUDED.content,
  size = EXCLUDED.size,
  modified_at = now();
SQL
  ok "wiki vfs row seeded"
}

resolve_project_id() {
  if [[ -n "$PROJECT_ID" ]]; then
    return 0
  fi
  log "resolve project_id for tenant=$TENANT slug=$PROJECT_SLUG"
  PROJECT_ID=$(kubectl exec -n runtime postgres-0 -- psql -U runtime -d runtime -tAc \
    "SELECT id FROM path_graph.projects WHERE tenant='${TENANT}' AND slug='${PROJECT_SLUG}' LIMIT 1;" \
    | tr -d '[:space:]')
  [[ -n "$PROJECT_ID" ]] || fail "no path_graph.projects row for tenant=$TENANT slug=$PROJECT_SLUG"
  ok "project_id=$PROJECT_ID"
}

export REPO_ROOT
require_kubectl
assert_agent_pool_vfs_env
login
load_state
resolve_project_id
seed_wiki_fixture
  local zipf="$WORK_DIR/utility-server.zip"
  local dir="$EXAMPLES_DIR/mcp-base/fastmcp_bundle"
  if admin_curl GET "/api/source-meta?kind=mcp&name=$MCP_SERVER" \
    | jq -e --arg n "$MCP_SERVER" '.items[] | select(.name==$n)' >/dev/null 2>&1; then
    ok "MCP $MCP_SERVER already registered"
    return 0
  fi
  log "register MCP $MCP_SERVER (minimal fastmcp bundle)"
  build_bundle_zip "$dir" "$zipf"
  upload_bundle "$zipf" mcp "$MCP_SERVER" v1 mcp:fastmcp app:build_server \
    '{"fastmcp":{"strict_input_validation":false,"mask_error_details":false}}' >/dev/null
  ok "MCP $MCP_SERVER registered"
}

ensure_general_agent() {
  log "create general agent $AGENT_NAME@$AGENT_VERSION"
  local body resp
  body=$(jq -nc \
    --arg name "$AGENT_NAME" \
    --arg version "$AGENT_VERSION" \
    --arg pid "$PROJECT_ID" \
    --arg mcp "$MCP_SERVER" \
    --arg model "$LLM_MODEL" \
    --arg prompt "You are a filesystem assistant. Always use ls/read tools when asked about files." \
    '{
      name: $name,
      version: $version,
      system_prompt: $prompt,
      mcp_servers: [$mcp],
      knowledge_project_ids: [$pid],
      config: { langgraph: { model: $model, checkpointer: "none" } }
    }')
  if resp=$(admin_curl POST /api/source-meta/general \
      -H 'Content-Type: application/json' \
      -d "$body" 2>&1); then
    ok "general agent created"
    return 0
  fi
  if grep -q 'already exists' <<<"$resp"; then
    ok "general agent already exists"
    return 0
  fi
  fail "create general agent failed: $resp"
}

verify_binding() {
  log "GET /api/me/knowledge-projects/$PROJECT_ID/binding"
  local resp mount
  resp=$(admin_curl GET "/api/me/knowledge-projects/$PROJECT_ID/binding")
  mount=$(jq -r .wiki.vfs_mount <<<"$resp")
  [[ "$mount" == "/wiki/${PROJECT_SLUG}/" ]] \
    || fail "unexpected vfs_mount=$mount (expected /wiki/${PROJECT_SLUG}/)"
  ok "binding wiki mount=$mount"
}

invoke_and_assert_wiki_read() {
  local vfs_path="/wiki/${PROJECT_SLUG}/"
  local prompt
  prompt=$(
    cat <<EOF
Use your filesystem tools only.
1) Run ls on path ${vfs_path}
2) Read file ${vfs_path}${WIKI_PAGE}
Reply with ONLY the first line of that file (the line starting with #), nothing else.
EOF
  )
  log "invoke $AGENT_NAME — VFS read at $vfs_path"
  local out text
  out=$(invoke_agent "$AGENT_NAME" "$AGENT_VERSION" \
    "$(jq -nc --arg c "$prompt" '{messages:[{role:"user",content:$c}]}')" \
    ) || fail "invoke failed"
  text=$(jq -r '
    if .output.messages then
      [.output.messages[] | select(.type=="ai" or .role=="assistant") | .content] | last // empty
    elif .output then .output | tostring
    else . | tostring end' <<<"$out" 2>/dev/null || echo "$out")
  if ! grep -Fq "$WIKI_MARKER" <<<"$text"; then
    echo "$out" | jq . 2>/dev/null || echo "$out"
    fail "response missing wiki marker '$WIKI_MARKER'"
  fi
  ok "invoke returned wiki content: $(echo "$text" | head -1)"
}

export REPO_ROOT
require_kubectl
assert_agent_pool_vfs_env
login
load_state
resolve_project_id
seed_wiki_fixture
ensure_utility_mcp
grant_access mcp "$MCP_SERVER"
login
load_state
ensure_general_agent
grant_access agent "$AGENT_NAME"
login
load_state
verify_binding
invoke_and_assert_wiki_read
ok "PG-3 Wiki VFS E2E passed"
