#!/usr/bin/env bash
# End-to-end smoke test against the dev cluster Ingress (https://agents.didim365.app).
#
# Flow:
#   1. login as admin (cookies + csrf)
#   2. zip + register the 4 example bundles via /api/source-meta/bundle.
#      LLM API keys + Naver creds are pulled from env and baked into
#      source_meta.config so each pool can resolve them at factory time.
#   3. upsert user_meta for the 2 agents (sanity check that merge path works)
#   4. grant user_resource_access on all 4 (kind, name) pairs to admin
#   5. invoke both agents:
#        - adk asks for arithmetic → LLM is expected to call the local
#          `calculate` tool
#        - langgraph (DeepAgent) asks a research question → LLM may call
#          MCP-routed `naver_search` / `fetch_url`
#
# Required env:
#   ADMIN_PASSWORD         — admin BFF password
#
# Optional env (without these, the corresponding step degrades gracefully —
# registration + resolve + factory build still pass; the LLM call may 5xx):
#   OPENAI_API_KEY         — OpenAI key (used by both agents in this run)
#   OPENAI_MODEL           — default "openai:gpt-4o-mini"
#   ANTHROPIC_API_KEY      — Claude key (alternative for the DeepAgent)
#   GOOGLE_API_KEY         — Gemini key (alternative for the ADK agent)
#   NAVER_CLIENT_ID        — Naver Search app client id
#   NAVER_CLIENT_SECRET    — Naver Search app client secret

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=lib.sh
source ./lib.sh

OPENAI_MODEL="${OPENAI_MODEL:-openai:gpt-4o-mini}"

# ---------------------------------------------------------------------------
# Bundle catalog: dir → identifier triple + entrypoint.
#
# search-server (mcp_sdk)  is the MCP target both agent bundles default to.
# utility-server (fastmcp) is registered to exercise the mcp:fastmcp pool
# independently — agents do NOT call it in this smoke test.
# ---------------------------------------------------------------------------
declare -a BUNDLES=(
  # dir|kind|name|version|runtime_pool|entrypoint
  "$EXAMPLES_DIR/agent-base/compiled_graph_bundle|agent|research-orchestrator|v1|agent:compiled_graph|app:build_agent"
  "$EXAMPLES_DIR/agent-base/adk_bundle|agent|research-math-agent|v1|agent:adk|app:build_agent"
  "$EXAMPLES_DIR/mcp-base/fastmcp_bundle|mcp|utility-server|v1|mcp:fastmcp|app:build_server"
  "$EXAMPLES_DIR/mcp-base/mcp_sdk_bundle|mcp|search-server|v1|mcp:mcp_sdk|app:build_server"
)

# ---------------------------------------------------------------------------
# Per-bundle source_meta.config — built fresh from env on every run so
# secrets never leak into git. Empty values are dropped from the JSON
# entirely; the factories use cfg.get(...) with sensible fallbacks.
# ---------------------------------------------------------------------------
make_source_config() {
  local name="$1"
  case "$name" in
    research-orchestrator)
      jq -nc \
        --arg model "$OPENAI_MODEL" \
        --arg mcp "search-server" \
        --arg openai "${OPENAI_API_KEY:-}" \
        --arg anthropic "${ANTHROPIC_API_KEY:-}" \
        '{
          langgraph: {model: $model, checkpointer: "none"},
          mcp_server: $mcp
        }
        + (if $openai    == "" then {} else {openai_api_key: $openai}      end)
        + (if $anthropic == "" then {} else {anthropic_api_key: $anthropic} end)'
      ;;
    research-math-agent)
      jq -nc \
        --arg model "$OPENAI_MODEL" \
        --arg mcp "search-server" \
        --arg openai "${OPENAI_API_KEY:-}" \
        --arg google "${GOOGLE_API_KEY:-}" \
        '{
          adk: {model: $model, temperature: 0.0, max_output_tokens: 1024},
          mcp_server: $mcp
        }
        + (if $openai == "" then {} else {openai_api_key: $openai} end)
        + (if $google == "" then {} else {google_api_key: $google} end)'
      ;;
    utility-server)
      jq -nc '{fastmcp: {strict_input_validation: false, mask_error_details: false}}'
      ;;
    search-server)
      jq -nc \
        --arg id "${NAVER_CLIENT_ID:-}" \
        --arg sec "${NAVER_CLIENT_SECRET:-}" \
        '{mcp: {mask_error_details: false}}
          + (if ($id == "" or $sec == "") then {}
             else {naver: {client_id: $id, client_secret: $sec}} end)'
      ;;
    *)
      echo '{}'
      ;;
  esac
}

