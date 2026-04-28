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

- **모든 호출은 `/api/*`** — Vite dev 서버는 `http://localhost:8000`으로 프록시(기존 `vite.config.ts` 설정 그대로).
- 프로덕션은 같은 origin에서 BFF가 SPA 정적 파일까지 서빙하거나, 별 origin이면 BFF의 `CORS_ORIGINS`에 SPA origin 등록.
- **인증 쿠키는 자동 전송**. fetch는 `credentials: "include"` 기본값 유지(same-origin이면 불필요, cross-origin이면 필수).
- **CSRF**: state-changing 요청(POST/PUT/DELETE/PATCH)은 `X-CSRF-Token` 헤더 필수. 로그인 응답으로 받은 `csrf_token` cookie 값을 읽어서 첨부(double-submit cookie). 이는 httpOnly가 아니므로 JS에서 읽힘.
- **페이지네이션 표준** (모든 list GET):
  - 요청: `?limit=<1..100, default 50>&offset=<>=0, default 0>`. 서버가 `limit>100`은 100으로 clamp.
  - 응답: `{items: [...], total: N, limit: L, offset: O}`. UI는 `total`로 페이지 수 계산(offset 기반).
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
/agents/:id                            상세 + 버전 목록 + retire/delete + access(이 agent 사용 가능한 user 목록)
/agents/:id/user-meta/:principal       user_meta 편집 (config JSON + secrets_ref)
/mcp-servers                           source_meta list (kind=mcp)
/mcp-servers/new                       생성
/mcp-servers/:id                       상세 + access
/mcp-servers/:id/user-meta/:principal  user_meta 편집
/users                                 사용자 리스트 (admin만)
/users/new                             사용자 생성 (username + password + tenant + is_admin)
/users/:id                             사용자 상세 + password 리셋 + disabled/is_admin 토글 + access 관리
/me                                    본인 프로필 (비번 변경)
/chat                                  agent 선택 → 대화 (SSE 스트리밍)
```

**가드 매트릭스**:

| 조건 | 리다이렉트 |
|---|---|
| 세션 없음 | `/login` |
| 세션 있음 + `must_change_password==true` | `/me` (비번 변경 강제 — 다른 모든 라우트 접근 차단) |
| 세션 있음 + `is_admin==false` | `/me` 와 `/chat` 만 허용 |
| 세션 있음 + `is_admin==true` + `must_change_password==false` | 모든 라우트 허용 |

구현은 `<RequireAuth />` → `<RequireNotForcedChangePassword />` → `<RequireAdmin />` 중첩 가드. 각 라우트 정의에서 필요한 레벨까지만 감쌈. `useSession()` 훅이 `{user_id, username, tenant, is_admin, must_change_password}` 노출.

공통 레이아웃: 상단 nav(에이전트 / MCP / 사용자 / 챗 / 로그아웃), 좌측 사이드바는 리스트 화면에서만.

### 주요 화면별 흐름

**source_meta 리스트 (`/agents`, `/mcp-servers`)**
- `GET /api/source-meta?kind=agent&limit=50&offset=0` (표준 페이지네이션). TanStack Query로 캐시, 30s staleTime.
- 열: `name`, `version`, `runtime_pool`, `checksum`(prefix 8자), `created_at`, `retired` 배지.
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

**source_meta 상세 (`/agents/:id`)**
- 메타 정보 + 현재 버전 + 같은 `(kind, name)`의 다른 버전 리스트.
- **편집 가능 필드 (PATCH 화이트리스트)**: `entrypoint` · `runtime_pool` · `sig_uri` · `config`. 나머지(`name`/`version`/`checksum`/`bundle_uri` 등)는 **readonly 표시**로 UI에서 편집 불가. 실수로 body에 섞여도 서버 400.
- **`config` 섹션**: 번들 기본 config JSON 편집기(`PATCH /api/source-meta/{id}` 로 저장). 경고 문구: "의미 변경이면 새 버전 권장 — 현재 로직은 `PATCH` 허용이지만 runtime 캐시/checksum 기반 warm pod는 재로드되지 않음".
- 액션 (상세 페이지 우측 패널):
  - `서명 파일 교체`: `<input type=file accept=".sig">` 다이얼로그 → `POST /api/source-meta/{id}/signature` (multipart `sig`). 성공 시 `sig_uri` 업데이트된 카드.
  - `무결성 검증` (nice-to-have): `POST /api/source-meta/{id}/verify` → 저장 파일의 sha256 재계산 + 서명 재검증. 결과를 토스트/패널로.
  - `retire`: `POST /api/source-meta/{id}/retire` → confirm dialog → `retired=true` 표시.
  - `delete`: `DELETE /api/source-meta/{id}` (dev/stage only, `ALLOW_HARD_DELETE=true`일 때만 서버가 수락). confirm dialog. 409 → "다른 버전이 같은 bundle을 참조 중" 메시지.
- `user_meta` 섹션: principal별 설정 테이블. 열: `principal_id`, `config` 요약(키 수), `secrets_ref`, `updated_at`. row → 편집. 페이지네이션 표준.

**user_meta 편집 (`/.../user-meta/:principal`)**
- `GET /api/user-meta?kind=&name=&version=&principal=` (없으면 404 → 빈 폼).
- `config`: JSON editor (monaco-editor 또는 가벼운 `react-json-view` + 텍스트 모드 토글). zod로 JSON 파싱 검증. **2-pane 레이아웃** — 좌측 `source.config`(read-only), 우측 `user.config`(편집), 하단에 **merge 프리뷰** (shallow merge, user wins) 표시. 사용자가 덮어쓴 키를 강조.
- `secrets_ref`: 단일 문자열 입력 (`vault://...` / `env://...` 등).
- 저장: `PUT /api/user-meta` (upsert). 성공 시 invalidate `user-meta` + `source-meta` 쿼리.

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
- agent 선택 드롭다운 → `GET /api/source-meta?kind=agent&retired=false`로 사용 가능한 agent 리스트(BFF가 `Principal.access` 기준으로 필터). 현재 드롭다운 표시는 `{name} ({version})`이지만 송신 페이로드에는 `name`만 포함 → 항상 latest로 라우팅(버전 핀 정책 결정은 ROADMAP 참조).
- 입력 → `POST /api/chat/invoke` body `{agent, input: {message}, session_id, stream: true}`. 응답은 `text/event-stream` 단일 채널, 세 가지 이벤트만 처리:
  - `data: {"text": "<delta>"}` — 누적 append, assistant 메시지의 streaming flag 유지.
  - `data: {"error": "<detail>"}` — throw해서 기존 빨간 에러 배너 경로 재사용. 받은 직후 종료.
  - `data: [DONE]` — 정상 종료, streaming flag false 전환.
  - 그 외(주석/빈 라인 등)는 무시. 포맷 정규화는 BFF가 책임 — 자세한 규약은 [backend/DESIGN.md](../backend/DESIGN.md)의 "Chat invoke" 참조.
