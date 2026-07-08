#!/usr/bin/env bash
# Telepresence-based core service debug (replaces wire-dev port-forward for launch.json).
#
# Usage:
#   ./scripts/telepresence-service-dev.sh intercept <service>
#   ./scripts/telepresence-service-dev.sh leave <service>
#
#   service: auth | deploy-api | ext-authz | backend
#
# Writes ${REPO}/.env.telepresence-<service> for VS Code envFile.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-runtime}"

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \?//'
}

k8s_service() {
  case "$1" in
    auth) echo "auth" ;;
    deploy-api) echo "deploy-api" ;;
    ext-authz) echo "ext-authz" ;;
    backend) echo "backend" ;;
    *)
      echo "error: unknown service '$1' (auth|deploy-api|ext-authz|backend)" >&2
      return 1
      ;;
  esac
}

local_port() {
  case "$1" in
    auth) echo 8081 ;;
    deploy-api) echo 8082 ;;
    ext-authz) echo 8083 ;;
    backend) echo 8000 ;;
    *)
      echo "error: unknown service '$1'" >&2
      return 1
      ;;
  esac
}

pod_port() {
  case "$1" in
    backend) echo 8000 ;;
    auth | deploy-api | ext-authz) echo 8080 ;;
    *)
      echo "error: unknown service '$1'" >&2
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
    echo "telepresence-service-dev: already connected"
    return 0
  fi
  echo "telepresence-service-dev: connecting to namespace $NAMESPACE"
  telepresence connect -n "$NAMESPACE"
}

cmd_intercept() {
  local service_key="${1:-}"
  if [[ -z "$service_key" ]]; then
    echo "error: intercept requires service" >&2
    usage
    exit 1
  fi
  require_telepresence

  local service local_port pod_port env_file
  service="$(k8s_service "$service_key")"
  local_port="$(local_port "$service_key")"
  pod_port="$(pod_port "$service_key")"
  env_file="$ROOT/.env.telepresence-${service_key}"

  cmd_connect

  telepresence leave "$service" -n "$NAMESPACE" 2>/dev/null || true

  echo "telepresence-service-dev: intercept $service → localhost:$local_port"
  telepresence intercept "$service" \
    -n "$NAMESPACE" \
    -p "${local_port}:${pod_port}" \
    --mount false \
    --env-file "$env_file"

  chmod 600 "$env_file"
  cat <<EOF
telepresence-service-dev: ready for $service_key
  • Cluster traffic → http://127.0.0.1:${local_port}
  • Remote env     → ${env_file}
  • Stop debugger  → telepresence leave runs automatically
EOF
}

cmd_leave() {
  local service_key="${1:-}"
  if [[ -z "$service_key" ]]; then
    echo "error: leave requires service" >&2
    usage
    exit 1
  fi
  require_telepresence

  local service
  service="$(k8s_service "$service_key")"
  if telepresence leave "$service" -n "$NAMESPACE"; then
    echo "telepresence-service-dev: left $service"
  else
    echo "telepresence-service-dev: no active intercept for $service"
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
