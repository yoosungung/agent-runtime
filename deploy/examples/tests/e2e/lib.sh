#!/usr/bin/env bash
# Shared helpers for e2e curl tests against the dev cluster Ingress.
# Source this file from run.sh or individual step scripts.

set -euo pipefail

: "${AGENTS_HOST:=https://agents.didim365.app}"
: "${ADMIN_USER:=admin}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD must be set (initial admin password seeded into backend)}"

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLES_DIR="$(cd "$E2E_DIR/../.." && pwd)"
WORK_DIR="$E2E_DIR/work"
COOKIE_JAR="$WORK_DIR/cookies.txt"
STATE_FILE="$WORK_DIR/state.env"

mkdir -p "$WORK_DIR"

log()  { printf '\033[1;34m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
fail() { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }
ok()   { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*" >&2; }

require() {
  command -v "$1" >/dev/null 2>&1 || fail "missing dependency: $1"
}

require curl
require jq
require zip

# ---------------------------------------------------------------------------
# Login — hits backend BFF /api/auth/login (NOT raw auth /login).
# Backend wraps auth and additionally sets:
#   - access_token (httpOnly cookie)   ← also used as Bearer for /v1/agents/invoke
#   - refresh_token (httpOnly cookie, path=/api/auth)
#   - csrf_token (non-httpOnly cookie) ← echoed as X-CSRF-Token on writes
# Saves cookies to $COOKIE_JAR and writes state to $STATE_FILE.
# ---------------------------------------------------------------------------
login() {
  log "login as $ADMIN_USER"
  rm -f "$COOKIE_JAR"
  local body
  body=$(curl -sS --fail-with-body \
    -c "$COOKIE_JAR" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$ADMIN_USER" --arg p "$ADMIN_PASSWORD" \
            '{username:$u, password:$p}')" \
    "$AGENTS_HOST/api/auth/login") \
    || fail "login failed: $body"

  local user_id is_admin csrf access
  user_id=$(jq -r .user_id <<<"$body")
  is_admin=$(jq -r .is_admin <<<"$body")
  [ "$is_admin" = "true" ] || fail "logged-in user is not admin"

  csrf=$(awk '/csrf_token/ {print $7}' "$COOKIE_JAR" | tail -n1)
  access=$(awk '/access_token/ {print $7}' "$COOKIE_JAR" | tail -n1)
  [ -n "$csrf" ]   || fail "csrf cookie missing from login response"
  [ -n "$access" ] || fail "access_token cookie missing from login response"

  cat >"$STATE_FILE" <<EOF
USER_ID=$user_id
PRINCIPAL_SUB=$ADMIN_USER
CSRF=$csrf
ACCESS_TOKEN=$access
EOF
  ok "login → user_id=$user_id"
}

load_state() {
  [ -f "$STATE_FILE" ] || fail "state file missing — run login first"
  # shellcheck source=/dev/null
  source "$STATE_FILE"
}

# Admin-API curl: sends cookies + X-CSRF-Token header.
# Usage: admin_curl <method> <path> [extra-curl-args...]
admin_curl() {
  local method="$1" path="$2"; shift 2
  curl -sS --fail-with-body \
    -X "$method" \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -H "X-CSRF-Token: $CSRF" \
    "$@" \
    "$AGENTS_HOST$path"
}

# Build a zip of a bundle directory with app.py at archive root.
# Usage: build_bundle_zip <bundle_dir> <out_zip>
build_bundle_zip() {
  local src="$1" out="$2"
  rm -f "$out"
  ( cd "$src" && zip -q -r "$out" . -x '*/__pycache__/*' '*.pyc' ) \
    || fail "zip failed for $src"
}

# Register a bundle via multipart upload to admin backend.
# Returns the new source_meta.id on stdout.
# Usage: upload_bundle <zip> <kind> <name> <version> <runtime_pool> <entrypoint> [config_json]
upload_bundle() {
  local zipf="$1" kind="$2" name="$3" version="$4" pool="$5" entry="$6"
  local config="${7-}"
  [ -n "$config" ] || config='{}'
  local meta
  meta=$(jq -nc --arg k "$kind" --arg n "$name" --arg v "$version" \
                --arg p "$pool" --arg e "$entry" --argjson c "$config" \
         '{kind:$k, name:$n, version:$v, runtime_pool:$p, entrypoint:$e, config:$c}') \
    || fail "meta JSON build failed (config=$config)"
  # Backend rate-limits this endpoint at 5 req/min per user — retry once on 429
  # after a 65s sleep so the e2e survives a hot iteration window.
  local resp attempt
  for attempt in 1 2; do
    resp=$(admin_curl POST /api/source-meta/bundle \
      -F "file=@$zipf;type=application/zip" \
      -F "meta=$meta" 2>&1) && { jq -r .id <<<"$resp"; return 0; }
    # 409 = already exists (idempotent re-run): look up existing id and return it.
    if grep -q 'already exists' <<<"$resp"; then
      log "  bundle exists, looking up existing id"
      local existing
      # Backend GET filter on name is a substring match, so also match name
      # exactly in jq to avoid sibling rows (e.g. example-mcp vs example-mcp-sdk).
      existing=$(admin_curl GET "/api/source-meta?kind=$kind&name=$name" \
                 | jq -r --arg v "$version" --arg n "$name" \
                       '.items[] | select(.version==$v and .name==$n) | .id')
      [ -n "$existing" ] || fail "could not find existing source_meta for $kind/$name/$version"
      echo "$existing"
      return 0
    fi
    if [ "$attempt" = 1 ] && grep -qE 'error: 429|Too Many Requests' <<<"$resp"; then
      log "  rate-limited (429); sleeping 65s before retry"
      sleep 65
      continue
    fi
    fail "upload_bundle $name failed: $resp"
  done
}

# Idempotently grant the admin user access to (kind, name).
grant_access() {
  local kind="$1" name="$2"
  admin_curl POST "/api/users/$USER_ID/access" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg k "$kind" --arg n "$name" '{kind:$k, name:$n}')" \
    -o /dev/null -w "%{http_code}" \
    | grep -qE '^(204|409)$' \
    || fail "grant_access $kind/$name failed"
}

# Upsert a per-principal user_meta row.
# Usage: upsert_user_meta <source_meta_id> <principal_sub> <config_json>
upsert_user_meta() {
  local sid="$1" sub="$2" cfg="$3"
  admin_curl PUT /api/user-meta \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --argjson s "$sid" --arg p "$sub" --argjson c "$cfg" \
            '{source_meta_id:$s, principal_id:$p, config:$c}')" \
    -o /dev/null
}

# Invoke an agent through the public Ingress (Envoy-routed).
# Uses the access_token cookie value as Authorization: Bearer.
# Usage: invoke_agent <name> <version> <input_json>
invoke_agent() {
  local name="$1" version="$2" input="$3"
  curl -sS --fail-with-body \
    -X POST "$AGENTS_HOST/v1/agents/invoke" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg a "$name" --arg v "$version" --argjson i "$input" \
            '{agent:$a, version:$v, input:$i, stream:false}')"
}
