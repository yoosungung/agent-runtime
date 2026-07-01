# Hermes Profile General 통합 가이드

Hermes profile tier(`deploy_mode=hermes_general`)의 agents-runtime monorepo 구성·검증 체크리스트.

## VFS (확정)

Profile 정본: `AsyncpgAgentVfsStore`, `kind='agent'`, `agent_name=source_meta.name`, 경로 prefix `/profile/`.

상세: [vfs-profile-design.md](vfs-profile-design.md)

---

## 1. packages/common

- `AgentRuntimeKind.HERMES = "hermes"`
- `HermesGeneralSourceConfig` in `config_schema.py`
- `source_instance_key`: `hermes:{name}:{version}`
- (변경 없음) `AsyncpgAgentVfsStore` / `AsyncpgUserVfsStore` 재사용

## 2. backend

### `POST /api/source-meta/hermes-general`

1. `source_meta` INSERT
2. **VFS seed** (`vfs_agent_files`):

```python
await agent_vfs.write("agent", name, "/profile/SOUL.md", body.soul)
await agent_vfs.write("agent", name, "/profile/config.yaml", render_hermes_yaml(cfg))
for skill in body.skills:
    await agent_vfs.write("agent", name, f"/profile/skills/{skill}/SKILL.md", bundled_skill_content(skill))
```

3. Admin `/vfs/agents/agent/{name}` — general agent VFS UI 재사용 (경로 `/profile/…` 안내)

### `PATCH /api/source-meta/hermes-general/{id}`

- `soul` / `skills` / `mcp_servers` / `model` / `visibility` / `config` — partial update (`exclude_none`)
- config rebuild 시 MCP catalog 재조회 → `_build_hermes_config`
- VFS upsert: `ProfileVfsSync.seed_from_config` (+ skills marker prune)
- SPA: `HermesAgentDetailPage` 편집 + `usePatchHermesAgent`

### migration

```sql
CHECK (deploy_mode IN ('bundle', 'image', 'general', 'hermes_general'));
```

## 3. runtimes/hermes-base

- `VFS_DSN` 필수, `create_asyncpg_pool` + `ProfileVfsSync` + `UserProfileVfsSync`
- `HERMES_WORK_DIR` emptyDir
- `profile_lock` Redis
- `agent_bridge.py` — delegate agent invoke-internal (orchestrator Hermes)

## 4. ext-authz / frontend / deploy

### ext-authz pool routing

- `runtime_pool=agent:hermes` → `Settings.agent_pool_url("hermes")` → `POOL_HERMES_URL`
- `deploy/k8s/base/ext-authz.yaml`: `POOL_HERMES_URL` env
- `deploy/k8s/base/agent-pool-hermes.yaml` + kustomization (**PVC 제거**)
- `checksum=NULL` (general tier와 동일) — warm-registry miss 시 pool ClusterIP Service로 라우팅
- 테스트: `services/ext-authz/tests/test_ext_authz.py::TestHermesAgentInvoke`

### build-images CI

[`.github/workflows/build-images.yml`](../.github/workflows/build-images.yml):

- matrix에 `hermes-base` 포함 → `ghcr.io/<owner>/agent-runtime/hermes-base:<git-sha>`
- `hermes-gates` job: install policy + OCI unit tests
- hermes-base 빌드: `GIT_SHA` / `HERMES_REVISION` build-arg + **1200 MiB** size gate

PR/push 검증: [`.github/workflows/hermes-base-oci.yml`](../.github/workflows/hermes-base-oci.yml).

스크립트: `scripts/hermes/check-hermes-install-policy.sh`, `check-hermes-image-size.sh`, `vendor-hermes.sh`

- **SPA**: `/agents/hermes` · `/agents/new/hermes` · `/agents/hermes/:id` — `HermesAgentNewPage`, `HermesAgentDetailPage`, `useCreateHermesAgent`

## 5. 검증 시나리오

1. 등록 → VFS에 `/profile/SOUL.md` 존재 (admin VFS UI)
2. Pod A invoke → memory 턴
3. Pod B invoke → VFS `memories/MEMORY.md` 반영·세션 연속
4. `skill_manage`로 skill 추가 → push → Pod B에서 `skills/` visible
5. 동시 invoke 동일 agent → 429 또는 lock 대기
6. 사용자별 `USER.md` → user VFS `/hermes/{agent}/memories/USER.md`

**멀티 pod E2E (wire-dev, LLM 없이)**: `test_multipod_wire.py` — Pod A/B 별도 scratch로 VFS memory·session DSN 연속성 검증

## 6. wire-dev E2E (로컬 Mac → dev k8s)

저장소 루트에서 port-forward·env 생성:

```bash
./scripts/wire-dev.sh up          # postgres:5432, redis:6379, envoy:8084
./scripts/wire-dev.sh env         # .env.dev.local
```

통합 테스트:

```bash
uv sync --all-packages
uv run pytest runtimes/hermes-base/tests -m integration -v
```

- `VFS_DSN` / `HERMES_SESSION_DSN`: wire-dev가 쓰는 dev Postgres (`runtime` DB)
- env 탐색: `HERMES_WIRE_DEV_ENV` → `.env.dev.local`
- 풀 로컬 디버그: `./scripts/wire-dev.sh pool-isolate hermes` → `:8095/invoke`
- 단위 테스트(mock VFS): `uv run pytest runtimes/hermes-base/tests -q -m "not integration"`

## 7. vendor/hermes-agent

upstream [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) main + `vendor/hermes-agent/patches/`.  
로컬 개발: `./scripts/hermes/vendor-hermes.sh`. OCI 빌드 시 Dockerfile vendor stage에서 clone.

상세: [vendor/hermes-agent/DESIGN.md](../vendor/hermes-agent/DESIGN.md)
