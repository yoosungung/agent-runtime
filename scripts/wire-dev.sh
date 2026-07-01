#!/usr/bin/env bash
# Wire a local Mac process to the dev k8s cluster (namespace: runtime).
#
# Usage:
#   ./scripts/wire-dev.sh up [--profile core|s3|full|legacy|opik]
#   ./scripts/wire-dev.sh down
#   ./scripts/wire-dev.sh status
#   ./scripts/wire-dev.sh env [--storage local|s3]  # write ${REPO}/.env.dev.local
#   ./scripts/wire-dev.sh pool-isolate <runtime_kind>
#   ./scripts/wire-dev.sh pool-restore <runtime_kind>
#   ./scripts/wire-dev.sh pool-restore-all
#
#   runtime_kind: compiled_graph | adk | hermes | fastmcp | mcp_sdk
#
# Local port map (cluster Service → Mac):
#   postgres:5432, redis:6379, auth:8081, deploy-api:8082, ext-authz:8083,
#   envoy:8084, backend:8000, backend-bundles:8010 (pool debug),
#   garage-s3:3900 (profile s3 — pipeline ingest manifest / blob store)
#
# See scripts/wire-dev.env.example and .vscode/launch.json for debug configs.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-runtime}"
OPIK_NAMESPACE="${OPIK_NAMESPACE:-opik}"
STATE_DIR="${WIRE_DEV_STATE_DIR:-$ROOT/.wire-dev}"
PID_DIR="$STATE_DIR/pids"
POOL_STATE_DIR="$STATE_DIR/pool-isolate"
PROFILE="${WIRE_DEV_PROFILE:-core}"
STORAGE_BACKEND="${WIRE_DEV_STORAGE:-}"
REGISTRY_TTL_WAIT_SEC="${REGISTRY_TTL_WAIT_SEC:-4}"

# Dev Garage defaults — sync with deploy/k8s/garage/garage-secrets.env
GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GKdev000000000000000001}"
GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-devsecret000000000000000000000000000000000000000000000000000000}"
GARAGE_BUCKET="${GARAGE_BUCKET:-runtime-bundles}"

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \?//'
  echo
  echo "Profiles:"
  echo "  core   postgres, redis, auth, deploy-api, envoy (default)"
  echo "  s3     core + garage-s3 :3900 (pipeline ingest; env → PIPELINE_STORAGE_BACKEND=s3)"
  echo "  full   core + ext-authz + backend"
  echo "  legacy postgres, redis, auth on :8080 (ready.sh compat; may conflict locally)"
  echo "  opik   Opik backend :8090/:3003 in namespace ${OPIK_NAMESPACE}"
  echo
  echo "Pool debug (launch.json pre/post tasks):"
  echo "  pool-isolate <runtime_kind>  scale cluster pool→0, pf backend bundles :8010"
  echo "  runtime_kind hermes → local pool :8095/invoke"
  echo "  pool-restore <runtime_kind>  restore saved replica count"
  echo "  pool-restore-all             restore every isolated pool"
  echo
  echo "env:"
  echo "  --storage local|s3   pipeline blob backend (default: local; s3 if last 'up --profile s3')"
}

