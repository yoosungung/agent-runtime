# hermes-base

agents-runtime **Hermes Profile General** tier용 pool. Profile 정본은 **Postgres VFS** — [docs/vfs-profile-design.md](../../docs/vfs-profile-design.md).

> **범위**: `RUNTIME_KIND=hermes`, `deploy_mode='hermes_general'`.

## 설계

### General tier 대비

| | `agent-base` general | `hermes-base` |
|---|---------------------|---------------|
| Factory | `build_general_agent()` → DeepAgents | `build_hermes_agent()` → `AIAgent` |
| 페르소나 | `config.general.system_prompt` | VFS `/profile/SOUL.md` |
| MCP | LangChain → Envoy | `runtime_mcp` → Envoy |
| 파일 저장 | VFS → DeepAgents `backend` | VFS → **pull/scratch/push** → `HERMES_HOME` |
| 세션 | LangGraph Postgres checkpointer | Hermes SessionDB Postgres |
| LLM | `prepare_langgraph_llm(cfg)` — `preset:NAME` / `DEFAULT_LLM_MODEL` | `resolve_hermes_llm_binding(cfg)` — preset·platform default; `openai_compatible`/커스텀 `OPENAI_API_BASE`는 `provider=custom` + explicit credentials, `context_length` ≥ 65536 |

### `/invoke` 처리

1. `resolve_for_invoke()` 
2. `deploy_mode != 'hermes_general'` → 400
3. `principal.user_id` 필수
4. `await profile_lock.acquire(agent_name)` — 실패 시 429
5. `scratch = work_dir / agent_name / {invoke_id}`
6. `await vfs_sync.pull(agent_name, scratch)`
7. `await vfs_sync.seed_from_config(agent_name, merged_cfg)` — fingerprint 불일치 시
8. `profile_runtime_scope(scratch)` 
9. `instance = await get_or_build_hermes_agent(...)`
10. `run_conversation(...)` (thread pool) — `stream: true` 시 `stream_callback` + SSE (`hermes_stream.py`)
11. `await vfs_sync.push(agent_name, scratch, manifest)` — agent VFS (`USER.md` 제외)
11b. `await user_vfs_sync.push(user_id, agent_name, scratch, user_manifest)`
12. `profile_lock.release()`

**UserVfs**

| 항목 | 구현 |
|------|------|
| 경로 | user VFS `/hermes/{agent}/memories/USER.md` ↔ scratch `memories/USER.md` |
| pull | agent pull 후 `UserProfileVfsSync.pull_overlay` — user 파일 있으면 덮어씀 |
| push | `USER.md`만 user VFS; `MEMORY.md` 등은 agent VFS |
| fallback | user 파일 없으면 agent VFS 시드 `USER.md` 유지 |

**P4 Gateway (확정: Chat UI only)**

agents-runtime SPA Chat이 유일 진입점. hermes-agent gateway/TUI/ACP는 pool 이미지에 미포함.

**P3 hardening**

| 항목 | 구현 |
|------|------|
| SSE | `POST /invoke` + `stream: true` → `text/event-stream`, `data: {"text":…}`, `[DONE]`. Chat SPA `chatStream.ts` 호환 |
| Opik | `OPIK_URL` → `configure_opik` lifespan; invoke/stream에 `opik_trace_context` |
| push 충돌 | `PullFileState.vfs_modified_at` vs push 시점 VFS 재조회 → `ProfileVfsConflictError` (409 JSON / SSE error) |
| 감사 | pool structured log `vfs_push_conflict`, `invoke_vfs_conflict` (backend `audit_log`는 별도) |

### ProfileVfsSync

```python
PROFILE_PREFIX = "/profile"

class ProfileVfsSync:
    kind: str = "agent"

    async def pull(self, agent_name: str, dest: Path) -> PullManifest: ...
    async def push(self, agent_name: str, src: Path, manifest: PullManifest) -> PushStats: ...
    async def seed_from_config(
        self, agent_name: str, cfg: dict, *, session_dsn: str | None, overwrite: bool = False
    ) -> None: ...
```

- `pull`: `store.glob(kind, name, "/profile/**")` → scratch에 mirror
- `push`: manifest `PullFileState`(scratch mtime + vfs `modified_at`) 대비 dirty 파일만 write; VFS 버전 불일치 → `ProfileVfsConflictError`
- `seed_from_config`: backend 등록 API와 동일 로직 (pool에서 config가 더 새일 때)

### Agent delegate bridge

`hermes_base/agent_bridge.py` — orchestrator Hermes agent가 delegate agent를 호출할 때 `POST /v1/agents/invoke-internal` JWT forward (`agent-base` delegate 패턴 대칭).

### ProfileMaterializer

scratch 디렉터리에 **파일 쓰기**만 담당 (`pull`/`seed`의 구현 세부).  
로컬 fingerprint: `scratch/.runtime-meta.json`.

