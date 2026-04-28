# agents-runtime

LLM 에이전트 / MCP 서버의 **런타임 플랫폼**. AWS Lambda 스타일 — 베이스 이미지가 장기 실행 pod로 떠 있고, 사용자 코드(agent graph, MCP 서버)는 **런타임에 동적으로** 베이스에 로드되어 실행된다.

이 문서는 **무엇이 있고 어떻게 맞물리는지**만 기술한다. 컴포넌트별 상세 설계·스키마·구현 계획은 해당 폴더의 `DESIGN.md`. 아키텍처 그림: `agent-runtime.png`.

## 구성요소

### services/ — 컨트롤/프록시 레이어

| 컴포넌트 | 역할 | Postgres 접근 |
|---|---|---|
| [`auth`](services/auth/DESIGN.md) | **로그온 + 검증**. `/login`으로 JWT 발급, `/verify`로 검증 + 허용 리소스 목록(`access`) 반환 | `users`, `user_resource_access` (read/write) |
| [`deploy-api`](services/deploy-api/DESIGN.md) | **런타임 메타 조회 서비스**. `/v1/resolve`로 `source_meta` + `user_meta` 묶음 조회 | `source_meta`, `user_meta` (read-only) — **유일한 DB 접근자** |
| [`ext-authz`](services/ext-authz/DESIGN.md) | Envoy HTTP ext_authz 서비스. agent/mcp 통합 — auth + access + resolve + pod pick → 응답 헤더(`x-pod-addr`, `x-pod-fallback-addr` 등)로 반환. MCP 발견·스트림 라우트도 직접 처리. 바디 릴레이는 Envoy(C++)가 담당 | **없음** |

### runtimes/ — 실행 워커 이미지

| 컴포넌트 | 역할 |
|---|---|
| [`agent-base`](runtimes/agent-base/DESIGN.md) | Agent-Pool 베이스. `RUNTIME_KIND ∈ {compiled_graph, adk, custom}`로 정체성 분기. 호출 시 deploy-api에서 번들 + user_meta를 가져와 factory를 실행 |
| [`mcp-base`](runtimes/mcp-base/DESIGN.md) | MCP-Pool 베이스. `RUNTIME_KIND ∈ {fastmcp, mcp_sdk, didim_rag, t2sql}`. 구조는 agent-base와 평행, 대상이 MCP 서버 |

두 베이스 모두 **이미지 1개 + env로 분기**. kind별 이미지를 따로 찍지 않는다. **Bundle 모드 전용** — Image 모드(`custom`) pool은 admin이 직접 빌드한 OCI 이미지를 사용하며 base-image와 무관.

### packages/common — 공용 라이브러리

`runtime_common.*` 네임스페이스. 모든 서비스와 런타임 베이스가 공용으로 import. [상세](packages/common/DESIGN.md).

- `schemas` — 서비스 간 계약 (`SourceMeta`, `UserMeta`, `ResolveResponse`, `Principal`, 식별자 기반 `*InvokeRequest`)
- `deploy_client` — `/v1/resolve` 호출 + ETag/LRU 캐시 (gateway·base 공용)
- `auth` — auth `/verify` 래퍼
- `loader` — 번들 fetch/검증/import/LRU
- `factory` / `secrets` — factory 시그니처 어댑터 + lazy 비밀값 resolver
- `registry` / `scheduling` — Redis 기반 warm-registry + gateway 스케줄러
- `db`, `logging`, `telemetry`, `settings`

### deploy/ — Kubernetes 매니페스트

Kustomize base + overlays(dev/stage/prod). 네임스페이스 `runtime`. Postgres는 StatefulSet — **auth / deploy-api만 접근**. NetworkPolicy로 게이트웨이/pool의 DB 접근을 원천 차단. [상세](deploy/DESIGN.md).

### 외부 의존 (scope 밖)

