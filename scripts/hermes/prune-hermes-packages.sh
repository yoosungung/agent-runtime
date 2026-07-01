#!/usr/bin/env bash
# Remove hermes-agent packages not needed for pool /invoke (AIAgent embed only).
#
# Vendor source: keep hermes_cli (run_agent imports env_loader at module load).
# Site-packages: also drop hermes_cli if a wheel copy exists beside editable install.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SITE="${1:-}"

VENDOR_PRUNE=(gateway tui_gateway acp_adapter)
SITE_PRUNE=(gateway tui_gateway acp_adapter)

_prune_dir() {
  local base="$1"
  shift
  local pkg
  for pkg in "$@"; do
    local target="$base/$pkg"
    if [[ -d "$target" ]]; then
      rm -rf "$target"
      echo "pruned $(basename "$base")/$pkg"
    fi
  done
}

VENDOR_SRC="${HERMES_VENDOR_SRC:-$ROOT/vendor/hermes-agent/src}"

if [[ -z "$SITE" ]]; then
  if [[ -d "$VENDOR_SRC" ]]; then
    _prune_dir "$VENDOR_SRC" "${VENDOR_PRUNE[@]}"
  fi
  if [[ "${HERMES_PRUNE_SITE:-1}" == "1" ]]; then
    SITE="$ROOT/.venv/lib/python3.12/site-packages"
  else
    SITE=""
  fi
fi

if [[ -n "$SITE" ]]; then
  _prune_dir "$SITE" "${SITE_PRUNE[@]}"
fi

echo "prune complete"