### get_or_build_hermes_agent

캐시 키 `hermes:{name}:{version}` × `user_id` × `user.updated_at`.  
VFS fingerprint 변경 시 `InstanceCache.invalidate_checksum` 또는 config PATCH 시 무효화.

### MCP Bridge

`hermes_base/mcp_bridge.py` — `agent_base.mcp_tools` 패턴.

### 환경 변수

| 변수 | 설명 |
|------|------|
| `VFS_DSN` | **필수** — `AsyncpgAgentVfsStore` + `AsyncpgUserVfsStore` |
| `HERMES_WORK_DIR` | scratch emptyDir (default `/var/cache/hermes-work`) |
| `HERMES_SESSION_DSN` | Hermes SessionDB Postgres |
| `REDIS_URL` | profile lock + warm-registry |
| `MCP_GATEWAY_URL` | Envoy |
| `PROFILE_LOCK_TTL_SEC` | lock TTL (default invoke_timeout + 30) |

**없음**: `HERMES_PROFILES_ROOT`, profile PVC.

### 동시 invoke

- 동일 `agent_name`: Redis lock → 한 번에 한 invoke
- 다른 agent: 병렬 OK
- pod A → pod B: VFS + SessionDB Postgres로 상태 공유

### Runtime-slim OCI

pool은 `AIAgent` library embed만 사용 — gateway·CLI·TUI·ACP adapter는 **이미지에 포함하지 않는다**.

#### 설치 정책

| 허용 | 금지 |
|------|------|
| `uv pip install -e ./vendor/hermes-agent/src` (core only) | `hermes-agent[all]` |
| `scripts/hermes/prune-hermes-packages.sh` (vendor + site-packages) | `hermes-agent[gateway]` / `[web]` / `[messaging]` |
| `uv sync --package hermes-base --no-dev` | `pip install hermes-agent[...]` with fat extras |

CI: `scripts/hermes/check-hermes-install-policy.sh` — Dockerfile·vendor 스크립트 grep.

#### Dockerfile (multi-stage)

```text
vendor  — git clone hermes-agent main → apply patches → prune vendor tree
base    — uv sync hermes-base → editable install → prune site-packages → import smoke
```

```bash
docker build -f runtimes/hermes-base/Dockerfile -t hermes-base:local .
bash scripts/hermes/check-hermes-image-size.sh hermes-base:local   # default max 1200 MiB
```

Prune 대상 (vendor + site-packages): `gateway`, `tui_gateway`, `acp_adapter`.  
`hermes_cli`는 `run_agent` module import에 필요 — **prune하지 않음**.

#### 이미지 크기 gate

`HERMES_IMAGE_MAX_MIB` (default `1200`) — CI `.github/workflows/hermes-base-oci.yml`에서 빌드 후 검증.

#### 장기 (선택)

upstream `hermes-agent[runtime]` optional-extra — SessionDB + `run_agent` deps만. 현재는 core + prune.

## wire-dev E2E (VFS + SessionDB)

로컬 Mac 프로세스를 dev k8s `runtime` 네임스페이스 Postgres/Redis에 연결한다.

| 변수 | wire-dev 값 |
|------|-------------|
| `VFS_DSN` | `postgresql://runtime:runtime@127.0.0.1:5432/runtime?sslmode=disable` |
| `HERMES_SESSION_DSN` | 동일 (Hermes `sessions.state_backend=postgres`) |
| `HERMES_WORK_DIR` | `.wire-dev/hermes-work` |
| `REDIS_URL` | `redis://127.0.0.1:6379` |
| `MCP_GATEWAY_URL` | `http://127.0.0.1:8084` |

```bash
# 저장소 루트
./scripts/wire-dev.sh up
./scripts/wire-dev.sh env    # → .env.dev.local

uv sync --all-packages
uv run pytest runtimes/hermes-base/tests -m integration -v
```

통합 fixture는 `.env.dev.local` 또는 `HERMES_WIRE_DEV_ENV`로 env를 로드. DSN이 없거나 Postgres unreachable이면 `@pytest.mark.integration` 테스트는 skip.

| 테스트 | 검증 |
|--------|------|
| `test_vfs_profile_wire.py` | real asyncpg VFS seed/pull/push |
| `test_session_wire.py` | `HERMES_SESSION_DSN` 연결 + config materialization |
| `test_multipod_wire.py` | Pod A/B scratch 분리 + VFS·session 연속성 |

풀 로컬 디버그: `./scripts/wire-dev.sh pool-isolate hermes` → cluster `agent-pool-hermes` scale 0, 로컬 `:8095/invoke`.

## Commands

```bash
uv sync --all-packages
uv run pytest runtimes/hermes-base/tests -q -m "not integration"
uv run uvicorn hermes_base.app:app --reload --port 8095
```

통합·배포 체크리스트: [docs/hermes-integration.md](../../docs/hermes-integration.md).
