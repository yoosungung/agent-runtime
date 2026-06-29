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
10. `run_conversation(...)` (thread pool)
11. `await vfs_sync.push(agent_name, scratch, manifest)`
12. `profile_lock.release()`

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
- `push`: manifest 대비 mtime/size 변경 파일만 `store.write`
- `seed_from_config`: backend 등록 API와 동일 로직 (pool에서 config가 더 새일 때)

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
| `VFS_DSN` | **필수** — `AsyncpgAgentVfsStore` |
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

### Runtime-slim OCI (예정 — [ROADMAP.md](../../ROADMAP.md) P1)

풀 `hermes-agent` 설치는 gateway·CLI·plugins 코드와 불필요한 core deps까지 이미지에 포함한다. pool은 `AIAgent` library embed만 사용.

- extras `[all]` / `[gateway]` / `[web]` / `[messaging]` 금지
- multi-stage Dockerfile + (선택) site-packages prune
- 장기: `hermes-agent[runtime]` optional-extra 또는 upstream 기여

## Commands

```bash
uv sync --all-packages
uv run pytest runtimes/hermes-base/tests -q
uv run uvicorn hermes_base.app:app --reload --port 8081
```
