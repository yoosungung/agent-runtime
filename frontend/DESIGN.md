# frontend (admin console + chat SPA)

`agent-runtime.d2`의 `user.chat_ui`와 `admin.admin_ui`를 **하나의 React SPA로 통합**. 운영자가 agent/MCP 번들을 등록·수정·삭제하고, 같은 로그인 세션에서 자기 agent와 대화할 수 있게 한다.

MVP 범위는 **관리(admin) 기능**. 챗 기능은 페이지 구조를 예약만 해두고 추후 추가.

## 책임 범위

| 포함 | 제외 |
|---|---|
| 로그인·로그아웃 (BFF cookie 세션) | JWT 직접 보관 — 모두 httpOnly cookie로 BFF가 관리 |
| source_meta 리스트 / 상세 / 생성 / retire / 삭제 | Postgres 직접 연결 — BFF가 소유 |
| bundle zip 업로드 (multipart) | 번들 내부 코드 편집 — 에디터/IDE 기능 밖 |
| user_meta (per-principal config JSON + secrets_ref) 편집 | secret 원본 저장 — `secrets_ref`만 편집, 원본은 Vault 등 외부 |
| 사용자 CRUD (생성 / 비번 변경·리셋 / disabled 토글 / is_admin 토글 / 삭제) | 비밀번호 해시 연산 — BFF가 argon2id로 처리 |
| 사용자-리소스 권한(access) 부여·회수 — user 관점 + resource 관점 양방향 | 세밀한 RBAC(role, 버전별 ACL 등) — 설계 밖 |
| (추후) 챗 인터페이스 — agent 선택 → 대화 | agent 실행 로직 — agent-pool이 담당 |

## 설계

### 스택

- **Vite 8 + React 18 + TypeScript (strict)**.
- **라우팅**: `react-router-dom` v6. 페이지 단위 파일 분할.
- **상태/데이터**: `@tanstack/react-query`로 서버 상태 캐시 + invalidation. 전역 UI 상태는 `zustand` 하나(가볍게).
- **폼**: `react-hook-form` + `zod` (BFF/deploy-api 스키마와 1:1 매핑).
- **UI**: Tailwind CSS + `shadcn/ui` 컴포넌트(Button, Table, Dialog, Form, Textarea/JSON editor). 디자인 시스템은 별도 구축하지 않음.
- **번들 검증**: 파일 선택 시 클라이언트에서 확장자(`.zip`) + 크기(`MAX_BUNDLE_SIZE_MB`) 사전 체크 — 서버 검증이 최종이지만 UX용 조기 차단.

### 백엔드 통신