- 파싱은 fetch + `ReadableStream`으로 직접 처리(`EventSource`는 cookie 인증·POST 미지원). `\n\n` 단위 버퍼링, `data:` prefix 라인만 JSON.parse.
- `session_id`는 페이지 진입 시 `crypto.randomUUID()`로 발급해 동일 대화 동안 재사용. "New Chat" 버튼이 abort + 새 UUID + messages 초기화. 새로고침에 유지할 필요 있으면 localStorage(JWT와 달리 민감정보 아님).

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
    AuditLogPage.tsx                 (향후 /api/audit)
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
    UserSearchInput.tsx              prefix autocomplete
    ErrorBoundary.tsx                500 전역
  hooks/
    useSession.ts                    GET /api/me (is_admin + must_change_password 포함)
    useSourceMeta.ts                 list / get / create / patch / retire / delete / signature / verify
    useUserMeta.ts                   get / upsert / delete
    useUsers.ts                      list / create / patch / password / delete
    useAccess.ts                     grant / revoke (양쪽 쿼리 동시 invalidate)
    usePagination.ts                 limit/offset 상태 + URL sync
```

### 접근성·i18n

- MVP는 **ko** only. 나중에 `react-i18next` 도입하되 지금은 문자열 직접.
- 키보드 네비게이션 / focus ring은 shadcn/ui가 기본 제공. 추가 검증은 Lighthouse 수동.