# ---------------------------------------------------------------------------
# Step 1 — login
# ---------------------------------------------------------------------------
login
load_state

# Warn about missing optional secrets so the operator knows what to expect.
[ -n "${OPENAI_API_KEY:-}"     ] || log "  (warn) OPENAI_API_KEY unset — both agents will 5xx at LLM call (unless ANTHROPIC_API_KEY/GOOGLE_API_KEY supplied)"
[ -n "${NAVER_CLIENT_ID:-}"    ] || log "  (warn) NAVER_CLIENT_ID unset — naver_search MCP tool will RuntimeError"
[ -n "${NAVER_CLIENT_SECRET:-}"] || log "  (warn) NAVER_CLIENT_SECRET unset — naver_search MCP tool will RuntimeError"

# ---------------------------------------------------------------------------
# Step 2 — register bundles. Captures source_meta.id per (kind, name) into a
# parallel indexed array (entries shaped "kind:name=sid") so this runs on
# macOS system bash 3.2 (no `declare -A`).
# ---------------------------------------------------------------------------
SOURCE_ENTRIES=()

lookup_sid() {
  local want="$1" e
  for e in "${SOURCE_ENTRIES[@]}"; do
    if [ "${e%%=*}" = "$want" ]; then
      echo "${e#*=}"
      return 0
    fi
  done
  return 1
}

for entry in "${BUNDLES[@]}"; do
  IFS='|' read -r dir kind name version pool ep <<<"$entry"
  zipf="$WORK_DIR/${kind}_${name}_${version}.zip"
  log "zip   $kind/$name@$version  ($(basename "$dir"))"
  build_bundle_zip "$dir" "$zipf"
  cfg="$(make_source_config "$name")"
  log "upload $kind/$name@$version → $pool / $ep"
  sid=$(upload_bundle "$zipf" "$kind" "$name" "$version" "$pool" "$ep" "$cfg")
  [ -n "$sid" ] || fail "no source_meta_id returned for $kind/$name"
  SOURCE_ENTRIES+=("$kind:$name=$sid")
  ok "  source_meta.id=$sid"
done

# ---------------------------------------------------------------------------
# Step 3 — upsert user_meta for the 2 agents. Override `mcp_server` (same
# value as source default) just to exercise the merge path.
# ---------------------------------------------------------------------------
USER_OVERRIDE='{"mcp_server":"search-server"}'

for key in "agent:research-orchestrator" "agent:research-math-agent"; do
  sid=$(lookup_sid "$key") || fail "no source_meta id captured for $key"
  log "user_meta upsert  source_meta_id=$sid principal=$PRINCIPAL_SUB"
  upsert_user_meta "$sid" "$PRINCIPAL_SUB" "$USER_OVERRIDE"
  ok "  user_meta upserted"
done

# ---------------------------------------------------------------------------
# Step 4 — grant access on all 4 (kind, name) pairs to the admin user.
# Backend's grant_access calls auth's POST /v1/admin/invalidate-access after
# each commit so freshly granted rows are visible to /v1/agents/invoke
# immediately (no TTL wait).
# ---------------------------------------------------------------------------
for entry in "${SOURCE_ENTRIES[@]}"; do
  key="${entry%%=*}"
  kind="${key%%:*}"; name="${key#*:}"
  log "grant user_resource_access  user_id=$USER_ID  $kind/$name"
  grant_access "$kind" "$name"
  ok "  granted"
done

# ---------------------------------------------------------------------------
# Step 5 — invoke both agents.
#   ADK            : input.text → google.genai Content (see agent_base.runner._adk_content)
#   compiled_graph : DeepAgents expects {"messages": [{"role":"user","content":...}]}
# ---------------------------------------------------------------------------
log "invoke agent: research-math-agent  (expects calculate tool call)"
out_adk=$(invoke_agent research-math-agent v1 \
  '{"text":"What is 27 * 13? Use the calculate tool, then state the answer."}' \
  || echo '{"error":"invoke failed (see warns above for missing keys)"}')
echo "$out_adk" | jq . 2>/dev/null || echo "$out_adk"

log "invoke agent: research-orchestrator  (DeepAgent — may call naver_search via MCP)"
out_lg=$(invoke_agent research-orchestrator v1 \
  '{"messages":[{"role":"user","content":"In one sentence, what is LangGraph?"}]}' \
  || echo '{"error":"invoke failed (see warns above for missing keys)"}')
echo "$out_lg" | jq . 2>/dev/null || echo "$out_lg"

ok "all steps completed (5xx in step 5 with missing keys is expected — see warns above)"