- **관리 API는 `/api/*`** — Vite dev 서버는 `http://localhost:8000`으로 프록시(기존 `vite.config.ts` 설정 그대로).
- **Chat invoke는 `/v1/agents/*`** — Ingress → Envoy 직접. BFF `/api/chat/invoke`를 거치지 않는다. 호출 URL은 빌드 env `VITE_AGENTS_INVOKE_URL`(기본 `/v1/agents/invoke`)로 지정. 로컬 dev는 Vite가 `/v1/agents`를 `VITE_DEV_ENVOY_PROXY_TARGET`(기본 `http://127.0.0.1:8084`, wire-dev Envoy PF)으로 프록시.
- **Bearer JWT**: httpOnly `access_token` 쿠키는 JS에서 읽을 수 없으므로, invoke 직전 `GET /api/auth/access-token`으로 JWT를 받아 `Authorization: Bearer …` + `x-runtime-name` 헤더로 Envoy에 전달. refresh가 발생하면 응답 Set-Cookie로 쿠키도 갱신.
- 프로덕션은 same origin(`agents.*`)에서 SPA·`/api/*`·`/v1/agents/*`가 동일 Ingress host. cross-origin dev는 BFF `CORS_ORIGINS`에 SPA origin 등록(`/api/*`만 해당 — invoke는 Vite proxy로 same-origin 유지 권장).
- **인증 쿠키는 자동 전송**. fetch는 `credentials: "include"` 기본값 유지(same-origin이면 불필요, cross-origin이면 필수).
- **CSRF**: state-changing 요청(POST/PUT/DELETE/PATCH)은 `X-CSRF-Token` 헤더 필수. 로그인 응답으로 받은 `csrf_token` cookie 값을 읽어서 첨부(double-submit cookie). 이는 httpOnly가 아니므로 JS에서 읽힘.
- **캐시**: `apiFetch`는 `cache: "no-store"`; BFF `/api/*`는 `Cache-Control: no-store` 응답.
- **페이지네이션 표준** (모든 list GET + UI):
  - API 요청: `?limit=<1..100>&offset=<>=0>`. 서버가 `limit>100`은 100으로 clamp.
  - API 응답: `{items: [...], total: N, limit: L, offset: O}`. UI는 `total`로 페이지 수 계산(offset 기반).
  - UI: `useViewportPagination` + `Paginator`. 목록 카드(`ref={anchorRef}`) 위치·뷰포트 높이로 `limit`을 동적 계산(`lib/viewportPageLimit.ts`, 기본 `min=10`·`max=50`·`rowHeight=44`). 리사이즈·필터 변경 시 offset 리셋. 고정 `usePagination`은 사용하지 않음.
  - 정렬: 서버 기본값 고정 — 오버라이드 UI 없음 (MVP).
- **에러 처리**:
  - `401` → 세션 만료 → 로그인 페이지로.
  - `403` → admin 권한 없음 → `/me`로 또는 "권한 없음" 안내.
  - `404`/`409`/`413`/`422`/`400` → 폼 필드 에러(422는 서버 `detail`에서 필드별 매핑) 또는 toast.
  - `412` → 낙관적 잠금 실패(다른 관리자가 먼저 수정) → "다시 불러오세요" 안내 + refetch 버튼. (nice-to-have 활성화 시)
  - `500` → 전역 에러 바운더리.

### 서버 검증과의 동기화

`lib/schemas.ts`의 zod 스키마는 backend의 [Validation 표](../backend/DESIGN.md)와 **1:1 일치**시킨다 — 프런트 체크는 UX용일 뿐 서버 400/422가 최종 권위. 드리프트 방지를 위해:

- **enum은 `runtime_common.schemas`의 `AgentRuntimeKind` / `McpRuntimeKind`가 단일 출처**. BFF가 응답 또는 전용 엔드포인트(`GET /api/meta/enums`, 신설 가능)로 내려주거나, 타입 생성 스크립트로 OpenAPI → TS. 하드코드 금지.
- 주요 regex (복제해 두지만 출처는 backend/DESIGN.md):
  - `name`: `/^[a-z0-9][a-z0-9-]{0,127}$/`
  - `version`: `/^[a-zA-Z0-9._-]{1,64}$/`
  - `entrypoint`: `/^[\w.]+:[\w]+$/`
  - `username`: `/^[a-zA-Z0-9_.-]{3,128}$/`
  - `checksum`: `/^sha256:[0-9a-f]{64}$/`
  - `secrets_ref`: `/^(vault|env|aws-sm):\/\/.+$/`
- **PATCH 화이트리스트**: 폼이 **애초에 불변 필드를 건드리지 않도록** UI 레벨에서 readonly/비활성. body에 실수로 실어도 서버가 400 거절 — 그 400은 일반 toast로 처리(필드 매핑 없음).
  - `source_meta` 상세 편집에서 변경 가능: `entrypoint`, `sig_uri`, `runtime_pool`, `config`. 금지: `name`, `version`, `kind`, `checksum`, `bundle_uri`, `retired`(전용 action), `created_at`.
  - 사용자 상세 편집에서 변경 가능: `tenant`, `disabled`, `is_admin`. 금지: `password`(전용 action), `username`, `id`, `created_at`, `updated_at`.