LLM serving, RAG 스토리지(DidimRAG / pgvector), OTEL collector, bundle 저장소(S3/OCI), 사용자 UI(Chat/Admin). 이 저장소에서는 엔드포인트 주소만 env로 받는다.

## 런타임 흐름 — 로그온 후 에이전트와 대화

사용자가 Chat UI에서 로그인한 뒤 agent와 한 턴 주고받는 전체 경로. 번호는 네트워크 홉 순서.

```
[User/Chat UI] ──(1)login──> [auth] ──SELECT users──> (Postgres)
     │                          │
     │<──(2) access_token──────┘
     │
     │ (3) POST /api/chat/invoke {agent, input, session_id}
     │     Authorization: Bearer <jwt>
     │     x-runtime-name: <agent>
     ▼
[backend BFF]
     │  (4) POST /v1/agents/invoke → Envoy (http://envoy.runtime.svc:8080)
     ▼
[Envoy]  ──ext_authz check──> [ext-authz]
     │                              │ (5) verify(token) → [auth] → Principal
     │                              │ (6) access 검사: (kind='agent', name) ∈ access
     │                              │ (7) resolve(kind=agent, name) → [deploy-api] → source
     │                              │ (8) scheduler.pick → warm pod IP
     │                              │<── x-pod-addr=<pod_ip:port>
     │                              │    x-pod-fallback-addr=<service:port>
     │   Lua: :authority ← x-pod-addr
     │   dynamic_forward_proxy
     │  (9) POST /invoke  {agent, version, input, session_id, principal}
     ▼
[agent-pool pod (compiled_graph)]
     │  (10) resolve(kind=agent, name, version)  ← pool이 자기 권한으로 재조회
     ▼
[deploy-api] ──> {source, user:{config, secrets_ref}}
     │  (11) BundleLoader.load(source) — checksum 캐시 hit이면 factory 재사용
     │  (12) factory(user_cfg, secrets) → instance
     │  (13) runner.run('compiled_graph', instance, input, session_id)
     │       → CompiledGraph.ainvoke(...)  ... LLM 호출 ...
     │       ... MCP 툴 호출이 필요하면 (14)~(21) ...
     │
     │  (14) POST /v1/mcp/invoke-internal  {server, version?, tool, arguments}
     │       Authorization: Bearer <사용자 JWT — pool이 forward>
     ▼
[Envoy]  ──ext_authz check──> [ext-authz]
     │                              │ (15) verify(token, grace_sec=N)  ← 내부 경로 grace 적용
     │                              │ (16) access 검사: (kind='mcp', name=server)
     │                              │ (17) resolve(kind=mcp, name) → source
     │                              │ (18) scheduler.pick → warm pod IP
     │                              │<── x-pod-addr, x-pod-fallback-addr
     │  (19) POST /invoke  {server, version, tool, arguments, principal}
     ▼
[mcp-pool pod (fastmcp)]
     │  (20) resolve(kind=mcp, name, version)  ← pool이 재조회
     │  (21) BundleLoader.load → factory → runner.call_tool → 외부 Infra 호출
     │<── tool result
     │
[agent-pool pod]<── tool result (Envoy 패스스루)
     │  (22) 실행 계속. (14)~(21) 여러 번 반복 가능
     │<── final result (SSE 스트리밍)
     │
[Envoy]<── pool 응답 패스스루 (버퍼링 없음)
     │
[backend BFF]<── SSE 정규화 (_extract_text)
     │
[User/Chat UI]<── (23) data: {"text": "..."} 이벤트
```

### 단계별 핵심

**(1)–(2) 로그온.** `auth.POST /login`이 `users` 테이블에서 비밀번호 해시 검증 후 JWT 서명.

**(3)–(4) invoke 요청.** BFF(`backend`)가 `x-runtime-name` 헤더 + `Authorization: Bearer <jwt>`와 함께 Envoy로 POST. payload엔 식별자만 (`{agent, version?, input, session_id?}`).

