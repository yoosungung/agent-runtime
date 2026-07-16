#!/usr/bin/env bash
# Expand a git ref / short SHA to the full commit SHA when resolvable.
# Non-git tags (e.g. admin-spa-*) pass through unchanged.
set -euo pipefail

tag=${1:?usage: resolve-image-tag.sh <tag-or-ref>}

if resolved=$(git rev-parse --verify "${tag}^{commit}" 2>/dev/null); then
  printf '%s\n' "$resolved"
else
  printf '%s\n' "$tag"
fi
