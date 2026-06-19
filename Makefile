REGISTRY  ?= ghcr.io/yoosungung/agent-runtime
TAG       ?= latest
NAMESPACE ?= runtime
GIT_REPO  ?= https://github.com/yoosungung/agent-studio.git
GIT_REF   ?= main
S3_BUCKET ?= agent-bundles

KANIKO := GIT_REPO=$(GIT_REPO) GIT_REF=$(GIT_REF) NAMESPACE=$(NAMESPACE) scripts/kaniko-build.sh

.PHONY: help sync lint typecheck test fmt \
        images registry-secret ncr-secret git-secret s3-secret jwt-secret ensure-jwt-secret ensure-namespace \
        ext-authz-image auth-image deploy-api-image \
        agent-base-image mcp-base-image backend-image \
        k8s-apply-dev k8s-apply-stage k8s-apply-prod k8s-delete-dev \
        k8s-rollout-restart k8s-redeploy-dev \
        db-migrate db-migrate-all \
        diagram diagram-png

help:
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## uv sync with dev deps
	uv sync --all-packages

lint: ## ruff check
	uv run ruff check .

fmt: ## ruff format
	uv run ruff format .

typecheck: ## mypy
	uv run mypy packages services runtimes

test: ## pytest
	uv run pytest

# --- images (deprecated: use GitHub Release → .github/workflows/build-images.yml) ---

IMG_EXT_AUTHZ     := $(REGISTRY)/ext-authz:$(TAG)
IMG_AUTH          := $(REGISTRY)/auth:$(TAG)
IMG_DEPLOY_API    := $(REGISTRY)/deploy-api:$(TAG)
IMG_AGENT_BASE    := $(REGISTRY)/agent-base:$(TAG)
IMG_MCP_BASE      := $(REGISTRY)/mcp-base:$(TAG)

ext-authz-image: ## [deprecated] build ext-authz via Kaniko — use GHA release workflow
	$(KANIKO) services/ext-authz/Dockerfile $(IMG_EXT_AUTHZ)

auth-image: ## [deprecated] build auth via Kaniko
	$(KANIKO) services/auth/Dockerfile $(IMG_AUTH)

deploy-api-image: ## [deprecated] build deploy-api via Kaniko
	$(KANIKO) services/deploy-api/Dockerfile $(IMG_DEPLOY_API)

agent-base-image: ## [deprecated] build agent-base via Kaniko
	$(KANIKO) runtimes/agent-base/Dockerfile $(IMG_AGENT_BASE)

mcp-base-image: ## [deprecated] build mcp-base via Kaniko
	$(KANIKO) runtimes/mcp-base/Dockerfile $(IMG_MCP_BASE)

IMG_BACKEND       := $(REGISTRY)/backend:$(TAG)

backend-image: ## [deprecated] build backend via Kaniko
	$(KANIKO) backend/Dockerfile $(IMG_BACKEND)

images: ext-authz-image auth-image deploy-api-image agent-base-image mcp-base-image backend-image ## [deprecated] Kaniko — use GHA release workflow

registry-secret: ## create/update GHCR pull secret (GITHUB_USER= GITHUB_PAT=)
	kubectl create secret docker-registry registry-creds \
		--namespace $(NAMESPACE) \
		--docker-server=ghcr.io \
		--docker-username=$(GITHUB_USER) \
		--docker-password=$(GITHUB_PAT) \
		--dry-run=client -o yaml | kubectl apply -f -

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

git-secret: ## create/update GitHub token secret for Kaniko  (GIT_TOKEN=<token> make git-secret)
	kubectl create secret generic git-creds \
		--namespace $(NAMESPACE) \
		--from-literal=token=$(GIT_TOKEN) \
		--dry-run=client -o yaml | kubectl apply -f -

ncr-secret: registry-secret ## deprecated alias — use registry-secret (GHCR)

s3-secret: ## create/update S3 credentials secret from .s3-config.json  (S3_BUCKET=<bucket> make s3-secret)
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

k8s-apply-dev: ensure-jwt-secret ## apply dev overlay (auto-generates jwt-keys if absent)
	kubectl apply -k deploy/k8s/overlays/dev

k8s-apply-stage: ensure-jwt-secret
	kubectl apply -k deploy/k8s/overlays/stage

k8s-apply-prod: ensure-jwt-secret
	kubectl apply -k deploy/k8s/overlays/prod

k8s-delete-dev:
	kubectl delete -k deploy/k8s/overlays/dev

k8s-rollout-restart: ## rolling restart all Deployments in $(NAMESPACE) (picks up new :latest images)
	kubectl -n $(NAMESPACE) rollout restart deployment

k8s-redeploy-dev: k8s-apply-dev k8s-rollout-restart ## apply dev overlay → rollout (images from GHCR via GHA release)

# --- db -------------------------------------------------------------------

db-migrate: ## apply 0001_init.sql to dev postgres
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0001_init.sql

db-migrate-all: db-migrate ## apply 0001 + 0002 + 0003 migrations
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0002_custom_image_mode.sql
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0003_general_and_vfs.sql

# --- docs -----------------------------------------------------------------

diagram: ## render agent-runtime.d2 → SVG
	d2 agent-runtime.d2 agent-runtime.svg

diagram-png: ## render agent-runtime.d2 → PNG (requires headless chrome)
	d2 agent-runtime.d2 agent-runtime.png