**(5)–(8) ext-authz check.** Envoy가 ext-authz에 check 요청을 포워드. ext-authz는 verify → access → resolve → scheduler.pick을 순서대로 실행하고 `x-pod-addr`(warm pod IP)과 `x-pod-fallback-addr`(pool Service URL)을 응답 헤더로 반환. Envoy Lua 필터가 `:authority`를 `x-pod-addr`로 교체 → `dynamic_forward_proxy`가 해당 pod로 직접 연결.

**(9) pool로 프록시.** Envoy가 pool pod에 `/invoke`로 패스스루. payload는 식별자만. meta는 넘기지 않는다.

**(10) pool이 재조회.** 같은 `resolve`를 pool이 **자기 권한으로** 다시 호출. gateway 경유 payload의 번들 정보를 신뢰하지 않기 위한 이중 검증 + user_meta fresh 값 확보.

**(11) 번들 로드.** `source.checksum`이 캐시 키. warm pod는 import된 factory 객체를 그대로 재사용 — cold-start 비용은 첫 호출만.

**(12) factory + 실행.** `cfg = {**source.config, **user.config}` (shallow merge, user wins). **체크포인터는 Redis** — session affinity 불필요.

**(14) MCP invoke (내부 경로).** agent-pool이 Envoy의 `/v1/mcp/invoke-internal`로 tool 호출. **사용자의 JWT를 그대로 forward** — 서비스 간 별도 토큰 발급 없이 ext-authz가 `access[]` 기준으로 인가. 이때 **만료 유예(grace period)** 가 적용된다.

**(15)–(18) MCP ext-authz check.** agent invoke와 동일 구조. `kind='mcp'`와 내부 경로라 grace가 적용된다는 것 둘 뿐.

**(19)–(21) mcp-pool.** agent-pool과 동일한 재조회 → BundleLoader → factory → runner 구조.

**(22)–(23) 응답 전파.** agent-pool → Envoy(버퍼링 없는 SSE 패스스루) → BFF(SSE 정규화, `_extract_text`) → Chat UI.

### agent와 MCP가 대칭인 이유

(14)~(21)이 (3)~(13)의 구조를 그대로 복제한다 — ext-authz(check) / Envoy / pool / deploy-api 네 축이 `kind` 하나로만 분기된다. 새 리소스 kind가 추가돼도 같은 4-레이어 패턴을 따를 수 있다는 의미. payload 스키마·Envoy 라우트·NetworkPolicy·OTEL span naming 모두 이 대칭을 깨지 않도록 유지한다.

## 핵심 설계 원칙

- **Postgres는 auth / deploy-api만**. 게이트웨이·pool은 DSN을 모른다. NetworkPolicy로 강제.
- **`runtime_pool`은 두 포맷을 가진다**:
  - **Bundle 모드**: `"{kind}:{runtime_kind}"` (예: `agent:compiled_graph`, `mcp:fastmcp`). gateway 라우팅과 pod 정체성(env)이 맞물린다. 새 bundle kind 추가 = 4곳(schemas enum / ext-authz / base runner / k8s Deployment) 동시 업데이트.
  - **Image 모드**: `"{kind}:custom:{slug}"` (예: `agent:custom:summarizer-v1`). admin 등록 시 backend가 K8s Deployment를 동적으로 생성. ext-authz는 slug에서 Service DNS를 derive해 라우팅 — ext-authz 재시작 불필요. `parse_runtime_pool()` (`runtime_common.schemas`)으로 구조화된 `RuntimePoolId(kind, runtime_kind, slug?, is_image_mode)` 파싱.
