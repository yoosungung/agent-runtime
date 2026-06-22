# ARCHITECTURE.md

LLM 에이전트/MCP 서버를 위한 **런타임 플랫폼**. base image에 사용자 코드를 동적 배포해서 실행(AWS Lambda 방식). LLM, RAG 인프라는 scope 밖.

**예외**: 플랫폼 운영용 관리 콘솔은 이 저장소에 포함한다 — `frontend/`(React+Vite SPA), `backend/`(FastAPI BFF). 런타임 데이터플레인과는 분리된 컴포넌트로 취급.

컴포넌트별 내부 상세는 각 폴더의 `DESIGN.md` 참조. 아키텍처 그림은 `agent-runtime.d2`.

---

## 1. 계약사항 (불변 규칙)

### 내부 계약

- **runtime_pool 식별자 포맷**
  - Bundle 모드: `"{kind}:{runtime_kind}"` (예: `agent:compiled_graph`, `mcp:fastmcp`). `source_meta.runtime_pool` 컬럼과 pod의 `RUNTIME_KIND` env가 이 규약으로 맞물린다.
  - Image 모드: `"{kind}:custom:{slug}"` (예: `agent:custom:summarizer-v1`). admin 등록 시 backend가 K8s Deployment를 동적으로 생성.
  - 새 bundle kind 추가 = `runtime_common.schemas` enum, ext-authz, 해당 base runner, k8s pool Deployment 네 곳을 함께 업데이트.
- **번들 엔트리포인트 포맷**: `"module.path:attr"` — attr은 factory. 시그니처는 `(cfg: dict, secrets: SecretResolver) -> NativeObj` (하위호환으로 zero-arg·1-arg도 허용). `cfg`는 `source_meta.config`와 `user_meta.config`를 runtime이 shallow merge(user wins)한 결과. agent는 프레임워크-네이티브 객체(CompiledGraph 등), mcp는 서버 객체를 반환.
- **베이스 이미지는 이미지 1개 + `RUNTIME_KIND` env**. kind별로 이미지 따로 찍지 않는다.
- **런타임 메타 조회는 deploy-api `/v1/resolve` 단일 경로**. gateway·agent-base·mcp-base 누구도 Postgres에 직접 붙지 않는다. **deploy-api는 read-only** — `source_meta`/`user_meta` **쓰기는 admin backend만**. `source_meta`(코드 정의)는 immutable·versioned, `user_meta`(사용자별 config·secrets_ref)는 mutable.
- **사용자/권한 테이블도 동일 규칙**. auth는 `/login`·`/verify`를 위해 `users`·`user_resource_access` **read-only**. 쓰기는 **admin backend만**. `refresh_tokens`는 예외로 auth가 소유. admin이 비밀번호 변경·계정 비활성 시 auth의 `POST /admin/revoke-tokens`를 호출.
- **pool `/invoke` payload는 식별자만**: agent는 `{agent, version, input, session_id, principal}`, mcp는 `{server, version, tool, arguments, principal}`. meta는 pool이 deploy-api에 **재조회**한다 — 단, Envoy 경유(bundle/image pool) 요청은 ext-authz가 **`x-resolve`** 헤더(base64 `ResolveResponse`)로 resolve 스냅샷을 전달하고 pool은 **헤더가 있으면 deploy-api 호출을 생략**한다. 직접 pool 호출·헤더 불일치·식별자 mismatch 시에는 deploy-api 재조회로 폴백.
- **pool `/invoke`의 `session_id`는 대화 연속성 키**. agent pool은 동일 `session_id`로 LangGraph checkpoint(`thread_id`)·ADK session을 **runtime Postgres**에 persist한다 (기본). Chat UI Recent Chats 목록의 정본은 admin `chat_threads`(플랫폼 `id`); invoke `session_id` = `chat_threads.provider_session_id`. 대화 본문은 provider 저장소가 소유한다.
- **`access`는 `/verify` 응답에 번들**. ext-authz가 별도 authorize 호출을 하지 않도록 한 번에 내려온다.
- **config는 source + user 두 층**. deploy-api는 병합하지 않고 그대로 내려보낸다 — cache 경계와 감사 지점 분리.
- **`infra_meta` 및 `llm_presets`는 platform env registry**. LLM API key·Opik URL 등 플랫폼 공통 인프라. **write = admin backend**, **deploy-api `/v1/resolve`에 포함하지 않음**. secret plaintext는 Postgres에 저장하지 않고 K8s Secret에만 기록. pool pod container env(ConfigMap `runtime-infra` + Secret `runtime-infra-secrets`)로 전달 — factory cfg merge(source+user) 경로와 분리. 에이전트/MCP 번들은 `preset:NAME` 형식으로 등록된 LLM 프리셋을 참조하며, reconciler가 `LLM_PRESET_{NAME}_*` 환경 변수 및 시크릿으로 투영합니다. 프리셋 API key는 빌드(factory/build) 시점에 프로세스 환경변수(`os.environ`)에 바인딩(mutate)되므로, 동시 invoke 환경에서의 경합 방지를 위해 factory 호출 직후 즉시 클라이언트를 동기식으로 인스턴스화해야 합니다.
- **LangGraph 체크포인터 기본은 Postgres** (`CHECKPOINTER_DSN`, VFS와 동일 DB). 대화 상태가 pod-local이 아니므로 session affinity 불필요. `checkpointer: none`/`redis` 등은 명시 override.
- **데이터플레인은 Envoy(C++)**. ext-authz는 스케줄링·인가 결정만. 바디 릴레이·SSE 패스스루는 Envoy.
- **내부 호출의 토큰 Grace Period**: 엣지(UI→Envoy)는 `grace_sec=0`(엄격). 런타임 내부(agent-pool→Envoy `/invoke-internal`)는 **같은 JWT forward** + `exp`만 `grace_sec`(예: 300) 유예. 서명·issuer·`access[]`는 항상 현재 시각 기준 엄격. trust 경계는 NetworkPolicy로 강제. 세부 구현은 [services/auth/DESIGN.md](services/auth/DESIGN.md), [services/ext-authz/DESIGN.md](services/ext-authz/DESIGN.md).
- **scope 경계**: LLM/RAG는 scope 밖. **번들 object store 기본값은 in-cluster Garage(S3 호환)** — 배포 시 env/secret으로 외부 S3(NCP·AWS 등)로 대체 가능. 관리 콘솔 `frontend/`·`backend/`는 예외.

