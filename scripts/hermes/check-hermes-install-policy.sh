#!/usr/bin/env bash
# Fail if hermes-base OCI build scripts request fat hermes-agent extras.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCAN_ROOT="${HERMES_POLICY_ROOT:-$ROOT}"

FORBIDDEN=(
  'hermes-agent\[all\]'
  'hermes-agent\[gateway\]'
  'hermes-agent\[web\]'
  'hermes-agent\[messaging\]'
  'pip install.*hermes-agent\['
  'uv pip install.*hermes-agent\['
)

scan_files() {
  local f
  for f in \
    "$SCAN_ROOT/runtimes/hermes-base/Dockerfile" \
    "$SCAN_ROOT/scripts/hermes/vendor-hermes.sh" \
    "$SCAN_ROOT/scripts/hermes/prune-hermes-packages.sh"
  do
    [[ -f "$f" ]] && printf '%s\n' "$f"
  done
}

failed=0
while IFS= read -r file; do
  for pattern in "${FORBIDDEN[@]}"; do
    if grep -qE "$pattern" "$file" 2>/dev/null; then
      echo "forbidden install pattern '$pattern' in $file" >&2
      grep -nE "$pattern" "$file" >&2 || true
      failed=1
    fi
  done
done < <(scan_files)

if [[ "$failed" -ne 0 ]]; then
  echo "hermes install policy check failed" >&2
  exit 1
fi

echo "hermes install policy OK"
