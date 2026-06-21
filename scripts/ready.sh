#!/usr/bin/env bash
# Legacy dev wire — prefer scripts/wire-dev.sh
#
#   ./scripts/wire-dev.sh up --profile core   # postgres, redis, auth:8081, deploy-api, envoy
#   ./scripts/wire-dev.sh up --profile opik   # Opik observability
#   ./scripts/wire-dev.sh env                 # .env.dev.local for launch.json

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "ready.sh: use scripts/wire-dev.sh (see .vscode/launch.json)" >&2
exec "$ROOT/scripts/wire-dev.sh" up --profile legacy
