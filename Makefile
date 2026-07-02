REGISTRY  ?= ghcr.io/yoosungung/agent-runtime
GHCR_USER ?= $(shell echo $(REGISTRY) | cut -d/ -f2)
NAMESPACE ?= runtime
S3_BUCKET ?= agent-bundles
IMAGE_TAG ?= $(shell git rev-parse HEAD)

.PHONY: help sync lint typecheck test fmt \
        registry-secret ensure-registry-secret _bootstrap-registry-secret \
        ncr-secret s3-secret jwt-secret ensure-jwt-secret ensure-namespace \
        k8s-apply-garage k8s-apply-dev k8s-apply-stage k8s-apply-prod k8s-delete-dev \
        k8s-rollout-restart k8s-redeploy-dev build-images build-images-wait \
        build-path-graph-rag-mcp build-path-graph-rag-mcp-wait \
        db-migrate db-migrate-all \
        diagram diagram-png

help:
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## uv sync with dev deps (path-graph release wheel; sibling dev: uv.override.toml)
	uv sync --all-packages

lint: ## ruff check
	uv run ruff check .

fmt: ## ruff format
	uv run ruff format .

typecheck: ## mypy
	uv run mypy packages services runtimes

test: ## pytest
	uv run pytest

registry-secret: ensure-namespace ## create/update GHCR pull secret (GITHUB_USER= GITHUB_PAT=)
	@test -n "$(GITHUB_USER)" -a -n "$(GITHUB_PAT)" \
		|| { echo "error: GITHUB_USER and GITHUB_PAT required" >&2; exit 1; }
	@kubectl create secret docker-registry registry-creds \
		--namespace $(NAMESPACE) \
		--docker-server=ghcr.io \
		--docker-username=$(GITHUB_USER) \
		--docker-password=$(GITHUB_PAT) \
		--dry-run=client -o yaml | kubectl apply -f -

ensure-registry-secret: ensure-namespace ## create registry-creds if absent (GITHUB_USER/PAT or gh auth for GHCR_USER)
	@kubectl -n $(NAMESPACE) get secret registry-creds >/dev/null 2>&1 \
		&& echo "registry-creds already exists, skipping" \
		|| $(MAKE) _bootstrap-registry-secret

_bootstrap-registry-secret:
	@set -e; \
	if [ -n "$(GITHUB_USER)" ] && [ -n "$(GITHUB_PAT)" ]; then \
		$(MAKE) registry-secret GITHUB_USER="$(GITHUB_USER)" GITHUB_PAT="$(GITHUB_PAT)"; \
	elif command -v gh >/dev/null 2>&1; then \
		token=$$(gh auth token --user $(GHCR_USER) 2>/dev/null || gh auth token 2>/dev/null || true); \
		if [ -n "$$token" ]; then \
			echo "registry-creds missing — creating from gh auth (user=$(GHCR_USER))"; \
			$(MAKE) registry-secret GITHUB_USER="$(GHCR_USER)" GITHUB_PAT="$$token"; \
		else \
			echo "WARNING: registry-creds missing and gh auth unavailable. Run: GITHUB_USER=... GITHUB_PAT=... make registry-secret" >&2; \
		fi; \
	else \
		echo "WARNING: registry-creds missing. Run: GITHUB_USER=... GITHUB_PAT=... make registry-secret" >&2; \
	fi

jwt-secret: ## generate RS4096 keypair and create/update jwt-keys secret (overwrites existing)
	openssl genrsa -out /tmp/jwt.key 4096 2>/dev/null
	openssl rsa -in /tmp/jwt.key -pubout -out /tmp/jwt.pub 2>/dev/null
	kubectl create secret generic jwt-keys \
		--namespace $(NAMESPACE) \
		--from-file=JWT_PRIVATE_KEY=/tmp/jwt.key \
		--from-file=JWT_PUBLIC_KEY=/tmp/jwt.pub \
		--dry-run=client -o yaml | kubectl apply -f -
	rm -f /tmp/jwt.key /tmp/jwt.pub

ensure-namespace: ## create runtime namespace if missing (first deploy)
	@kubectl get ns $(NAMESPACE) >/dev/null 2>&1 \
		|| kubectl apply -f deploy/k8s/base/namespace.yaml

ensure-jwt-secret: ensure-namespace ## create jwt-keys secret only if it does not already exist (idempotent)
	@kubectl -n $(NAMESPACE) get secret jwt-keys >/dev/null 2>&1 \
		&& echo "jwt-keys already exists, skipping key generation" \
		|| $(MAKE) jwt-secret