### 라우트 구조

```
/login                                 공개
/                                      로그인 필요, 대시보드 (admin만)
/agents                                source_meta list (kind=agent)
/agents/new                            생성 폼 (bundle_uri 입력 또는 zip 업로드)
/agents/new/general                    general agent 생성 (config-only)
/agents/hermes                         Hermes profile agent 목록 (`deploy_mode=hermes_general`)
/agents/new/hermes                     Hermes agent 생성 (`POST /api/source-meta/hermes-general`)
/agents/hermes/:id                     Hermes agent 상세 (조회·retire·delete; PATCH는 P2 후속)
/agents/:id                            상세 — bundle: User Meta Template 탭 + access; general: 편집 폼
/mcp-servers/:id                       상세 + User Meta Template 탭 + access
/me                                    본인 프로필 + integrations + 비번 변경
/me/integrations                       → /me 리다이렉트
/me/user-meta/:kind/:name              본인 user_meta 편집 (template 기반 폼)
/chat                                  agent 선택 → 대화 (SSE 스트리밍)
/bundle/bucket                          admin: bundle object store 브라우저 (S3 또는 local); `/bucket` → redirect
/vfs                                    admin: → `/vfs/agent` redirect
/vfs/agent                              admin: general·hermes_general agent VFS 목록
/vfs/agent/:kind/:name                  admin: agent VFS 브라우저 + 텍스트 에디터
/vfs/agents/:kind/:name                 → `/vfs/agent/:kind/:name` 호환
/vfs/user                               admin: 사용자 VFS 목록
/vfs/user/:userId                       admin: user VFS 브라우저
/vfs/wiki                               admin: pipeline project wiki VFS 목록
/vfs/wiki/:projectId                    admin: wiki VFS 브라우저 (project slug breadcrumb)
/settings/infra                        admin: Platform env (LLM·Opik·OTLP)
/users                                 admin: 사용자 관리
/audit                                 admin: 감사 로그
/pipeline                              admin: Pipeline 랜딩 (프로젝트 미선택 안내·생성)
/pipeline/credentials                  admin: OAuth (tenant 공용)
/pipeline/projects/:projectId          → sources 탭으로 redirect
/pipeline/projects/:projectId/sources
/pipeline/projects/:projectId/sources/new
/pipeline/projects/:projectId/sources/:sourceId
/pipeline/projects/:projectId/runs
/pipeline/projects/:projectId/documents
/pipeline/projects/:projectId/documents/:documentId
/pipeline/projects/:projectId/maintenance   admin: reconcile·cleanup·purge (헤더 링크)
/files/*                               → `/pipeline` redirect (구 파일관리)
```

**Pipeline (`/pipeline/*`, admin)** — … **Sources · Runs · Documents** 탭 목록은 표준 페이지네이션(`Paginator` + `useViewportPagination`). …

**ingest_state 배지**: `pending` · `indexed_rag` · `dead_letter` · `purging` · `purged` — `knowledge/components/IngestStateBadge.tsx`. **Runs status 배지**: Argo phase(`Succeeded`/`Running`/…) · PG `submitted` — `pipeline/components/WorkflowStatusBadge.tsx`.

**Bucket (`/bundle/bucket`, admin)** — Bundle 섹션 탭(Agent/MCP 옆, admin만 표시). `GET /api/bucket/info` 배지(S3/local). breadcrumb + 1-depth listing. toolbar: New Folder · Upload · Move · Delete. `in_use` 행(checkbox disabled, "In use" badge) — `source_meta` 참조 중 번들. delete/move 409 → "Source Meta가 참조 중인 번들입니다…" toast.