### 이것만은 하지 말 것

- 루트 외 위치에 `.venv` 만들지 말 것(uv가 루트에 단일 venv 관리).
- pool별 이미지를 만들지 말 것 — env로만 분기.
- `source_meta`/`user_meta`/`infra_meta`/`users`/`user_resource_access`에 런타임 서비스(gateway·pool·deploy-api·auth)가 직접 INSERT/UPDATE 하지 말 것 — 쓰기 소유자는 admin backend. `refresh_tokens`만 예외로 auth 전용.
- LLM/RAG 코드를 이 저장소에 추가하지 말 것 — scope 밖. (관리 콘솔 `frontend/`·`backend/`는 예외.)

---

## 2. 컴포넌트 개요

### services/ — 컨트롤/프록시

| 컴포넌트 | 역할 | Postgres 접근 |
|---|---|---|
| [auth](services/auth/DESIGN.md) | 로그온 + 검증. `/login` JWT 발급, `/verify` 검증 + `access` 반환 | `users`, `user_resource_access` (read-only) |
| [deploy-api](services/deploy-api/DESIGN.md) | 런타임 메타 조회. `/v1/resolve` → `source_meta` + `user_meta` | `source_meta`, `user_meta` (read-only) |
| [ext-authz](services/ext-authz/DESIGN.md) | Envoy ext_authz. auth + access + resolve + pod pick → `x-pod-addr` 등 헤더 | 없음 |

### runtimes/ — 실행 워커

| 컴포넌트 | 역할 |
|---|---|
| [agent-base](runtimes/agent-base/DESIGN.md) | Agent-Pool 베이스. `RUNTIME_KIND ∈ {compiled_graph, adk}`. Bundle + General 모드 |
| [mcp-base](runtimes/mcp-base/DESIGN.md) | MCP-Pool 베이스. `RUNTIME_KIND ∈ {fastmcp, mcp_sdk, ...}`. Bundle 모드 |

Image 모드(`custom`) pool은 admin이 빌드한 OCI 이미지가 직접 운영되며 base-image와 무관. contract는 [backend/DESIGN.md](backend/DESIGN.md) "Custom Image 관리" 참조.

### packages/common

`runtime_common.*` — schemas, deploy_client, auth, loader, factory, secrets, registry, scheduling, db, logging, telemetry, settings. [상세](packages/common/DESIGN.md).

### deploy/

Kustomize base + overlays. 네임스페이스 `runtime`(Garage 포함). Postgres는 auth·deploy-api만 접근. [상세](deploy/DESIGN.md).

### 외부 의존 (scope 밖)

LLM serving, RAG 스토리지, OTEL collector, 사용자 Chat UI. **번들 object store**는 k8s 배포 시 **Garage(내장, S3 API)** 가 기본 — `BUNDLE_STORAGE_BACKEND`·`S3_*` env로 외부 S3로 교체 가능.

---

## 3. 런타임 흐름 (Chat invoke)

