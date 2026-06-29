#!/usr/bin/env bash
# Remove hermes-agent packages not needed for pool /invoke (AIAgent embed only).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE="${1:-}"

if [[ -z "$SITE" ]]; then
  SITE="$ROOT/.venv/lib/python3.12/site-packages"
  if [[ -d "$ROOT/vendor/hermes-agent/src" ]]; then
  for pkg in gateway hermes_cli tui_gateway acp_adapter; do
    TARGET="$ROOT/vendor/hermes-agent/src/$pkg"
    if [[ -d "$TARGET" ]]; then
      rm -rf "$TARGET"
      echo "pruned vendor/$pkg"
    fi
  done
  fi
fi

for pkg in gateway hermes_cli tui_gateway acp_adapter; do
  TARGET="$SITE/$pkg"
  if [[ -d "$TARGET" ]]; then
    rm -rf "$TARGET"
    echo "pruned site-packages/$pkg"
  fi
done

echo "prune complete"