**VFS (`/vfs`, admin)** — Platform → **VFS**. Bundle/Container와 동일한 섹션 레이아웃(`VfsSectionLayout`) + **Agent · User · Wiki** 탭. `/vfs` → `/vfs/agent` redirect. Agent(`/vfs/agent`)는 general·hermes_general agent 목록 → 브라우저(`/vfs/agent/:kind/:name`). User(`/vfs/user`)는 사용자 목록 → 개인 VFS(`/vfs/user/:userId`). Wiki(`/vfs/wiki`)는 pipeline project 목록 → project wiki VFS(`/vfs/wiki/:projectId`). Bucket UX와 유사(breadcrumb, 텍스트 에디터). agent name·project slug 기준 공유 안내.

**가드 매트릭스**:

| 조건 | 리다이렉트 |
|---|---|
| 세션 없음 | `/login` |
| 세션 있음 + `must_change_password==true` | `/me` (비번 변경 강제 — 다른 모든 라우트 접근 차단) |
| 세션 있음 + `is_admin==false` | `/me`, `/me/user-meta/*`, `/chat` 허용 |
| 세션 있음 + `is_admin==true` + `must_change_password==false` | 모든 라우트 허용 |

구현은 `<RequireAuth />` → `<RequireNotForcedChangePassword />` → `<RequireAdmin />` 중첩 가드. 각 라우트 정의에서 필요한 레벨까지만 감쌈. `useSession()` 훅이 `{user_id, username, tenant, is_admin, must_change_password}` 노출.

공통 레이아웃: 상단 nav(에이전트 / MCP / 사용자 / 챗 / 로그아웃), 좌측 사이드바는 리스트 화면에서만.

### 주요 화면별 흐름

**source_meta 리스트 (`/agents`, `/bundle/agents`, `/bundle/mcp`)**
- `GET /api/source-meta?kind=agent&limit=50&offset=0` (표준 페이지네이션). TanStack Query로 캐시, 30s staleTime.
- **Agent 목록**(general `/agents`, bundle `/bundle/agents`) 공통 tail 열: `chat_selectable`(헤더 **Chatable**) · `created_at` · `retired` 배지(**Status**). bundle agent는 deploy context가 이미 bundle이므로 **Mode** 열 없음.
- general agent 열: `name`, `version`, `visibility`, Chatable, Created, Status.
- bundle agent 열: `name`, `version`, `runtime_pool`, `checksum`(prefix 8자), Chatable, Created, Status.
- bundle MCP 열: `name`, `version`, `runtime_pool`, `checksum`, Created, Status (Mode 없음).
- **Container agent 리스트** (`/container/agents`): `name`, `version`, `slug`, `image_uri`, Chatable, Created, Status, Actions.
- 필터: `name` prefix 검색(디바운스 300ms) + `retired` 토글.
- 페이저: `total` 기준. 다음/이전 버튼 + 현재 페이지 표기.
- row 클릭 → 상세. `+ 새로 등록` 버튼 → `/:kind/new`.

**source_meta 생성 (`/agents/new`)**
- 두 가지 모드 택일(탭):
  1. **외부 URI 등록** — `bundle_uri`(s3/http/oci/file) 입력 → `POST /api/source-meta`.
     - http(s) → 서버가 fetch+sha256, 응답에서 최종 `checksum` 수신.
     - s3/oci → 프런트가 **`checksum`(`sha256:<hex>`) 필수 필드**로 요구. 안 입력하면 서버가 400.
     - `file://` → 개발용.
  2. **zip 업로드** — 파일 선택 → `POST /api/source-meta/bundle` (multipart).
     - 파트: `file`(zip) + 선택 `sig`(서명 blob) + `meta`(JSON: 나머지 필드).
     - 클라 체크: 확장자(`.zip`), 크기 `<=MAX_BUNDLE_SIZE_MB` (서버 최종). 실패 시 업로드 시작 전 조기 차단.
     - 서버 에러 매핑: `413` "파일이 너무 큼", `400 "invalid zip"` → "zip이 손상됐습니다", `409` → "같은 `(kind, name, version)` 중복".