pool_deployment() {
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

require_kubectl() {
  if ! command -v kubectl >/dev/null 2>&1; then
    echo "error: kubectl not found" >&2
    exit 1
  fi
  if ! kubectl -n "$NAMESPACE" get svc postgres >/dev/null 2>&1; then
    echo "error: namespace '$NAMESPACE' or service 'postgres' not reachable" >&2
    echo "hint: kubectl config current-context && make k8s-apply-dev" >&2
    exit 1
  fi
}

port_listen() {
  lsof -i ":$1" -sTCP:LISTEN >/dev/null 2>&1
}

svc_exists() {
  kubectl -n "$1" get "svc/$2" >/dev/null 2>&1
}

start_pf() {
  local name="$1"
  local local_port="$2"
  local remote_port="$3"
  local svc="$4"
  local ns="$5"
  local pid_file="$PID_DIR/${name}.pid"

  mkdir -p "$PID_DIR"

  if [[ -f "$pid_file" ]]; then
    local old_pid
    old_pid="$(cat "$pid_file")"
    if kill -0 "$old_pid" 2>/dev/null; then
      echo "  [skip] $name already forwarded (pid $old_pid, :$local_port)"
      return 0
    fi
    rm -f "$pid_file"
  fi

  if port_listen "$local_port"; then
    echo "  [warn] port $local_port already in use — skipping $name (svc/$svc)" >&2
    return 0
  fi

  if ! svc_exists "$ns" "$svc"; then
    echo "  [warn] svc/$svc not found in $ns — skipping $name" >&2
    return 0
  fi

  echo "  [start] $name 127.0.0.1:$local_port → svc/$svc:$remote_port ($ns)"
  kubectl -n "$ns" port-forward "svc/$svc" "${local_port}:${remote_port}" \
    >"$STATE_DIR/${name}.log" 2>&1 &
  echo $! >"$pid_file"
  sleep 0.3
}

stop_pf() {
  local name="$1"
  local pid_file="$PID_DIR/${name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "  [stop] $name (pid $pid)"
  fi
  rm -f "$pid_file"
}

wire_core() {
  start_pf postgres 5432 5432 postgres "$NAMESPACE"
  start_pf redis 6379 6379 redis "$NAMESPACE"
  start_pf auth 8081 8080 auth "$NAMESPACE"
  start_pf deploy-api 8082 8080 deploy-api "$NAMESPACE"
  start_pf envoy 8084 8080 envoy "$NAMESPACE"
}

wire_garage() {
  start_pf garage-s3 3900 3900 garage-s3 "$NAMESPACE"
}

wire_full() {
  wire_core
  start_pf ext-authz 8083 8080 ext-authz "$NAMESPACE"
  start_pf backend 8000 8000 backend "$NAMESPACE"
}

wire_legacy() {
  start_pf postgres 5432 5432 postgres "$NAMESPACE"
  start_pf redis 6379 6379 redis "$NAMESPACE"
  start_pf auth-8080 8080 8080 auth "$NAMESPACE"
}

wire_opik() {
  if ! kubectl -n "$OPIK_NAMESPACE" get svc opik-backend >/dev/null 2>&1; then
    echo "  [warn] svc/opik-backend not found in $OPIK_NAMESPACE — skipping opik" >&2
    return 0
  fi
  local name="opik-backend"
  local pid_file="$PID_DIR/${name}.pid"
  mkdir -p "$PID_DIR"

  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "  [skip] opik-backend already forwarded"
    return 0
  fi

  if port_listen 8090 || port_listen 3003; then
    echo "  [warn] port 8090 or 3003 in use — skipping opik" >&2
    return 0
  fi

  echo "  [start] opik 127.0.0.1:8090→8080, :3003→3003 (svc/opik-backend, $OPIK_NAMESPACE)"
  kubectl -n "$OPIK_NAMESPACE" port-forward svc/opik-backend 8090:8080 3003:3003 \
    >"$STATE_DIR/opik-backend.log" 2>&1 &
  echo $! >"$pid_file"
  sleep 0.3
}

cmd_up() {
  local profile="$1"
  require_kubectl
  mkdir -p "$STATE_DIR"
  echo "wire-dev: profile=$profile namespace=$NAMESPACE"
  case "$profile" in
    core) wire_core ;;
    s3)
      wire_core
      wire_garage
      ;;
    full) wire_full ;;
    legacy) wire_legacy ;;
    opik) wire_opik ;;
    *)
      echo "error: unknown profile '$profile'" >&2
      exit 1
      ;;
  esac
  echo "$profile" >"$STATE_DIR/profile"
  echo "wire-dev: up done (pids in $PID_DIR)"
}

