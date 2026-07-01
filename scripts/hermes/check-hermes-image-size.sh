#!/usr/bin/env bash
# Fail when a built hermes-base image exceeds HERMES_IMAGE_MAX_MIB (default 1200).
set -euo pipefail

IMAGE="${1:-}"
if [[ -z "$IMAGE" ]]; then
  echo "usage: $0 <image-ref>" >&2
  exit 2
fi

MAX_MIB="${HERMES_IMAGE_MAX_MIB:-1200}"
MAX_BYTES=$((MAX_MIB * 1024 * 1024))

if [[ -n "${HERMES_IMAGE_SIZE_BYTES:-}" ]]; then
  SIZE="$HERMES_IMAGE_SIZE_BYTES"
else
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker not found — set HERMES_IMAGE_SIZE_BYTES for offline checks" >&2
    exit 2
  fi
  SIZE="$(docker image inspect "$IMAGE" --format='{{.Size}}')"
fi

if [[ -z "$SIZE" || ! "$SIZE" =~ ^[0-9]+$ ]]; then
  echo "could not read image size for $IMAGE" >&2
  exit 2
fi

SIZE_MIB=$((SIZE / 1024 / 1024))
echo "Image $IMAGE: ${SIZE_MIB} MiB (limit ${MAX_MIB} MiB)"

if (( SIZE > MAX_BYTES )); then
  echo "Image size ${SIZE_MIB} MiB exceeds limit ${MAX_MIB} MiB" >&2
  exit 1
fi

echo "Image size OK"
