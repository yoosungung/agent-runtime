#!/usr/bin/env bash
# Clone or update hermes-agent main, apply patches, editable install.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR_SRC="${ROOT}/vendor/hermes-agent/src"
PATCH_DIR="${ROOT}/vendor/hermes-agent/patches"
REVISION_FILE="${ROOT}/vendor/hermes-agent/REVISION"
REPO_URL="https://github.com/NousResearch/hermes-agent.git"
PIN="${1:-}"

mkdir -p "$(dirname "$VENDOR_SRC")"

if [[ -d "${VENDOR_SRC}/.git" ]]; then
  git -C "$VENDOR_SRC" fetch origin main --depth 1
  if [[ -n "$PIN" && "$PIN" != "--pin" ]]; then
    git -C "$VENDOR_SRC" checkout "$PIN"
  else
    git -C "$VENDOR_SRC" checkout origin/main
  fi
else
  rm -rf "$VENDOR_SRC"
  git clone --depth 1 --branch main "$REPO_URL" "$VENDOR_SRC"
  if [[ -n "$PIN" && "$PIN" != "--pin" ]]; then
    git -C "$VENDOR_SRC" fetch --depth 1 origin "$PIN"
    git -C "$VENDOR_SRC" checkout "$PIN"
  fi
fi

if [[ -d "$PATCH_DIR" ]]; then
  shopt -s nullglob
  for patch in "$PATCH_DIR"/*.patch; do
    echo "Applying $(basename "$patch")..."
    git -C "$VENDOR_SRC" apply --check "$patch"
    git -C "$VENDOR_SRC" apply "$patch"
  done
fi

git -C "$VENDOR_SRC" rev-parse HEAD > "$REVISION_FILE"
echo "hermes-agent @ $(cat "$REVISION_FILE")"

if [[ "${HERMES_VENDOR_SKIP_INSTALL:-}" == "1" ]]; then
  exit 0
fi

cd "$ROOT"
uv pip install -e "$VENDOR_SRC"
