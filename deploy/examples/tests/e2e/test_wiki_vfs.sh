#!/usr/bin/env bash
# PG-3 — Wiki VFS cluster E2E (general agent + S3 wiki prefix mount).
#
# Prerequisites:
#   - dev cluster: agents-runtime k8s applied, agent-pool-compiled-graph has WIKI_S3_BUCKET + s3-creds
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

assert_agent_pool_wiki_env() {
  log "check agent-pool WIKI_S3_BUCKET + S3_ENDPOINT_URL"
  local bucket endpoint
  bucket=$(kubectl -n runtime exec deploy/agent-pool-compiled-graph -- printenv WIKI_S3_BUCKET 2>/dev/null \
    || true)
  endpoint=$(kubectl -n runtime exec deploy/agent-pool-compiled-graph -- printenv S3_ENDPOINT_URL 2>/dev/null \
    || true)
  [[ -n "$bucket" ]] || fail "WIKI_S3_BUCKET unset on agent-pool — apply k8s + rollout restart"
  [[ -n "$endpoint" ]] || fail "S3_ENDPOINT_URL unset on agent-pool — ensure s3-creds envFrom"
  ok "agent-pool wiki env: bucket=$bucket endpoint=$endpoint"
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

upload_wiki_fixture() {
  log "upload wiki fixture to S3 (tenant=$TENANT project=$PROJECT_ID)"
  eval "$(
    kubectl -n runtime get secret s3-creds -o json \
      | python3 -c 'import json,sys,base64; d=json.load(sys.stdin)["data"];
for k,v in d.items(): print(f"export {k}={base64.b64decode(v).decode()!r}")'
  )"
  local pf_pid=""
  if [[ "${S3_ENDPOINT_URL:-}" == *".svc"* ]]; then
    log "port-forward runtime/garage-s3 :3900 for local upload"
    kubectl -n runtime port-forward svc/garage-s3 3900:3900 >/dev/null 2>&1 &
    pf_pid=$!
    sleep 2
    export S3_ENDPOINT_URL=http://127.0.0.1:3900
  fi
  export REPO_ROOT TENANT PROJECT_ID WIKI_PAGE WIKI_MARKER
  if ! "$E2E_PY" <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["REPO_ROOT"]) / "../path-graph/pipeline/src"))

import boto3
from path_graph.contracts.s3_keys import s3_key_wiki

tenant = os.environ["TENANT"]
project_id = os.environ["PROJECT_ID"]
page = os.environ["WIKI_PAGE"]
marker = os.environ["WIKI_MARKER"]
key = s3_key_wiki(tenant, project_id, page.removesuffix(".md"))
body = f"# {marker}\n\nCluster E2E wiki mount verification.\n"

client = boto3.client(
    "s3",
    endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
    aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID") or None,
    aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY") or None,
    region_name=os.environ.get("S3_REGION") or "us-east-1",
)
bucket = os.environ["S3_BUCKET"]
client.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
print(key)
PY
  then
    [[ -n "$pf_pid" ]] && kill "$pf_pid" 2>/dev/null || true
    fail "wiki fixture upload failed"
  fi
  [[ -n "$pf_pid" ]] && kill "$pf_pid" 2>/dev/null || true
  ok "wiki object uploaded"
}

ensure_utility_mcp() {
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
assert_agent_pool_wiki_env
login
load_state
resolve_project_id
upload_wiki_fixture
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
