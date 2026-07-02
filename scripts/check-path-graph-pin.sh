#!/usr/bin/env bash
# Verify agents-runtime path-graph wheel pin matches latest GitHub release tag.
set -euo pipefail

REPO="${GITHUB_REPOSITORY_OWNER:-yoosungung}/path-graph"
LATEST_TAG="$(gh release view --repo "$REPO" --json tagName -q .tagName)"
LATEST_VERSION="${LATEST_TAG#v}"

PIN_FILE="deploy/tests/test_path_graph_dependency.py"
PIN_VERSION="$(python3 -c "import re; t=open('$PIN_FILE').read(); m=re.search(r'PATH_GRAPH_VERSION = \"([^\"]+)\"', t); print(m.group(1) if m else '')")"

if [ -z "$PIN_VERSION" ]; then
  echo "Could not read PATH_GRAPH_VERSION from $PIN_FILE" >&2
  exit 1
fi

if [ "$PIN_VERSION" != "$LATEST_VERSION" ]; then
  echo "path-graph pin $PIN_VERSION != latest release $LATEST_VERSION ($LATEST_TAG)" >&2
  echo "Bump backend/pyproject.toml, path-graph-rag-mcp Dockerfile, and $PIN_FILE" >&2
  exit 1
fi

echo "path-graph pin matches latest release: $LATEST_TAG"