- **식별자 기반 payload**. pool이 받는 invoke 정보엔 번들 위치가 없다. pool이 직접 resolve → 신뢰 경계가 deploy-api 한 곳으로 수렴.
- **source_meta(immutable/versioned) vs user_meta(mutable)**. 번들 캐시는 checksum으로 장수명, user 설정은 매 invoke fresh. 수명이 달라 테이블도 별도.
- **config는 source + user 두 층**. 번들 기본(`source_meta.config`, 버전 고정) + per-principal 덮어쓰기(`user_meta.config`). runtime이 shallow merge(user wins) 후 factory에 주입. deploy-api는 병합하지 않고 그대로 내려보낸다 — cache 경계와 감사 지점을 분리하기 위함.
- **`access`는 `/verify` 응답에 번들**. ext-authz가 별도 authorize 호출을 하지 않도록 한 번에 내려온다.
- **이미지 1개 + RUNTIME_KIND env**. pool별 이미지를 찍지 않는다.
- **LangGraph 체크포인터는 Redis**. 대화 상태가 pod-local이 아니므로 **session affinity 불필요** — 어떤 pod가 같은 `session_id`의 다음 턴을 받아도 된다.
- **데이터플레인은 Envoy(C++)**. Python 게이트웨이(agent-gateway, mcp-gateway)를 제거하고 ext-authz는 스케줄링 결정만 담당. 바디 릴레이·SSE 패스스루는 Envoy가 처리.
- **내부 호출은 JWT forward + exp grace**. 엣지(UI→Envoy)는 엄격, 런타임 내부(agent-pool→Envoy `/invoke-internal`)는 같은 JWT 재사용 + `exp`만 짧은 유예. 서명·issuer·`access[]`는 항상 현재 시각 기준 엄격. trust 경계는 NetworkPolicy로 강제.
- **scope 경계**: LLM/RAG/UI/번들 저장소는 외부. 이 저장소는 그들에게 붙는 런타임까지만 책임진다.

## Postgres 스키마 (참고)

런타임 + admin이 공유하는 단일 Postgres 인스턴스. **쓰기 소유자는 admin backend** — 런타임 서비스는 각자 read-only 영역만 갖는다. `refresh_tokens`만 예외로 auth가 read+write. 자세한 위임·브릿지는 [backend/DESIGN.md](backend/DESIGN.md), [services/auth/DESIGN.md](services/auth/DESIGN.md), [services/deploy-api/DESIGN.md](services/deploy-api/DESIGN.md).

