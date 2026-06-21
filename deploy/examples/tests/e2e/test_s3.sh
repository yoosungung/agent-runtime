#!/usr/bin/env bash
# S3 bundle storage e2e smoke test.
#
# Verifies:
#   1. bundle_uri in source_meta is an HTTP URL (not s3://)
#   1b. public Ingress blocks GET /bundles/* (403)
#   2. in-cluster bundle URL (BACKEND_PF_URL or BUNDLE_URI) → 307 presigned redirect
#   3. presigned URL host matches S3 backend
#   4. Downloaded bundle content matches uploaded sha256
#
# Run after backend is deployed with BUNDLE_STORAGE_BACKEND=s3.
# For check 2: kubectl port-forward -n runtime svc/backend 8000:8000
#   (or wire-dev.sh) and optionally BACKEND_PF_URL=http://127.0.0.1:8000

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
source ./lib.sh

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
login
load_state

# ---------------------------------------------------------------------------
# Upload a test bundle and capture source_meta
# ---------------------------------------------------------------------------
BUNDLE_DIR="$EXAMPLES_DIR/mcp-base/fastmcp_bundle"
ZIPF="$WORK_DIR/s3_test_bundle.zip"
TEST_VERSION="s3test-$(date +%s)"

log "building test bundle zip"
build_bundle_zip "$BUNDLE_DIR" "$ZIPF"
LOCAL_SHA=$(sha256_file "$ZIPF")
log "local sha256=$LOCAL_SHA"

log "uploading bundle (version=$TEST_VERSION)"
META=$(jq -nc \
  --arg kind mcp \
  --arg name s3-smoke-test \
  --arg version "$TEST_VERSION" \
  --arg pool mcp:fastmcp \
  --arg ep  app:build_server \
  '{kind:$kind, name:$name, version:$version, runtime_pool:$pool, entrypoint:$ep}')

RESP=$(admin_curl POST /api/source-meta/bundle \
  -F "file=@$ZIPF;type=application/zip" \
  -F "meta=$META")

SOURCE_ID=$(jq -r .id        <<<"$RESP")
BUNDLE_URI=$(jq -r .bundle_uri <<<"$RESP")
CHECKSUM=$(jq -r .checksum    <<<"$RESP")
SHA_HEX=${CHECKSUM#sha256:}

log "source_meta.id=$SOURCE_ID"
log "bundle_uri=$BUNDLE_URI"
log "checksum=$CHECKSUM"

# ---------------------------------------------------------------------------
# Assertion 1: bundle_uri must be HTTP, not s3://
# ---------------------------------------------------------------------------
log "--- check 1: bundle_uri scheme"
if [[ "$BUNDLE_URI" == s3://* ]]; then
  fail "bundle_uri is s3:// — pool loader cannot handle this scheme: $BUNDLE_URI"
fi
if [[ "$BUNDLE_URI" != http* ]]; then
  fail "bundle_uri has unexpected scheme: $BUNDLE_URI"
fi
ok "bundle_uri is HTTP: $BUNDLE_URI"

# ---------------------------------------------------------------------------
# Assertion 1b: public Ingress must not serve /bundles/*
# ---------------------------------------------------------------------------
log "--- check 1b: public Ingress blocks /bundles"
PUB_HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
  "$AGENTS_HOST/bundles/${SHA_HEX}.zip" 2>/dev/null || true)
[ "$PUB_HTTP" = "403" ] || fail "expected 403 from public Ingress for /bundles, got $PUB_HTTP"
ok "public Ingress blocks /bundles → 403"

# Resolve cluster-internal bundle URL for in-cluster-style fetch (port-forward).
resolve_bundle_fetch_url() {
  local uri="$1"
  if [[ "$uri" == *".svc.cluster.local"* ]]; then
    local pf="${BACKEND_PF_URL:-http://127.0.0.1:8000}"
    local rest="${uri#http://}"
    rest="${rest#https://}"
    echo "${pf%/}/${rest#*/}"
  else
    echo "$uri"
  fi
}
BUNDLE_FETCH_URL=$(resolve_bundle_fetch_url "$BUNDLE_URI")
log "bundle_fetch_url=$BUNDLE_FETCH_URL"

# ---------------------------------------------------------------------------
# Assertion 2: GET bundle serve URL → 307 redirect to presigned URL
# ---------------------------------------------------------------------------
log "--- check 2: bundle serve → 307 presigned redirect"
REDIRECT_URL=$(curl -sS --fail-with-body \
  -o /dev/null \
  -w "%{redirect_url}" \
  "$BUNDLE_FETCH_URL")

[ -n "$REDIRECT_URL" ] || fail "no redirect URL returned from $BUNDLE_FETCH_URL (expected 307)"
log "redirect_url=$REDIRECT_URL"

HTTP_CODE=$(curl -sS \
  -o /dev/null \
  -w "%{http_code}" \
  --max-redirs 0 \
  "$BUNDLE_FETCH_URL" 2>/dev/null || true)
[ "$HTTP_CODE" = "307" ] || fail "expected 307, got $HTTP_CODE for $BUNDLE_FETCH_URL"
ok "GET bundle serve URL → 307"

# ---------------------------------------------------------------------------
# Assertion 3: redirect URL points to the configured S3 endpoint
# ---------------------------------------------------------------------------
log "--- check 3: presigned URL host matches S3 backend"
REDIRECT_HOST=$(echo "$REDIRECT_URL" | sed -E 's#^https?://([^/?]+).*#\1#')
case "$REDIRECT_HOST" in
  *ncloudstorage.com*|*garage*|*garage.local*)
    ok "presigned URL host: $REDIRECT_HOST"
    ;;
  *)
    fail "unexpected presigned URL host (not NCP/Garage): $REDIRECT_URL"
    ;;
esac

# ---------------------------------------------------------------------------
# Assertion 4: presigned URL is downloadable and sha256 matches
# ---------------------------------------------------------------------------
log "--- check 4: download via presigned URL and verify sha256"
DOWNLOAD="$WORK_DIR/s3_downloaded.zip"
HTTP_DL=$(curl -sS \
  -o "$DOWNLOAD" \
  -w "%{http_code}" \
  "$REDIRECT_URL")
[ "$HTTP_DL" = "200" ] || fail "presigned URL download returned HTTP $HTTP_DL (expected 200)"

DOWNLOADED_SHA=$(sha256_file "$DOWNLOAD")
[ "$DOWNLOADED_SHA" = "$LOCAL_SHA" ] \
  || fail "sha256 mismatch: uploaded=$LOCAL_SHA downloaded=$DOWNLOADED_SHA"
ok "downloaded sha256 matches: $LOCAL_SHA"

# ---------------------------------------------------------------------------
# Cleanup: retire the test source_meta row
# ---------------------------------------------------------------------------
log "retiring test source_meta (id=$SOURCE_ID)"
admin_curl POST "/api/source-meta/${SOURCE_ID}/retire" \
  -H 'Content-Type: application/json' \
  -d '{}' -o /dev/null
ok "retired"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
ok "=== S3 e2e smoke test passed ==="