사용자가 Chat UI에서 로그인한 뒤 agent와 한 턴 주고받는 경로. **Chat invoke는 BFF를 경유하지 않는다** — Ingress에 공개된 `/v1/agents/*`로 Envoy에 직접 POST하고, BFF는 httpOnly 세션 쿠키 → Bearer JWT 브릿지(`GET /api/auth/access-token`)만 담당.

```
[User/Chat UI] ──login──> [backend BFF] ──> [auth] ──> (Postgres)
     │ GET /api/auth/access-token  (Bearer JWT handoff)
     │ POST /v1/agents/invoke + Bearer JWT  (same origin / Ingress)
     ▼
[Envoy] ──ext_authz──> [ext-authz]
     │ verify → access → resolve → scheduler.pick
     │ x-pod-addr → dynamic_forward_proxy
     ▼
[agent-pool pod] ──resolve──> [deploy-api]
     │ BundleLoader → factory(cfg, secrets) → runner
     │ (MCP tool 필요 시) ──> Envoy /v1/mcp/invoke-internal ──> [mcp-pool pod]
     ▼
[User/Chat UI]  ← SSE (agent-base emit; UI가 runtime_kind별 포맷 정규화)
```

**핵심**: pool은 gateway 경유 payload의 번들 정보를 신뢰하지 않는다. Envoy+ext-authz 경로에서는 **`x-resolve` 스냅샷**으로 deploy-api 왕복을 줄이되, 헤더가 없거나 검증 실패 시 **deploy-api 재조회**로 폴백한다. agent와 MCP invoke는 ext-authz / Envoy / pool / deploy-api 네 축이 `kind` 하나로만 분기 — 대칭 구조.

단계별 내부 구현은 [backend/DESIGN.md](backend/DESIGN.md), [services/ext-authz/DESIGN.md](services/ext-authz/DESIGN.md), [runtimes/agent-base/DESIGN.md](runtimes/agent-base/DESIGN.md) 참조.

---

## 4. Postgres 스키마

런타임 + admin이 공유하는 단일 Postgres. **쓰기 소유자는 admin backend** — 런타임 서비스는 read-only 영역만. `refresh_tokens`만 auth가 read+write.

| 테이블 | write | runtime read | 비고 |
|---|---|---|---|
| `source_meta` | admin backend | deploy-api | immutable·versioned |
| `user_meta` | admin backend | deploy-api | mutable |
| `infra_meta` | admin backend | — | platform env; K8s reconciler가 pool pod에 주입 |
| `llm_presets` | admin backend | — | LLM presets; K8s reconciler가 pool pod에 주입 |
| `users` | admin backend | auth | 로그인 credentials |
| `user_resource_access` | admin backend | auth | user ↔ `(kind, name)` ACL |
| `refresh_tokens` | auth | auth | refresh 토큰 해시 |
| `api_keys` | auth | auth | **비활성**(설계 미완 — [ROADMAP.md](ROADMAP.md)) |

마이그레이션: `backend/migrations/0001_init.sql`. 적용: `make db-migrate` 또는 `make db-migrate-all`.

### source_meta

```sql
CREATE TABLE source_meta (
    id            BIGSERIAL PRIMARY KEY,
    kind          VARCHAR(16)  NOT NULL,              -- 'agent' | 'mcp'
    name          VARCHAR(128) NOT NULL,
    version       VARCHAR(64)  NOT NULL,
    runtime_pool  VARCHAR(128) NOT NULL,              -- bundle: '{kind}:{runtime_kind}', image: '{kind}:custom:{slug}'
    entrypoint    VARCHAR(256),                       -- bundle 모드만 NOT NULL
    bundle_uri    VARCHAR(512),
    checksum      VARCHAR(128),
    sig_uri       VARCHAR(512),
    config        JSONB        NOT NULL DEFAULT '{}',
    user_meta_template JSONB   NOT NULL DEFAULT '{}',  -- admin UI form template (runtime merge 제외)
    retired       BOOLEAN      NOT NULL DEFAULT FALSE,
    deploy_mode   VARCHAR(16)  NOT NULL DEFAULT 'bundle',   -- 'bundle' | 'image'
    image_uri     VARCHAR(512),
    image_digest  VARCHAR(128),
    slug          VARCHAR(63),
    status        VARCHAR(16)  NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_source_meta_nv UNIQUE (kind, name, version),
    CONSTRAINT uq_source_meta_kind_slug UNIQUE (kind, slug)
);
```

`/v1/resolve`: `status='pending'` 제외, `status='active'` + `retired=false`만 반환.

### infra_meta