ncr-secret: registry-secret ## deprecated alias — use registry-secret (GHCR)

s3-secret: ## override embedded Garage with external S3 (.s3-config.json + S3_BUCKET=)
	kubectl create secret generic s3-creds \
		--namespace $(NAMESPACE) \
		--from-literal=BUNDLE_STORAGE_BACKEND=s3 \
		--from-literal=S3_BUCKET=$(S3_BUCKET) \
		--from-literal=S3_ENDPOINT_URL=$(shell jq -r .endpoint_url .s3-config.json) \
		--from-literal=S3_REGION=$(shell jq -r .region_name .s3-config.json) \
		--from-literal=S3_PREFIX=bundles/ \
		--from-literal=S3_ACCESS_KEY_ID=$(shell jq -r .access_key .s3-config.json) \
		--from-literal=S3_SECRET_ACCESS_KEY=$(shell jq -r .secret_key .s3-config.json) \
		--dry-run=client -o yaml | kubectl apply -f -

# --- k8s ------------------------------------------------------------------

# Substitute __IMAGE_TAG__ placeholder from deploy/k8s/components/ghcr-images (git SHA by default).
define K8S_APPLY_OVERLAY
	kubectl kustomize deploy/k8s/overlays/$(1) \
		| sed 's/__IMAGE_TAG__/$(IMAGE_TAG)/g' \
		| kubectl apply -f -
endef

k8s-apply-garage: ## apply embedded Garage object store only (namespace: runtime; also in base overlay)
	kubectl apply -k deploy/k8s/garage

k8s-apply-dev: ensure-jwt-secret ensure-registry-secret ## apply dev overlay (IMAGE_TAG=$(IMAGE_TAG))
	$(call K8S_APPLY_OVERLAY,dev)

k8s-apply-stage: ensure-jwt-secret ensure-registry-secret
	$(call K8S_APPLY_OVERLAY,stage)

k8s-apply-prod: ensure-jwt-secret ensure-registry-secret
	$(call K8S_APPLY_OVERLAY,prod)

k8s-delete-dev:
	kubectl delete -k deploy/k8s/overlays/dev

k8s-rollout-restart: ## rolling restart all Deployments in $(NAMESPACE) (same image tag — prefer k8s-apply-* with new IMAGE_TAG)
	kubectl -n $(NAMESPACE) rollout restart deployment

k8s-redeploy-dev: build-images-wait k8s-apply-dev ## build images for current HEAD → apply dev overlay

REF ?= main
build-images: ## trigger GHA build-images workflow (push REF first; tags GHCR with commit SHA only)
	gh workflow run "Build and push images" --ref $(REF)
	@echo "Triggered. Watch: gh run list --workflow=build-images.yml --limit=1"

build-images-wait: ## wait for the latest build-images workflow run to finish
	@run_id=$$(gh run list --workflow=build-images.yml --limit=1 --json databaseId --jq '.[0].databaseId'); \
	gh run watch "$$run_id"

build-path-graph-rag-mcp: ## trigger GHA path-graph-rag-mcp only (faster than full build-images)
	gh workflow run "path-graph-rag-mcp" --ref $(REF)
	@echo "Triggered. Watch: gh run list --workflow=path-graph-rag-mcp.yml --limit=1"

build-path-graph-rag-mcp-wait: ## wait for the latest path-graph-rag-mcp workflow run
	@run_id=$$(gh run list --workflow=path-graph-rag-mcp.yml --limit=1 --json databaseId --jq '.[0].databaseId'); \
	gh run watch "$$run_id"

# --- db -------------------------------------------------------------------

db-migrate: ## apply 0001_init.sql to dev postgres
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0001_init.sql

db-migrate-all: db-migrate ## apply 0001 … 0011 for existing DBs
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0002_vfs.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0003_user_meta_template.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0004_general_visibility.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0005_llm_presets.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0006_chat_threads.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0007_api_keys_user_id.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0008_chat_threads_agent_version.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0009_users_tenant_not_null.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0010_hermes_general.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0011_chat_selectable.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0012_llm_preset_context.sql

# --- docs -----------------------------------------------------------------

diagram: ## render agent-runtime.d2 → SVG
	d2 agent-runtime.d2 agent-runtime.svg

diagram-png: ## render agent-runtime.d2 → PNG (requires headless chrome)
	d2 agent-runtime.d2 agent-runtime.png