- 공통 필드: `kind`(URL로 고정), `name`, `version`, `runtime_pool`(드롭다운 — enum은 `runtime_common.schemas` 또는 BFF 엔드포인트에서), `entrypoint`(`module.path:attr` regex 체크), **`config`** (JSON editor — 번들 기본값, 생략 시 `{}`).
- 제출 시 `422`는 zod 스키마와 매핑해 필드별 에러 표시. `400`은 전역 toast.

**general agent 생성·편집 (`/agents/new/general`, general `deploy_mode` 상세)**
- 필드: `name`(전체 너비), `version` + **`사용 권한`**(`visibility` — `<select>`, 동일 행 반씩), `system_prompt`, MCP 서버(체크박스), **Pipeline projects**(복수 선택, binding 미리보기), `config` JSON.
- MCP 중 `requires_knowledge_project=true`인 서버를 고르면 project 1개 이상 필수 (`access-resources.requires_knowledge_project`).
- `tenant` 옵션은 세션에 `tenant`가 없으면 disabled + 안내 문구. 기본값 `private`.
- 생성 `POST /api/source-meta/general`, 편집 `PATCH /api/source-meta/general/{id}`.

**Hermes agent 생성·조회 (`/agents/new/hermes`, `/agents/hermes/:id`)**
- Agent nav 하위 탭: **General** (`/agents`) · **Hermes** (`/agents/hermes`).
- 필드: `name`, `version` + `visibility`, **`soul`**(SOUL.md), MCP 서버(체크박스, 필수), `skills`(쉼표 구분, optional), `model`(optional), `config` JSON(optional).
- VFS seed: 등록 시 `/profile/SOUL.md`, `/profile/config.yaml`, `/profile/skills/{name}.enabled` — admin VFS UI에서 확인.
- 생성 `POST /api/source-meta/hermes-general`. 편집 `PATCH /api/source-meta/hermes-general/{id}` + `usePatchHermesAgent`.
- 목록 `GET /api/source-meta?kind=agent&deploy_mode=hermes_general` — general과 동일 visibility 필터(비-developer 허용).

**MCP bundle 등록 (`/bundle/mcp/new`)**
- 체크박스 **Pipeline project binding 필요** → `config.knowledge.requires_project`. path-graph retrieval MCP(image) 등에서 사용.

**MCP Image 등록·편집 (`/container/mcp/new`, `/container/mcp/:slug/edit`)**
- 동일 체크박스 → `config.knowledge.requires_project` (MCP Image 기본 checked).

**source_meta 상세 (`/agents/:id`)**
- 메타 정보 + 현재 버전 + 같은 `(kind, name)`의 다른 버전 리스트.
- **편집 가능 필드 (PATCH 화이트리스트)**: `entrypoint` · `runtime_pool` · `sig_uri` · `config` · `user_meta_template`. 나머지(`name`/`version`/`checksum`/`bundle_uri` 등)는 **readonly 표시**로 UI에서 편집 불가. 실수로 body에 섞여도 서버 400.
- **`config` 섹션**: 번들 기본 config JSON 편집기(`PATCH /api/source-meta/{id}` 로 저장). 경고 문구: "의미 변경이면 새 버전 권장 — 현재 로직은 `PATCH` 허용이지만 runtime 캐시/checksum 기반 warm pod는 재로드되지 않음".
- 액션 (상세 페이지 우측 패널):
  - `서명 파일 교체`: `<input type=file accept=".sig">` 다이얼로그 → `POST /api/source-meta/{id}/signature` (multipart `sig`). 성공 시 `sig_uri` 업데이트된 카드.
  - `무결성 검증` (nice-to-have): `POST /api/source-meta/{id}/verify` → 저장 파일의 sha256 재계산 + 서명 재검증. 결과를 토스트/패널로.
  - `retire`: `POST /api/source-meta/{id}/retire` → confirm dialog → `retired=true` 표시.
  - `delete`: `DELETE /api/source-meta/{id}` (dev/stage only, `ALLOW_HARD_DELETE=true`일 때만 서버가 수락). confirm dialog. 409 → "다른 버전이 같은 bundle을 참조 중" 메시지.
