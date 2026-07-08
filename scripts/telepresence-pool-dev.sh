#!/usr/bin/env bash
# Telepresence-based pool debug (replaces wire-dev pool-isolate for launch.json).
#
# Usage:
#   ./scripts/telepresence-pool-dev.sh intercept <runtime_kind>
#   ./scripts/telepresence-pool-dev.sh leave <runtime_kind>
#
#   runtime_kind: compiled_graph | adk | hermes | fastmcp | mcp_sdk
#
# Writes ${REPO}/.env.telepresence-<runtime_kind> for VS Code envFile.
# See .vscode/launch.json "Debug: agent-pool (compiled_graph)".

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-runtime}"

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \?//'
}

pool_service() {
  case "$1" in
    compiled_graph) echo "agent-pool-compiled-graph" ;;
    adk) echo "agent-pool-adk" ;;
    hermes) echo "agent-pool-hermes" ;;
    fastmcp) echo "mcp-pool-fastmcp" ;;
    mcp_sdk) echo "mcp-pool-mcp-sdk" ;;
    *)
      echo "error: unknown runtime_kind '$1' (compiled_graph|adk|hermes|fastmcp|mcp_sdk)" >&2
      return 1
      ;;
  esac
}

pool_local_port() {
  case "$1" in
    compiled_graph) echo 8091 ;;
    adk) echo 8092 ;;
    hermes) echo 8095 ;;
    fastmcp) echo 8093 ;;
    mcp_sdk) echo 8094 ;;
    *)
      echo "error: unknown runtime_kind '$1'" >&2
      return 1
      ;;
  esac
}

require_telepresence() {
  if ! command -v telepresence >/dev/null 2>&1; then
    echo "error: telepresence not found (https://telepresence.io/docs/install/)" >&2
    exit 1
  fi
}

cmd_connect() {
  if telepresence status 2>/dev/null | grep -q "Connected"; then
    echo "telepresence-pool-dev: already connected"
    return 0
  fi
  echo "telepresence-pool-dev: connecting to namespace $NAMESPACE"
  telepresence connect -n "$NAMESPACE"
}

cmd_intercept() {
  local kind="${1:-}"
  if [[ -z "$kind" ]]; then
    echo "error: intercept requires runtime_kind" >&2
    usage
    exit 1
  fi
  require_telepresence

  local service local_port env_file
  service="$(pool_service "$kind")"
  local_port="$(pool_local_port "$kind")"
  env_file="$ROOT/.env.telepresence-${kind}"

  cmd_connect

  telepresence leave "$service" -n "$NAMESPACE" 2>/dev/null || true

  echo "telepresence-pool-dev: intercept $service → localhost:$local_port"
  telepresence intercept "$service" \
    -n "$NAMESPACE" \
    -p "${local_port}:8080" \
    --mount false \
    --env-file "$env_file"

  chmod 600 "$env_file"
  cat <<EOF
telepresence-pool-dev: ready for RUNTIME_KIND=$kind
  • Cluster traffic → http://127.0.0.1:${local_port}
  • Remote env     → ${env_file}
  • Stop debugger  → telepresence leave runs automatically
EOF
}

cmd_leave() {
  local kind="${1:-}"
  if [[ -z "$kind" ]]; then
    echo "error: leave requires runtime_kind" >&2
    usage
    exit 1
  fi
  require_telepresence

  local service
  service="$(pool_service "$kind")"
  if telepresence leave "$service" -n "$NAMESPACE"; then
    echo "telepresence-pool-dev: left $service"
  else
    echo "telepresence-pool-dev: no active intercept for $service"
  fi
}

main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    intercept) cmd_intercept "${1:-}" ;;
    leave) cmd_leave "${1:-}" ;;
    -h | --help | help) usage ;;
    *)
      echo "error: unknown command '${cmd:-}'" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
