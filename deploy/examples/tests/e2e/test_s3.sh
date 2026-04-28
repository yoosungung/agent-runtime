#!/usr/bin/env bash
# S3 bundle storage e2e smoke test.
#
# Verifies:
#   1. bundle_uri in source_meta is an HTTP URL (not s3://)
#   2. GET /bundles/{sha256}.zip returns 307 redirect to NCP presigned URL
#   3. presigned URL is directly downloadable (HEAD 200)
#   4. Downloaded bundle content matches uploaded sha256
#
# Run after backend is deployed with BUNDLE_STORAGE_BACKEND=s3.
# Prereqs: curl, jq, zip, sha256sum (or shasum on macOS).

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
# Assertion 2: GET /bundles/{sha256}.zip → 307 redirect to NCP presigned URL
# ---------------------------------------------------------------------------
log "--- check 2: bundle serve → 307 presigned redirect"
REDIRECT_URL=$(curl -sS --fail-with-body \
  -b "$COOKIE_JAR" \
  -o /dev/null \
  -w "%{redirect_url}" \
  "$AGENTS_HOST/bundles/${SHA_HEX}.zip")

[ -n "$REDIRECT_URL" ] || fail "no redirect URL returned from /bundles/${SHA_HEX}.zip (expected 307)"
log "redirect_url=$REDIRECT_URL"

HTTP_CODE=$(curl -sS \
  -b "$COOKIE_JAR" \
  -o /dev/null \
  -w "%{http_code}" \
  --max-redirs 0 \
  "$AGENTS_HOST/bundles/${SHA_HEX}.zip" 2>/dev/null || true)
[ "$HTTP_CODE" = "307" ] || fail "expected 307, got $HTTP_CODE for /bundles/${SHA_HEX}.zip"
ok "GET /bundles/${SHA_HEX}.zip → 307"

# ---------------------------------------------------------------------------
# Assertion 3: redirect URL points to NCP Object Storage
# ---------------------------------------------------------------------------
log "--- check 3: presigned URL is NCP endpoint"
if [[ "$REDIRECT_URL" != *ncloudstorage.com* ]]; then
  fail "redirect URL does not point to NCP: $REDIRECT_URL"
fi
ok "presigned URL domain: $(echo "$REDIRECT_URL" | grep -oE '[^/]+\.ncloudstorage\.com')"

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