cmd_down() {
  cmd_pool_restore_all || true
  if [[ ! -d "$PID_DIR" ]]; then
    echo "wire-dev: nothing to stop"
    return 0
  fi
  echo "wire-dev: stopping port-forwards"
  for pid_file in "$PID_DIR"/*.pid; do
    [[ -e "$pid_file" ]] || continue
    name="$(basename "$pid_file" .pid)"
    stop_pf "$name"
  done
  echo "wire-dev: down done"
}

cmd_status() {
  if [[ ! -d "$PID_DIR" ]]; then
    echo "wire-dev: no active forwards"
    return 0
  fi
  echo "wire-dev: active forwards"
  local any=0
  for pid_file in "$PID_DIR"/*.pid; do
    [[ -e "$pid_file" ]] || continue
    any=1
    local name pid
    name="$(basename "$pid_file" .pid)"
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "  ok  $name pid=$pid"
    else
      echo "  dead $name pid=$pid (stale pid file)"
    fi
  done
  if [[ "$any" -eq 0 ]]; then
    echo "  (none)"
  fi
}

fetch_jwt_keys() {
  local priv pub
  priv="$(kubectl -n "$NAMESPACE" get secret jwt-keys -o jsonpath='{.data.JWT_PRIVATE_KEY}' 2>/dev/null | base64 -d || true)"
  pub="$(kubectl -n "$NAMESPACE" get secret jwt-keys -o jsonpath='{.data.JWT_PUBLIC_KEY}' 2>/dev/null | base64 -d || true)"
  if [[ -z "$priv" || -z "$pub" ]]; then
    echo "error: secret jwt-keys not found in namespace $NAMESPACE" >&2
    exit 1
  fi
  JWT_PRIVATE_KEY="$priv"
  JWT_PUBLIC_KEY="$pub"
}

resolve_storage_backend() {
  local storage="$STORAGE_BACKEND"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --storage)
        storage="$2"
        shift 2
        ;;
      *)
        echo "error: unknown env option '$1'" >&2
        exit 1
        ;;
    esac
  done
  if [[ -z "$storage" ]] && [[ -f "$STATE_DIR/profile" ]]; then
    if [[ "$(cat "$STATE_DIR/profile")" == "s3" ]]; then
      storage="s3"
    fi
  fi
  echo "${storage:-local}"
}

cmd_env() {
  require_kubectl
  fetch_jwt_keys
  local storage
  storage="$(resolve_storage_backend "$@")"
  local env_file="$ROOT/.env.dev.local"
  local bundle_dir="$STATE_DIR/bundles"
  mkdir -p "$bundle_dir"

  local s3_block=""
  if [[ "$storage" == "s3" ]]; then
    s3_block=$(cat <<EOF

# Pipeline blob store (Garage via wire-dev profile s3 → :3900)
PIPELINE_STORAGE_BACKEND=s3
S3_ENDPOINT_URL=http://127.0.0.1:3900
S3_BUCKET=${GARAGE_BUCKET}
S3_ACCESS_KEY_ID=${GARAGE_ACCESS_KEY}
S3_SECRET_ACCESS_KEY=${GARAGE_SECRET_KEY}
S3_REGION=garage
EOF
)
  fi

  cat >"$env_file" <<EOF
# Generated by scripts/wire-dev.sh env — do not commit (.gitignore)
# Re-run: ./scripts/wire-dev.sh env

ENV=dev
LOG_LEVEL=DEBUG

POSTGRES_DSN=postgresql+asyncpg://runtime:runtime@127.0.0.1:5432/runtime?sslmode=disable
POSTGRES_READ_DSN=postgresql+asyncpg://runtime:runtime@127.0.0.1:5432/runtime?sslmode=disable
POSTGRES_PGBOUNCER=false
VFS_DSN=postgresql://runtime:runtime@127.0.0.1:5432/runtime?sslmode=disable
VFS_PGBOUNCER=false

REDIS_URL=redis://127.0.0.1:6379

AUTH_URL=http://127.0.0.1:8081
AUTH_SERVICE_URL=http://127.0.0.1:8081
DEPLOY_API_URL=http://127.0.0.1:8082
ENVOY_URL=http://127.0.0.1:8084
MCP_GATEWAY_URL=http://127.0.0.1:8084

JWT_ISSUER=agents-runtime

K8S_IN_CLUSTER=false
K8S_RUNTIME_NAMESPACE=${NAMESPACE}
SESSION_COOKIE_SECURE=false
BACKEND_SERVE_SPA=false
CORS_ORIGINS=http://localhost:5173
ALLOW_HARD_DELETE=true
BUNDLE_STORAGE_BACKEND=local
BUNDLE_STORAGE_DIR=${bundle_dir}
BUNDLE_PUBLIC_BASE_URL=http://127.0.0.1:8000/bundles

# hermes-base pool (ProfileVfsSync + SessionDB)
HERMES_WORK_DIR=${STATE_DIR}/hermes-work
HERMES_SESSION_DSN=postgresql://runtime:runtime@127.0.0.1:5432/runtime?sslmode=disable

# Pool local debug — scale cluster pool to 0 before debugging to avoid Redis registry clashes
POD_NAME=local-dev
POD_IP=127.0.0.1${s3_block}
EOF

  chmod 600 "$env_file"

  # Append PEM keys with escaped newlines (portable on macOS/Linux).
  JWT_PRIVATE_KEY="$JWT_PRIVATE_KEY" JWT_PUBLIC_KEY="$JWT_PUBLIC_KEY" \
    "${ROOT}/.venv/bin/python3" - "$env_file" <<'PY'
import os
import sys

def esc(pem: str) -> str:
    return pem.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

path = sys.argv[1]
with open(path, "a", encoding="utf-8") as f:
    f.write(f'JWT_PRIVATE_KEY="{esc(os.environ["JWT_PRIVATE_KEY"])}"\n')
    f.write(f'JWT_PUBLIC_KEY="{esc(os.environ["JWT_PUBLIC_KEY"])}"\n')
PY

  echo "wire-dev: wrote $env_file (pipeline storage=$storage)"
}

cmd_pool_isolate() {
  local kind="${1:-}"
  if [[ -z "$kind" ]]; then
    echo "error: pool-isolate requires runtime_kind" >&2
    exit 1
  fi
  require_kubectl
  local deploy
  deploy="$(pool_deployment "$kind")"

  mkdir -p "$POOL_STATE_DIR"
  local state_file="$POOL_STATE_DIR/${deploy}.replicas"
  local current
  current="$(kubectl -n "$NAMESPACE" get "deploy/$deploy" -o jsonpath='{.spec.replicas}' 2>/dev/null || true)"
  if [[ -z "$current" ]]; then
    echo "error: deployment $deploy not found in namespace $NAMESPACE" >&2
    exit 1
  fi

  if [[ ! -f "$state_file" ]]; then
    echo "$current" >"$state_file"
    echo "wire-dev: saved $deploy replicas=$current"
  else
    echo "wire-dev: $deploy already isolated (restore target=$(cat "$state_file"))"
  fi

  if [[ "$current" != "0" ]]; then
    echo "wire-dev: scaling $deploy → 0 (avoid Redis warm-registry clash with local pool)"
    kubectl -n "$NAMESPACE" scale "deploy/$deploy" --replicas=0
    kubectl -n "$NAMESPACE" rollout status "deploy/$deploy" --timeout=120s
  else
    echo "wire-dev: $deploy already at 0 replicas"
  fi

  echo "wire-dev: waiting ${REGISTRY_TTL_WAIT_SEC}s for warm-registry TTL expiry..."
  sleep "$REGISTRY_TTL_WAIT_SEC"

  start_pf backend-bundles 8010 8000 backend "$NAMESPACE"

  local local_port
  case "$kind" in
    compiled_graph) local_port=8091 ;;
    adk) local_port=8092 ;;
    hermes) local_port=8095 ;;
    fastmcp) local_port=8093 ;;
    mcp_sdk) local_port=8094 ;;
    *) local_port="?" ;;
  esac

  cat <<EOF
wire-dev: pool isolate ready for RUNTIME_KIND=$kind
  • POST /invoke → http://127.0.0.1:${local_port}/invoke
  • Cluster bundles: http://127.0.0.1:8010/bundles/... (bundle_uri must use this host or file://)
  • Ingress/Envoy full path is not wired to local pool — use boundary /invoke
  • Stop debugger → pool-restore runs automatically (or: ./scripts/wire-dev.sh pool-restore $kind)
EOF
}

cmd_pool_restore() {
  local kind="${1:-}"
  if [[ -z "$kind" ]]; then
    echo "error: pool-restore requires runtime_kind" >&2
    exit 1
  fi
  require_kubectl
  local deploy
  deploy="$(pool_deployment "$kind")"
  local state_file="$POOL_STATE_DIR/${deploy}.replicas"

  stop_pf backend-bundles

  if [[ ! -f "$state_file" ]]; then
    echo "wire-dev: no isolate state for $deploy — skip restore"
    return 0
  fi

  local replicas
  replicas="$(cat "$state_file")"
  echo "wire-dev: restoring $deploy → replicas=$replicas"
  kubectl -n "$NAMESPACE" scale "deploy/$deploy" --replicas="$replicas"
  kubectl -n "$NAMESPACE" rollout status "deploy/$deploy" --timeout=180s
  rm -f "$state_file"
  echo "wire-dev: pool restore done ($deploy)"
}

cmd_pool_restore_all() {
  if [[ ! -d "$POOL_STATE_DIR" ]]; then
    return 0
  fi
  local restored=0
  for state_file in "$POOL_STATE_DIR"/*.replicas; do
    [[ -e "$state_file" ]] || continue
    local deploy kind
    deploy="$(basename "$state_file" .replicas)"
    case "$deploy" in
      agent-pool-compiled-graph) kind="compiled_graph" ;;
      agent-pool-adk) kind="adk" ;;
      agent-pool-hermes) kind="hermes" ;;
      mcp-pool-fastmcp) kind="fastmcp" ;;
      mcp-pool-mcp-sdk) kind="mcp_sdk" ;;
      *)
        echo "wire-dev: unknown deployment in state: $deploy" >&2
        continue
        ;;
    esac
    cmd_pool_restore "$kind"
    restored=1
  done
  if [[ "$restored" -eq 0 ]]; then
    echo "wire-dev: no isolated pools to restore"
  fi
}

main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    up)
      local profile="$PROFILE"
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --profile)
            profile="$2"
            shift 2
            ;;
          *)
            echo "error: unknown option '$1'" >&2
            usage
            exit 1
            ;;
        esac
      done
      cmd_up "$profile"
      ;;
    down) cmd_down ;;
    status) cmd_status ;;
    env) cmd_env "$@" ;;
    pool-isolate)
      cmd_pool_isolate "${1:-}"
      ;;
    pool-restore)
      cmd_pool_restore "${1:-}"
      ;;
    pool-restore-all) cmd_pool_restore_all ;;
    -h | --help | help) usage ;;
    *)
      echo "error: unknown command '${cmd:-}'" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