- **User Meta Template 탭**: `enabled`로 필요 여부 선택. `enabled: true`일 때만 필드 path/label/type/required 정의 + live preview. `enabled: false`면 사용자 Integrations에 "Not required" 표시.
- **Access 탭**: grant/revoke (`AccessList`).

**본인 프로필 (`/me`)**
- Account Info + Change Password (2열) + **API Keys** + **Integrations** (전체 너비, 순서대로).
- **API Keys** — `GET|POST|DELETE /api/me/api-keys`. 목록(이름·생성·만료·상태) + 발급 다이얼로그(`name`, 선택 `expires_in_days`) + 폐기(confirm). plain key(`ak_…`)는 **생성 응답 1회만** 표시·복사 UI; 이후 목록에는 해시·plaintext 없음. 복사는 `lib/copyToClipboard.ts`(Clipboard API → `execCommand` fallback — dev HTTP Ingress 대응). path-graph 등 장기 invoke용(`PIPELINE_AGENT_ACCESS_TOKEN`) — agent/MCP `user_resource_access`는 별도 grant.
- **Integrations** — Agent → MCP 탭. `user_meta_required`인 리소스만 표시.
- `GET /api/me/access-resources?kind=` — JWT `Principal.access` 기준 목록.
- user-meta 편집: `/me/user-meta/:kind/:name` — **모달**로 열림 (URL·뒤로가기 지원). template + 본인 config.

**사용자 리스트 (`/users`)**
- `GET /api/users?username=<prefix>&tenant=&disabled=&limit=50&offset=0` (표준 페이지네이션).
- 열: `username`, `tenant`, `is_admin` 배지, `disabled` 배지, `created_at`.
- 필터: `username` prefix(디바운스) + `tenant`·`disabled` 드롭다운.
- row 클릭 → 상세. `+ 사용자 추가` 버튼 → `/users/new`.

**사용자 생성 (`/users/new`)**
- 필드: `username`(unique), `password`(min=12, 정책 클라이언트 힌트만 — 서버가 최종), `tenant`(optional), `is_admin`(체크박스).
- `POST /api/users`. 409(중복)·400(정책) 에러 처리.

**사용자 상세 (`/users/:id`)**
- 상단: 프로필. **읽기 전용 필드**: `username`, `id`, `created_at`. **편집 가능 필드 (PATCH 화이트리스트)**: `tenant`, `disabled`, `is_admin`.
- PATCH 부수 효과 안내: `disabled=true` 또는 `is_admin=false`로 토글하면 서버가 **그 사용자의 모든 세션(refresh token)을 즉시 revoke**. 토글 전 confirm dialog에 "해당 사용자가 바로 로그아웃됩니다" 문구. 성공 시 toast에 "세션 종료됨".
- 액션:
  - `비밀번호 리셋`: 새 비번 입력 다이얼로그 → `POST /api/users/{id}/password`. 성공 시 toast에 "모든 세션 로그아웃됨. 사용자는 다음 로그인 시 비번 변경이 강제될 수 있습니다." (`must_change_password=true` 세팅되는 경우).
  - `사용자 삭제`: confirm dialog → `DELETE /api/users/{id}`. self/마지막 admin이면 서버가 400, UI는 에러 표시.
- 탭 `access`: 이 사용자가 쓸 수 있는 `(kind, name)` 리스트. 표준 페이지네이션.
  - 추가: 드롭다운으로 기존 source_meta의 `name` 선택(`GET /api/source-meta?kind=`로 옵션 로드) → `POST /api/users/{id}/access` (중복 시 204, 에러 없음).
  - 제거: row 우측 `x` 버튼 → `DELETE /api/users/{id}/access?kind=&name=`. 토스트 불필요(즉시 반영).