| 테이블 | write | runtime read | 비고 |
|---|---|---|---|
| [`source_meta`](#source_meta) | admin backend | deploy-api (`/v1/resolve`) | agent/MCP 번들 코드 정의 — **immutable·versioned** |
| [`user_meta`](#user_meta) | admin backend | deploy-api (`/v1/resolve`) | per-principal config·secrets_ref — **mutable** |
| [`users`](#users) | admin backend | auth (`/login`) | 로그인 credentials |
| [`user_resource_access`](#user_resource_access) | admin backend | auth (`/verify`) | user ↔ `(kind, name)` ACL |
| [`refresh_tokens`](#refresh_tokens) | auth | auth | refresh 토큰 해시 — 런타임 세션 상태 |
| [`api_keys`](#api_keys) | auth (`POST /v1/api-keys`) | auth (`/verify` 분기) | 서비스 간 API 키 — **현재 비활성**(설계 미완, 아래 참조) |

마이그레이션 파일: **`backend/migrations/0001_init.sql`** (모든 테이블 초기 스키마) + **`backend/migrations/0002_custom_image_mode.sql`** (image 모드 컬럼). 과거엔 `services/auth/migrations/` / `services/deploy-api/migrations/`에 나뉘어 있었으나 admin backend가 쓰기 소유자로 재배치되면서 통합. 적용 경로는 `make db-migrate` 또는 `deploy/k8s/base/migration-job.yaml` (ConfigMap으로 동일 SQL 인라인).

### source_meta

```sql
CREATE TABLE source_meta (
    id            BIGSERIAL PRIMARY KEY,
    kind          VARCHAR(16)  NOT NULL,              -- 'agent' | 'mcp'
    name          VARCHAR(128) NOT NULL,
    version       VARCHAR(64)  NOT NULL,
    runtime_pool  VARCHAR(128) NOT NULL,              -- bundle: '{kind}:{runtime_kind}', image: '{kind}:custom:{slug}'
    entrypoint    VARCHAR(256),                       -- 'module.path:factory_attr' — bundle 모드만 NOT NULL
    bundle_uri    VARCHAR(512),                       -- https:// | file:// | s3:// | oci:// — bundle 모드만
    checksum      VARCHAR(128),                       -- sha256:...
    sig_uri       VARCHAR(512),                       -- 서명 파일 URI (선택)
    config        JSONB        NOT NULL DEFAULT '{}', -- 기본 config (버전 고정, 아래 '병합' 참조)
    retired       BOOLEAN      NOT NULL DEFAULT FALSE,
    -- image 모드 컬럼 (migration 0002)
    deploy_mode   VARCHAR(16)  NOT NULL DEFAULT 'bundle',   -- 'bundle' | 'image'
    image_uri     VARCHAR(512),                             -- OCI 이미지 URI (image 모드만)
    image_digest  VARCHAR(128),                             -- sha256 digest (image 모드, 선택)
    slug          VARCHAR(63),                              -- '{kind}:custom:{slug}' 에서의 slug (image 모드만)
    status        VARCHAR(16)  NOT NULL DEFAULT 'active',   -- 'pending'|'active'|'failed'|'retired'
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_source_meta_nv UNIQUE (kind, name, version),
    CONSTRAINT uq_source_meta_kind_slug UNIQUE (kind, slug)  -- slug 고유성 (NULL은 제외)
);
CREATE INDEX ix_source_meta_name ON source_meta (name);
CREATE INDEX ix_source_meta_slug ON source_meta (slug);
CREATE INDEX ix_source_meta_checksum ON source_meta (checksum);  -- hard delete 참조 카운트 O(log N)
```

**deploy-api `/v1/resolve` 동작**: `status='pending'` 행은 resolve 결과에서 제외 (라우팅 대상 아님). `status='active'` + `retired=false` 행만 반환.

마이그레이션 파일: **`backend/migrations/0001_init.sql`** (초기 스키마) + **`backend/migrations/0002_custom_image_mode.sql`** (image 모드 컬럼 추가).

**`source_meta.config` vs `user_meta.config` — 병합 규칙**

| 측면 | `source_meta.config` | `user_meta.config` |
|---|---|---|
| 정의자 | 번들 작성자(개발자) | 사용자/관리자 |
| 수명 | 버전과 동일 — immutable | 매 invoke fresh — mutable |
| 용도 | 기본값 · 모두에게 공통인 파라미터 (모델 선택, tool allowlist 기본값 등) | per-principal 덮어쓰기 (quota, tone, 개인 설정) |
| 누가 write | admin backend (source_meta 생성 시 같이) | admin backend (`/api/user-meta` upsert) |

**런타임에서 factory에 들어가는 값은 두 config의 shallow merge** — `{**source.config, **user.config}`. user 키가 같으면 source를 덮어쓴다. 병합은 **agent-base / mcp-base가 resolve 결과를 받은 직후** 수행 — deploy-api는 각각 그대로 내려보낸다 (transparency + caching 분리).

MVP는 1단 shallow merge. 중첩 dict / list의 깊은 병합은 도입하지 않는다(필요해지면 번들 factory가 직접 처리).

### user_meta

```sql
CREATE TABLE user_meta (
    id             BIGSERIAL PRIMARY KEY,
    source_meta_id BIGINT       NOT NULL REFERENCES source_meta(id) ON DELETE CASCADE,
    principal_id   VARCHAR(128) NOT NULL,            -- Principal.user_id (또는 tenant_id)
    config         JSONB        NOT NULL DEFAULT '{}',  -- per-user 실행 파라미터
    secrets_ref    VARCHAR(512),                     -- 'vault://...' / 'env://...' — 원본 비밀값 아님
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_meta_source_principal UNIQUE (source_meta_id, principal_id)
);
CREATE INDEX ix_user_meta_principal ON user_meta (principal_id);
```

### users

```sql
CREATE TABLE users (
    id                   BIGSERIAL PRIMARY KEY,
    username             VARCHAR(128) NOT NULL,
    password_hash        VARCHAR(256) NOT NULL,             -- argon2id
    tenant               VARCHAR(64),
    disabled             BOOLEAN      NOT NULL DEFAULT FALSE,
    is_admin             BOOLEAN      NOT NULL DEFAULT FALSE,
    must_change_password BOOLEAN      NOT NULL DEFAULT FALSE,  -- bootstrap seed = TRUE
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_username UNIQUE (username)
);
```

### user_resource_access

```sql
CREATE TABLE user_resource_access (
    user_id    BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       VARCHAR(16)  NOT NULL,                -- 'agent' | 'mcp' — source_meta.kind와 동일 어휘
    name       VARCHAR(128) NOT NULL,                -- source_meta.name과 동일 어휘 (FK 없음)
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, kind, name)
);
CREATE INDEX ix_ura_kind_name ON user_resource_access (kind, name);  -- 리소스 관점 역조회
```

`source_meta`에 FK 걸지 않는 이유: `source_meta`는 `(kind, name, version)` 단위로 다행이 존재, 매핑은 `(kind, name)`까지만 필요. 정합성은 admin write path의 책임. 버전별 ACL은 설계 밖.

### refresh_tokens

```sql
CREATE TABLE refresh_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(128) NOT NULL UNIQUE,        -- sha256(plaintext) — 평문은 발급 시 1회만 클라에 전달
    expires_at  TIMESTAMPTZ  NOT NULL,
    revoked_at  TIMESTAMPTZ,                         -- NULL = 유효, 값 있으면 revoke됨
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
```

admin이 비번 변경·계정 비활성·삭제할 때 해당 user의 refresh 전체 revoke 필요 → admin backend가 `POST /admin/revoke-tokens?user_id=` (auth 신설 예정) 호출. admin은 이 테이블에 직접 쓰지 않는다.

### api_keys

```sql
CREATE TABLE api_keys (
    id         SERIAL       PRIMARY KEY,
    key_hash   VARCHAR(128) UNIQUE NOT NULL,         -- argon2id(plaintext) — 실제 구현은 argon2 (컬럼명은 legacy)
    name       VARCHAR(128) NOT NULL,
    tenant     VARCHAR(64),
    disabled   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ
);
```

**원래 의도**: 서비스 간 호출(Chat Service → gateway 등)에 JWT 대신 쓰는 장기 토큰. Chat Service 같은 백엔드는 `/login` 대신 발급받은 API key를 `Authorization: Bearer ak_<id>_<secret>`으로 보낸다.

**현재 상태 — 비활성(skeleton only)**:
- 구현된 것: `POST /v1/api-keys` 발급(평문은 응답에 1회만), `POST /verify`가 `ak_` 접두 토큰을 `_verify_api_key`로 분기.
- **문제**: `_verify_api_key`가 `Principal(user_id=0, access=[], ...)` 를 반환 → gateway 인가는 `(kind, name) ∈ access` 검사이므로 **모든 invoke가 403**. 즉 발급은 되지만 실제 호출은 실패한다.
- **빠진 것**: API key 별 권한 매핑이 없음. 활성화하려면 아래 중 하나가 필요:
  - `api_key_resource_access(api_key_id, kind, name)` 테이블 신설 → `_verify_api_key`가 여기서 access 채움 (가장 대칭적)
  - 또는 `tenant` 기반 ACL (같은 tenant의 모든 리소스 허용) — 단순하지만 세밀도 낮음
  - 또는 API key를 기존 user에 묶어 `user_resource_access` 재사용 (user 발급의 연장)
- **관리 UI**: 없음. 필요 시 admin backend에 `/api/api-keys` CRUD + 권한 매핑 UI 추가.

어느 방향인지 결정되기 전까지는 운영에서 사용하지 말 것.