```sql
CREATE TABLE infra_meta (
    id           BIGSERIAL PRIMARY KEY,
    scope        VARCHAR(16)  NOT NULL DEFAULT 'global',   -- MVP: 'global' only
    scope_key    VARCHAR(128) NOT NULL DEFAULT '',
    env          JSONB        NOT NULL DEFAULT '{}',       -- flat container env var names → values
    secret_keys  JSONB        NOT NULL DEFAULT '[]',       -- configured secret env var names only
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_infra_meta_scope UNIQUE (scope, scope_key)
);
```

`/v1/resolve`에 포함하지 않음. secret 값은 K8s Secret `runtime-infra-secrets`에만 존재.

### user_meta

```sql
CREATE TABLE user_meta (
    id             BIGSERIAL PRIMARY KEY,
    source_meta_id BIGINT       NOT NULL REFERENCES source_meta(id) ON DELETE CASCADE,
    principal_id   VARCHAR(128) NOT NULL,
    config         JSONB        NOT NULL DEFAULT '{}',
    secrets_ref    VARCHAR(512),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_meta_source_principal UNIQUE (source_meta_id, principal_id)
);
```

### users / user_resource_access / refresh_tokens / api_keys

```sql
CREATE TABLE users (
    id                   BIGSERIAL PRIMARY KEY,
    username             VARCHAR(128) NOT NULL,
    password_hash        VARCHAR(256) NOT NULL,
    tenant               VARCHAR(64),
    disabled             BOOLEAN      NOT NULL DEFAULT FALSE,
    is_admin             BOOLEAN      NOT NULL DEFAULT FALSE,
    must_change_password BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_username UNIQUE (username)
);

CREATE TABLE user_resource_access (
    user_id    BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       VARCHAR(16)  NOT NULL,
    name       VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, kind, name)
);

CREATE TABLE refresh_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(128) NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ  NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
    id         SERIAL       PRIMARY KEY,
    key_hash   VARCHAR(128) UNIQUE NOT NULL,
    name       VARCHAR(128) NOT NULL,
    tenant     VARCHAR(64),
    disabled   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ
);
```

`user_resource_access`에 `source_meta` FK 없음: ACL은 `(kind, name)`까지만, 버전별 ACL은 설계 밖.

---

## 5. source_meta / user_meta config 병합

| 측면 | `source_meta.config` | `user_meta.config` |
|---|---|---|
| 정의자 | 번들 작성자 | 사용자/관리자 |
| 수명 | 버전과 동일 — immutable | 매 invoke fresh — mutable |
| write | admin backend (source 생성 시) | **사용자 self-service** (`/api/me/user-meta`) + admin break-glass (`/api/user-meta`) |

**`source_meta.user_meta_template`**: admin이 `/me` self-service 폼에 노출할 필드 정의(UI-only). runtime merge 대상 아님. `PATCH /api/source-meta/{id}` 화이트리스트.

**런타임 factory 입력** = shallow merge `{**source.config, **user.config}` — user 키가 같으면 source를 덮어씀. 병합은 agent-base / mcp-base가 resolve 직후 수행. MVP는 1단 shallow merge만.

email-server 등 per-principal 예시는 [backend/DESIGN.md](backend/DESIGN.md) 참조.

### 5.1 infra_meta / llm_presets (platform env)

source/user meta와 **orthogonal**. principal·번들과 무관하게 pool pod container env로 전달.

| 측면 | `infra_meta` / `llm_presets` | `source_meta.config` | `user_meta.config` | Kustomize `runtime-env` |
|---|---|---|---|---|
| 범위 | platform (global) | 번들/버전 | principal × 번들 | 클러스터 bootstrap |
| 수명 | 운영 중 mutable | immutable (버전) | invoke마다 fresh | 배포 시 |
| 전달 | flat env → ConfigMap + Secret → pod env | resolve → merge → factory cfg | resolve → merge → factory cfg | gitops envFrom |
| 예시 | `OPIK_URL`, `LLM_PRESET_{NAME}_MODEL_ID`, `LLM_PRESET_{NAME}_API_KEY` 등 | MCP provider, preset reference (`preset:NAME`) | mailbox, model override | `REDIS_URL`, `DEPLOY_API_URL` |

**API/DB/K8s**: `env`는 flat container env var 이름(`[A-Z][A-Z0-9_]*`, reserved 제외). LLM Preset을 등록하면 `LLM_PRESET_{NAME}_*` 형태의 환경변수가 자동 매핑되어 컨테이너에 주입됩니다. **Admin UI**는 Opik 및 LLM Presets 탭을 제공하여 이들을 관리합니다.

**infra에 두지 않을 것**: 번들 도메인 credential → `source_meta.config`; principal identity → `user_meta.config`; custom image 전용 env → `source_meta.pool_env`(infra보다 우선).
