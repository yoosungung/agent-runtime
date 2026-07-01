# VFS Profile 저장 (확정)

Hermes profile의 **정본(canonical)** 은 agents-runtime **Postgres VFS** (`vfs_agent_files`).  
pod 로컬 디렉터리는 invoke 생명주기 동안만 쓰는 **scratch**이며 persist하지 않는다.

---

## 1. VFS 경로 규약

`AgentVfsStore` 스코프: `kind='agent'`, `agent_name=source_meta.name` (예: `my-special-hermes`).

profile 트리는 VFS 경로 `/profile/` 아래에 Hermes `HERMES_HOME`과 동일한 상대 구조를 mirror한다.

```text
/profile/SOUL.md
/profile/config.yaml
/profile/.runtime-meta.json          # fingerprint, hermes revision (sync 메타)
/profile/skills/{skill-name}/SKILL.md
/profile/memories/MEMORY.md
/profile/memories/USER.md
/profile/memories/*.md               # Hermes memory provider 파일
/profile/cron/…                      # (선택) cron job 정의
```

| 경로 | 쓰기 주체 | 비고 |
|------|-----------|------|
| `SOUL.md`, `config.yaml` | **등록/PATCH API** (backend) | `source_meta.config.hermes`와 동기 시드 |
| `skills/**` | 등록 API + **Hermes runtime** (`skill_manage`) | runtime 변경은 write-back |
| `memories/**` | **Hermes runtime** | 장기 메모리 pod 간 공유 핵심 |
| `.runtime-meta.json` | hermes-base sync | config fingerprint |

**User-scoped** (`UserVfsStore`, `user_id`):

```text
/hermes/{agent_name}/memories/USER.md   # 사용자별 프로필 (정본)
```

- `MEMORY.md` 및 기타 `memories/*.md`는 agent VFS (`/profile/…`)에 유지 — 에이전트 공유 지식.
- `USER.md`만 user VFS — invoke 시 scratch `memories/USER.md`에 overlay, push 시 agent VFS가 아닌 user VFS로 write-back.
- user 파일 없으면 agent VFS의 `/profile/memories/USER.md`(등록 시드)를 fallback으로 scratch에 남김; 첫 편집부터 user VFS 정본.

---

## 2. Invoke 생명주기 (pull → run → push)

```text
POST /invoke
  1. Redis lock:  rt:lock:hermes:profile:{agent_name}   (TTL = invoke_timeout + margin)
  2. pull:        agent VFS `/profile/**` → scratch; user VFS `/hermes/{agent}/memories/USER.md` overlay
  3. merge:       source_meta.config.hermes 변경분이 VFS보다 새면 seed 덮어쓰기 (등록 직후 1회)
  4. scope:       profile_runtime_scope(scratch_dir) + HERMES_SESSION_DSN (Postgres)
  5. build/run:   get_or_build_hermes_agent → run_conversation
  6. push:        scratch dirty → agent VFS (`memories/USER.md` 제외) + user VFS (`memories/USER.md`)
  7. unlock
```

- **Scratch**: `HERMES_WORK_DIR` (기본 `/var/cache/hermes-work`), pod `emptyDir` — **RWX PVC 없음**.
- **세션·메시지**: Hermes `SessionDB` → Postgres (`HERMES_SESSION_DSN`). VFS와 별도.
- **충돌**: 동일 agent에 동시 invoke는 Redis lock으로 직렬화. lock 실패 시 429 + retry-after.
- **VFS write-back 충돌 (P3)**: pull 시점 `vfs_modified_at`과 push 전 재조회 값이 다르면 `409` — 다른 pod/관리자가 중간에 VFS를 갱신한 경우.

---

## 3. 등록·수정 (backend)

`POST /api/source-meta/hermes-general`:

1. `source_meta` INSERT (`deploy_mode=hermes_general`)
2. **VFS seed** (트랜잭션):
   - `write agent/my-bot /profile/SOUL.md`
   - `write agent/my-bot /profile/config.yaml` (model, sessions, toolsets YAML)
   - bundled `skills[]` → `/profile/skills/{name}/SKILL.md` (이미지 내 번들에서 복사)
3. Admin **VFS UI** (`/vfs/agents/agent/{name}`)에서 동일 트리 편집 가능 (general agent와 동일 UX)

`PATCH /api/source-meta/hermes-general/{id}`:

- `soul` / `skills` 변경 시 VFS 갱신 + `hermes-base` `InstanceCache` 무효화 키 변경(config fingerprint)

---

## 4. 컴포넌트

| 모듈 | 역할 |
|------|------|
| `hermes_base.vfs_profile.ProfileVfsSync` | agent VFS pull / push (`memories/USER.md` 제외) |
| `hermes_base.user_vfs_profile.UserProfileVfsSync` | user VFS overlay pull / `USER.md` push |
| `hermes_base.profile_materializer` | scratch에 파일 쓰기 (pull 결과 + config seed) |
| `hermes_base.profile_lock` | Redis `SET NX` lock |
| `runtime_common.vfs.store.AsyncpgAgentVfsStore` | Postgres I/O (재사용) |

```python
class ProfileVfsSync:
    def __init__(self, store: AgentVfsStore, *, prefix: str = "/profile"): ...

    async def pull(self, agent_name: str, dest: Path) -> PullManifest: ...
    async def push(self, agent_name: str, src: Path, manifest: PullManifest) -> PushStats: ...
    async def seed_from_config(self, agent_name: str, cfg: dict, *, session_dsn: str | None) -> None: ...
```

`PullManifest`: `{path: vfs_modified_at}` — push 시 변경 감지.

---

## 5. 환경 변수 (hermes-base pod)

| 변수 | 필수 | 설명 |
|------|------|------|
| `VFS_DSN` | **예** | `AsyncpgAgentVfsStore` (general pool과 동일 secret) |
| `HERMES_WORK_DIR` | 예 | scratch emptyDir |
| `HERMES_SESSION_DSN` | 예 | Hermes SessionDB Postgres |
| `REDIS_URL` | 예 | profile lock + warm-registry |
| `MCP_GATEWAY_URL` | 예 | MCP bridge |

제거: `HERMES_PROFILES_ROOT`, `hermes-profiles` PVC.

---

## 6. 이것만은 하지 말 것

- profile 정본을 RWX PVC에 두지 말 것.
- invoke 종료 없이 scratch를 다음 invoke에 재사용하지 말 것 (항상 pull 또는 fingerprint 검증).
- VFS push 없이 pod 로컬에만 memory/skill 변경을 남기지 말 것.

---

## 7. 관련 문서

- [ARCHITECTURE.md](../ARCHITECTURE.md) §1 Hermes Profile General tier
- [runtimes/hermes-base/DESIGN.md](../runtimes/hermes-base/DESIGN.md)
- [docs/hermes-integration.md](hermes-integration.md)