**리소스 관점의 access (`/agents/:id`, `/mcp-servers/:id`)**
- 상세 페이지 하단에 "이 리소스를 쓸 수 있는 사용자" 섹션.
- `GET /api/source-meta/{id}/access` — user 목록, 표준 페이지네이션.
- 행별 제거 버튼(`DELETE /api/users/{user_id}/access?kind=&name=`).
- `+ 사용자 추가`: 사용자 검색 자동완성 → grant (`POST /api/users/{user_id}/access`).
- **쿼리 무효화 규약**: user→resource 또는 resource→user 어느 쪽에서 변경하든 **양쪽 쿼리 키를 invalidate** (`['users', id, 'access']` + `['source-meta', id, 'access']`). 다른 페이지에서 열어둔 뷰가 stale하지 않도록.

**본인 프로필 (`/me`)**
- 비밀번호 변경: current + new 두 필드 → `POST /api/me/password`. 성공 시:
  - 서버가 본인 refresh 전체 revoke → 현재 access token은 만료까지 유효, 새 요청에 refresh 교환 시 실패.
  - UI는 "다시 로그인하세요" 안내 + **자동 로그아웃** → `/login`.
- **`must_change_password==true` 강제 모드**:
  - 가드가 다른 라우트 접근을 차단. 페이지 상단에 경고 배너("비밀번호를 변경해야 계속 사용할 수 있습니다").
  - 변경 성공 시 서버가 `must_change_password=false` 업데이트(본인 password 경로의 부수 효과) → 자동 로그아웃 → 재로그인 후 일반 가드로 복귀.
- 비-admin 사용자가 `/me`와 `/chat`만 접근 가능.

**챗 (`/chat`)**
- agent 선택 → `GET /api/me/access-resources?kind=agent`. 사이드바는 `{name}`만 표시(latest 참고용).
- **버전 핀**: New Chat 시 BFF가 latest `source_meta.version`을 `chat_threads.agent_version`에 저장. 이후 invoke는 thread의 pinned version을 body·`x-runtime-version`에 포함 — mid-thread silent upgrade 방지.
- invoke 흐름: `GET /api/auth/access-token` → `POST ${VITE_AGENTS_INVOKE_URL}` body `{agent, version, input: {message}, session_id, stream: true}` + Bearer/`x-runtime-name`/`x-runtime-version`/`x-runtime-session-id` 헤더. Ingress → Envoy → ext-authz → pool.
- 응답은 `text/event-stream`. agent-base emit 포맷(runtime_kind별 LangGraph/ADK/CUSTOM)을 `lib/chatStream.ts`의 `extractTextFromAgentEvent()`로 UI용 텍스트 델타로 정규화(BFF `/api/chat/invoke`에 있던 규칙과 동일). `[DONE]`·`{"error":…}`·BFF 레거시 `{"text":…}` 모두 처리.
- 파싱은 fetch + `ReadableStream`(`lib/agentsInvoke.ts`). `\n\n` 단위 버퍼링.
- `session_id`는 페이지 진입 시 **New Chat** → `POST /api/me/chat/threads` 응답의 `session_id`(= DB `provider_session_id`)로 발급·재사용. 플랫폼 thread `id`와 분리.
- **Recent Chats** — `GET /api/me/chat/threads` 목록. 선택 시 `GET .../threads/{id}` + `GET .../messages`로 hydrate 후 동일 `session_id`로 invoke 연속.
- 메시지 전송 후 `POST .../threads/{id}/touch`로 `title`·`last_message_at` 갱신.
- 삭제는 `DELETE .../threads/{id}`(소프트). provider 데이터 정리는 `scripts/purge_deleted_chat_threads.py` 배치.

**Frontend env**

