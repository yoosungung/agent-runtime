REGISTRY  ?= ax1-images.kr.ncr.ntruss.com
TAG       ?= latest
NAMESPACE ?= runtime
GIT_REPO  ?= https://github.com/yoosungung/agent-studio.git
GIT_REF   ?= main
S3_BUCKET ?= agent-bundles

KANIKO := GIT_REPO=$(GIT_REPO) GIT_REF=$(GIT_REF) NAMESPACE=$(NAMESPACE) scripts/kaniko-build.sh

.PHONY: help sync lint typecheck test fmt \
        images ncr-secret git-secret s3-secret jwt-secret \
        ext-authz-image auth-image deploy-api-image \
        agent-base-image mcp-base-image backend-image \
        k8s-apply-dev k8s-apply-stage k8s-apply-prod k8s-delete-dev \
        k8s-rollout-restart k8s-redeploy-dev \
        db-migrate \
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

# --- images ---------------------------------------------------------------

IMG_EXT_AUTHZ     := $(REGISTRY)/ext-authz:$(TAG)
IMG_AUTH          := $(REGISTRY)/auth:$(TAG)
IMG_DEPLOY_API    := $(REGISTRY)/deploy-api:$(TAG)
IMG_AGENT_BASE    := $(REGISTRY)/agent-base:$(TAG)
IMG_MCP_BASE      := $(REGISTRY)/mcp-base:$(TAG)

ext-authz-image: ## build ext-authz image via Kaniko
	$(KANIKO) services/ext-authz/Dockerfile $(IMG_EXT_AUTHZ)

auth-image: ## build auth image via Kaniko
	$(KANIKO) services/auth/Dockerfile $(IMG_AUTH)

deploy-api-image: ## build deploy-api image via Kaniko
	$(KANIKO) services/deploy-api/Dockerfile $(IMG_DEPLOY_API)

agent-base-image: ## build agent-base image via Kaniko
	$(KANIKO) runtimes/agent-base/Dockerfile $(IMG_AGENT_BASE)

mcp-base-image: ## build mcp-base image via Kaniko
	$(KANIKO) runtimes/mcp-base/Dockerfile $(IMG_MCP_BASE)

IMG_BACKEND       := $(REGISTRY)/backend:$(TAG)

backend-image: ## build backend (admin console BFF + SPA) image via Kaniko
	$(KANIKO) backend/Dockerfile $(IMG_BACKEND)

images: ext-authz-image auth-image deploy-api-image agent-base-image mcp-base-image backend-image ## build all images via Kaniko

jwt-secret: ## generate RS4096 keypair and create/update jwt-keys secret
	openssl genrsa -out /tmp/jwt.key 4096 2>/dev/null
	openssl rsa -in /tmp/jwt.key -pubout -out /tmp/jwt.pub 2>/dev/null
	kubectl create secret generic jwt-keys \
		--namespace $(NAMESPACE) \
		--from-file=JWT_PRIVATE_KEY=/tmp/jwt.key \
		--from-file=JWT_PUBLIC_KEY=/tmp/jwt.pub \
		--dry-run=client -o yaml | kubectl apply -f -
	rm -f /tmp/jwt.key /tmp/jwt.pub

git-secret: ## create/update GitHub token secret  (GIT_TOKEN=<token> make git-secret)
	kubectl create secret generic git-creds \
		--namespace $(NAMESPACE) \
		--from-literal=token=$(GIT_TOKEN) \
		--dry-run=client -o yaml | kubectl apply -f -

ncr-secret: ## create/update NCR push secret from .ncr-config.json
	kubectl create secret generic ncr-creds \
		--namespace $(NAMESPACE) \
		--from-file=.dockerconfigjson=.ncr-config.json \
		--type=kubernetes.io/dockerconfigjson \
		--dry-run=client -o yaml | kubectl apply -f -

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

k8s-apply-dev: ## apply dev overlay
	kubectl apply -k deploy/k8s/overlays/dev

k8s-apply-stage:
	kubectl apply -k deploy/k8s/overlays/stage

k8s-apply-prod:
	kubectl apply -k deploy/k8s/overlays/prod

k8s-delete-dev:
	kubectl delete -k deploy/k8s/overlays/dev

k8s-rollout-restart: ## rolling restart all Deployments in $(NAMESPACE) (picks up new :latest images)
	kubectl -n $(NAMESPACE) rollout restart deployment

k8s-redeploy-dev: images k8s-apply-dev k8s-rollout-restart ## build all images → apply dev → rollout restart

# --- db -------------------------------------------------------------------

db-migrate: ## apply SQL migrations to the dev postgres
	kubectl -n $(NAMESPACE) exec -i statefulset/postgres -- \
		psql -U runtime -d runtime < backend/migrations/0001_init.sql

# --- docs -----------------------------------------------------------------

diagram: ## render agent-runtime.d2 → SVG
	d2 agent-runtime.d2 agent-runtime.svg

diagram-png: ## render agent-runtime.d2 → PNG (requires headless chrome)
	d2 agent-runtime.d2 agent-runtime.png