| 변수 | 기본 | 용도 |
|---|---|---|
| `VITE_AGENTS_INVOKE_URL` | `/v1/agents/invoke` | Chat invoke POST URL (Docker build ARG로 prod 주입) |
| `VITE_DEV_ENVOY_PROXY_TARGET` | `http://127.0.0.1:8084` | Vite dev만 — `/v1/agents` 프록시 대상(wire-dev Envoy PF) |

### 폴더 구조

```
src/
  main.tsx
  App.tsx                   라우터 루트
  lib/
    api.ts                  fetch 래퍼 (CSRF 헤더 자동, 401/412 처리, 페이지네이션 응답 파서)
    queryClient.ts          TanStack Query 설정 (+ invalidation 헬퍼)
    schemas.ts              zod 스키마 (backend Validation 표와 1:1)
    enums.ts                AgentRuntimeKind / McpRuntimeKind (runtime_common.schemas 동기화)
    mergeConfigs.ts         shallow merge(user wins) — 2-pane 프리뷰용
    env.ts                  VITE_AGENTS_INVOKE_URL
    chatStream.ts           agent-base SSE → text delta
    agentsInvoke.ts         Bearer handoff + Envoy invoke
  pages/
    LoginPage.tsx
    DashboardPage.tsx
    SourceMetaListPage.tsx           (페이지네이션 + 필터)
    SourceMetaNewPage.tsx            (URI 모드 / zip 업로드 모드 탭)
    SourceMetaDetailPage.tsx         (편집 + 서명교체 + verify + access 역조회)
    UserMetaEditPage.tsx             (2-pane + merge 프리뷰)
    UsersListPage.tsx
    UserNewPage.tsx
    UserDetailPage.tsx               (PATCH 화이트리스트 + access 탭)
    MePage.tsx                       본인 비번 변경 + must_change_password 강제 모드
    AuditLogPage.tsx                 GET /api/audit — details는 `lib/formatAuditDetailValue.ts`로 스칼라·배열·객체를 읽기 쉬운 문자열로 표시
    ChatPage.tsx                     agent 선택 + 메시지 + SSE 스트리밍
  components/
    Layout.tsx                       nav + sidebar
    RequireAuth.tsx                  세션 가드
    RequireNotForcedChangePassword.tsx  must_change_password 가드
    RequireAdmin.tsx                 is_admin 가드
    Paginator.tsx                    limit/offset 페이저 (total 기반)
    JsonEditor.tsx                   react-json-view-lite 또는 textarea+zod
    FileDropZone.tsx                 drag&drop + 크기/확장자 클라 체크
    SignatureUploadDialog.tsx        .sig 교체
    ConfirmDialog.tsx                (+ destructive 변형 지원)
    AccessList.tsx                   (user↔resource 양방향 공유)
    UserSearchInput.tsx              user combobox (browse on focus, prefix search, no autofill)
    GeneralAgentVisibilityField.tsx  사용 권한 4모드 (private/tenant/public/allowlist)
    ErrorBoundary.tsx                500 전역
  hooks/
    useSession.ts                    GET /api/me (is_admin + must_change_password 포함)
    useSourceMeta.ts                 list / get / create / patch / retire / delete / signature / verify
    useMyUserMeta.ts                 self-service access-resources / user-meta
    useUserMeta.ts                   admin get / upsert / delete (break-glass)
    useUsers.ts                      list / create / patch / password / delete
    useAccess.ts                     grant / revoke (양쪽 쿼리 동시 invalidate)
    useViewportPagination.ts       뷰포트 기반 limit/offset + anchorRef
    viewportPageLimit.ts           행 수 계산 유틸
```

### 접근성·i18n

- MVP는 **ko** only. 나중에 `react-i18next` 도입하되 지금은 문자열 직접.
- 키보드 네비게이션 / focus ring은 shadcn/ui가 기본 제공. 추가 검증은 Lighthouse 수동.

