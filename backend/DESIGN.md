# backend (admin console)

관리 콘솔 프런트엔드([`../frontend/`](../frontend/))가 쓰는 서버. BFF 역할 + **`source_meta` / `user_meta` 쓰기 소유자**.

`agent-runtime.d2`의 `admin.admin_service` 노드에 해당 — 여기서 deploy-api로 화살표가 나가는 부분이 원래 설계 의도였다. 지금까지 deploy-api에 임시로 들어가 있던 CRUD를 이 서비스로 이전한다.

## 포지셔닝

**왜 쓰기를 deploy-api가 아니라 admin backend가 소유하는가**:
- deploy-api는 **런타임 크리티컬 경로** (모든 invoke가 `/v1/resolve`를 통과). 관리 UI의 CRUD·파일 업로드·검증 로직이 같은 프로세스에 붙으면 장애 반경이 runtime까지 번진다.
- admin은 소수 운영자용·저 QPS·긴 트랜잭션(파일 업로드). 프로세스·replica·스케일 정책이 전혀 다르다.
- 소유권 분리로 deploy-api는 read replica를 마음껏 쓰고, admin backend는 primary에 write할 수 있다.

**담당 O / X**:

| O | X |
|---|---|
| `source_meta` 테이블 INSERT/UPDATE/DELETE | `/v1/resolve` 제공 — 런타임 경로는 deploy-api 전용 |
| `user_meta` 테이블 INSERT/UPDATE/DELETE | runtime invoke 라우팅 — gateway 소유 |
| `users` 테이블 INSERT/UPDATE/DELETE + 비밀번호 해싱(argon2id) | `/login` / `/verify` — auth 전용 (users/access는 auth에선 read-only) |
| `user_resource_access` 테이블 INSERT/DELETE (grant/revoke) | JWT 발급·서명 / refresh token 발급·rotate·revoke — auth 전용 |
| bundle zip 수신·저장·checksum 계산 | `source_meta` 내용 해석(entrypoint 파싱 등) — 필드는 그대로 저장만 |
| auth 서비스 프록시(login/logout/refresh) | 런타임 토큰 grace·권한 판정 — auth 내부 |
| 세션(httpOnly cookie) + CSRF | |
| 관리 UI용 read — Postgres 직결 | `/v1/resolve` 계열 read — deploy-api 전용 |
| Envoy 경유 agent invoke 프록시(`/api/chat/invoke`) | LLM 호출 / 응답 가공 |

## 설계

### DB / 업스트림

- **Postgres 직결** — 네 테이블의 **쓰기 소유자**:
  - `source_meta` (immutable·versioned) — INSERT/DELETE/retire
  - `user_meta` (mutable, per-principal) — upsert/DELETE
  - `users` (login credentials + admin flag) — INSERT/UPDATE/DELETE + 비밀번호 해싱
  - `user_resource_access` (user ↔ (kind,name) 매핑) — INSERT/DELETE(grant/revoke)
  - `refresh_tokens`는 제외 — auth가 issue/rotate/revoke하는 짧은 수명 상태라 auth 전용으로 유지.
  - DSN: `POSTGRES_DSN` (write, asyncpg URL). 읽기 replica 분리는 admin 규모에선 과하므로 MVP는 primary 단일.
  - `runtime_common.db.make_engine` / `session_scope` 재사용.
  - SQLAlchemy 모델: **`runtime_common.db.models` 공용 사용** (backend·deploy-api·auth 세 서비스가 같은 선언을 import). backend가 자체 `models.py`를 두지 않는다. 공용화는 [../packages/common/DESIGN.md](../packages/common/DESIGN.md) "공용 DB 모델 리팩토링" 참조.
  - 마이그레이션: **`backend/migrations/0001_init.sql`** — 모든 테이블 단일 파일(과거 auth/deploy-api별 분할을 통합). 적용은 `make db-migrate` 또는 `deploy/k8s/base/migration-job.yaml`의 `db-migrate` Job.
- **auth 서비스**: `AUTH_URL` — `/login`, `/refresh`, `/logout`, `/verify` 프록시.
- **deploy-api는 호출하지 않는다** — admin은 DB를 직접 보므로 proxy 단계를 거치지 않는다. deploy-api의 resolve 캐시(in-memory, 5s TTL)는 자연 만료로 eventual consistency. auth도 같은 이유로 `users`/`user_resource_access` read 캐시(TTL ~5s)가 admin write 이후 자연 만료.

### 인증 / 세션 (BFF)

- **로그인**: `POST /api/auth/login` → auth `/login`으로 프록시. 성공 시 `access_token`·`refresh_token`을 **httpOnly, Secure, SameSite=Strict cookie**로 저장(XSS 노출 차단). 응답 바디에는 공개 정보(`username`, `tenant`, `user_id`, `is_admin`)만.
- **요청 인가**: admin API는 전부 세션 쿠키 필요. cookie에서 JWT 꺼내 `AuthClient.verify(token, grace_sec=0)` → `Principal`. **admin 판정은 `principal.is_admin`** — `users.is_admin` 컬럼에서 auth가 `/login` 시 JWT claim으로 싣고 `/verify`가 `Principal`에 실어 내린다. `is_admin==False`면 로그인 자체는 성공하지만 admin API 호출은 403(프런트가 "관리자 권한 없음" 페이지). MVP에 bootstrap용으로 `ADMIN_USERNAMES` env(쉼표 구분) 폴백 — `users.is_admin`이 스키마에 없거나 초기 마이그레이션 전이면 사용, 이후 컬럼으로 완전 전환.
- **CSRF**: cookie-based → double-submit cookie. 로그인 응답에 non-httpOnly `csrf_token` cookie 동봉, 프런트엔드는 `X-CSRF-Token` 헤더로 에코. 불일치 시 403.
- **토큰 만료**: access 만료 감지 시 BFF가 refresh로 **내부에서** 자동 재발급 후 원요청 재시도 1회. refresh도 만료면 401 → 프런트가 `/login`으로.

### 엔드포인트

모두 `/api/*`. state-changing(POST/PUT/DELETE)은 CSRF 헤더 필수.

| method | path | 처리 | 비고 |
|---|---|---|---|
| `POST` | `/api/auth/login` | auth `/login` 프록시 + cookie 세팅 + CSRF 토큰 발급 | admin allowlist 검사 |
| `POST` | `/api/auth/logout` | auth `/logout` (refresh revoke) + cookie 삭제 | |
| `GET` | `/api/me` | cookie claims 파싱 (업스트림 호출 X) | |
| `GET` | `/api/source-meta` | Postgres SELECT, filter `kind`/`name`(prefix)/`retired` | list, 표준 페이지네이션(아래 "Pagination") |
| `GET` | `/api/source-meta/{id}` | Postgres SELECT by id | 상세 |
| `POST` | `/api/source-meta` | Postgres INSERT — `bundle_uri` 기반(외부 URI 등록). body에 `config: dict` 포함(생략 시 `{}`). URI 모드 checksum 정책은 아래 "URI 모드" | 409 중복(kind,name,version) |
| `POST` | `/api/source-meta/bundle` | **multipart** → atomic 저장 → checksum → INSERT. `config`·`sig` 필드 포함 가능 | 아래 "Bundle 저장소" |
| `POST` | `/api/source-meta/{id}/signature` | 이미 등록된 source에 서명 파일만 **추가/교체** (multipart, `.sig`) | sig_uri 업데이트 |
| `POST` | `/api/source-meta/{id}/verify` | 저장된 bundle의 sha256 재계산 + 서명 재검증 | 무결성 체크 (향후) |
| `PATCH` | `/api/source-meta/{id}` | 필드별 부분 수정 (아래 "PATCH 화이트리스트") | `name`/`version`/`checksum`/`bundle_uri`/`password_*`는 400 거절 |
| `POST` | `/api/source-meta/{id}/retire` | `retired=true` toggle | soft delete |
| `DELETE` | `/api/source-meta/{id}` | Postgres DELETE + bundle 파일 정리(ours) | dev/stage only (`ALLOW_HARD_DELETE`) |
| `GET` | `/api/user-meta` | Postgres SELECT by `(kind,name,version,principal)` 또는 `(source_meta_id, principal)` | |
| `PUT` | `/api/user-meta` | Postgres UPSERT `(source_meta_id, principal_id)` | `config`/`secrets_ref` 갱신 |
| `DELETE` | `/api/user-meta/{id}` | Postgres DELETE | |
| `GET` | `/api/users` | Postgres SELECT, filter `username`/`tenant`/`disabled` | 페이지네이션 |
| `GET` | `/api/users/{id}` | Postgres SELECT by id | 비밀번호 해시는 응답에 없음 |
| `POST` | `/api/users` | argon2id hash + Postgres INSERT | `{username, password, tenant?, is_admin?}`, 409 중복 |
| `PATCH` | `/api/users/{id}` | Postgres UPDATE | `{tenant?, disabled?, is_admin?}` — 자기 자신의 `is_admin=false`는 금지(락아웃 방지) |
| `POST` | `/api/users/{id}/password` | argon2id re-hash + UPDATE + refresh token revoke all | 관리자 강제 변경. 본인 변경은 별 경로로 분리 가능(`POST /api/me/password`) |
| `DELETE` | `/api/users/{id}` | Postgres DELETE (cascade: `user_resource_access`, `refresh_tokens`) | 자기 자신 삭제 금지 |
| `GET` | `/api/users/{id}/access` | Postgres SELECT from `user_resource_access` where `user_id=?` | 허용 리소스 목록 |
| `POST` | `/api/users/{id}/access` | Postgres INSERT `(user_id, kind, name)` | 중복은 204(idempotent) |
| `DELETE` | `/api/users/{id}/access` | Postgres DELETE by `(user_id, kind, name)` | 쿼리 파라미터로 `kind`, `name` |
| `GET` | `/api/source-meta/{id}/access` | Postgres SELECT user_resource_access JOIN users (해당 리소스에 접근 가능한 user 목록) | 리소스 관점의 역조회 |
| `GET` | `/api/audit` | Postgres SELECT from audit_log (향후 도입) | 감사 조회 (향후) |
| `POST` | `/api/admin/custom-images` | Image 모드 agent/MCP 등록 (admin only) — slug 생성·검증 → `source_meta` INSERT (`status='pending'`) → K8s 4종 apply → ready 확인 → `status='active'` | 아래 "Custom Image 관리" |
| `GET` | `/api/admin/custom-images` | Image 모드 목록 조회. `?kind=agent\|mcp` 필터 | |
| `DELETE` | `/api/admin/custom-images/{kind}/{slug}` | `source_meta` retire + K8s 4종 삭제 | 204 |
| `PATCH` | `/api/admin/custom-images/{kind}/{slug}` | `replicas_max`/`resources`/`env`/`config` 운영 파라미터 업데이트. `image_uri`/`image_digest` 변경은 새 version 등록으로 강제 | 200 |
| `GET` | **`/bundles/{sha256}.zip`** | 파일시스템(또는 S3 presigned) read-only 서빙 | **auth 없음 — NetworkPolicy로 클러스터 내부만**. pool이 이 URL로 fetch. `bundle_uri`에 박히는 주소. |
| `GET` | **`/bundles/{sha256}.sig`** | 서명 파일 서빙 (있을 때만) | 위와 동일 경로 규칙 |
| `POST` | `/api/chat/invoke` | Envoy → agent-pool 스트리밍 프록시 + SSE 정규화 | 아래 "Chat invoke" 참조 |

**Bundle 모드 vs Image 모드 분류**: `POST /api/source-meta` 계열은 **bundle 모드** 전용 (entrypoint + bundle_uri 필수). `POST /api/admin/custom-images`는 **image 모드** 전용 (image_uri 필수, entrypoint/bundle_uri 불필요). 두 체계는 `source_meta` 테이블에 공존 — `deploy_mode` 컬럼으로 구분.

**불변 필드 방침**: `source_meta.(kind, name, version, checksum, bundle_uri)`는 생성 후 변경 금지 — 버전 새로 찍는 게 정답. `PATCH`는 `entrypoint`/`sig_uri`/`runtime_pool`/`config` 오기재 수정 정도만 허용(감사 로그에 before/after 기록).

**`config` 필드**: 번들 기본 config(immutable 의도지만 row-level `PATCH`는 허용). runtime이 `user_meta.config`와 shallow merge(user wins)해 factory에 주입 — 자세한 합의는 [/DESIGN.md](../DESIGN.md)의 "source_meta / user_meta config 병합". admin UI는 두 config를 나란히 편집할 수 있어야 하며, 덮어쓰기 프리뷰(merge 결과)도 보여주면 유용.

### Custom Image 관리

Image 모드 pool — admin이 빌드한 OCI 이미지를 등록하면 backend가 K8s Deployment+Service를 동적으로 생성해 운영하는 체계. Bundle 모드(shared base + 번들 동적 로드)와 공존.

#### Image contract

임의 언어·프레임워크로 빌드한 이미지가 다음만 만족하면 된다. SDK 의존 없음.

- **HTTP** (포트 8080): `POST /invoke` · `GET /healthz` · `GET /readyz`
- **k8s 주입 env**: `RUNTIME_POOL="{kind}:custom:{slug}"`, `DEPLOY_API_URL`, `POD_NAME`/`POD_IP`/`POD_PORT`
- **`x-principal` 헤더**: ext-authz가 invoke 요청에 base64(JSON) 형태로 주입. image는 신뢰.
- **`x-runtime-cfg` 헤더**: ext-authz가 `{**source.config, **user.config}` shallow merge를 base64(JSON)으로 첨부. deploy-api 직접 호출 불필요.
- **`x-runtime-secrets-ref` 헤더**: `user_meta.secrets_ref` opaque 패스스루 (`vault://...` 등). 실제 비밀값 resolution은 image author 책임.

#### State-machine 배포 (`POST /api/admin/custom-images`)

```
payload 수신
 → slug 생성/검증 (auto-derive 또는 admin 명시, (kind,slug) UNIQUE)
 → config 크기 검증 (≤ 16 KB)
 → source_meta INSERT (status='pending', deploy_mode='image')  [DB commit]
 → K8s apply: Deployment(replicas=1) + Service + ScaledObject(minReplicas=1) + PDB(minAvailable=1)
 → Deployment ready poll (budget 60s)
 → 성공: status='active'  (resolve 대상에 노출)
 → 실패: status='failed'  (K8s 리소스는 reconciler가 정리)
```

앱 크래시 시 DB는 `status='pending'`, K8s는 부분 생성 상태 → reconciler가 복구.

#### Slug 규칙

- 자동 derive: `slugify(name)-slugify(version)` (예: `Summarizer Agent` + `v2.0` → `summarizer-agent-v2-0`)
- admin 명시 override 가능
- 형식: `[a-z0-9]([a-z0-9-]*[a-z0-9])?`, ≤ 45자 (`{kind}-pool-custom-` 18자 프리픽스 + slug ≤ 63자 K8s label 한도)
- `(kind, slug)` UNIQUE — 같은 slug 두 Deployment 공존 불가. 다른 version → 다른 slug → 동시 운영 가능

#### K8sPoolManager (`backend.k8s_client`)

backend가 `kubernetes-asyncio` 클라이언트로 `runtime` 네임스페이스 안에서 4종 리소스를 관리:

| 리소스 | 역할 |
|---|---|
| `Deployment` | 이미지 워크로드. `replicas=1` 시작, KEDA가 auto-scale |
| `Service` | ClusterIP. `{kind}-pool-custom-{slug}:8080` — ext-authz가 DNS로 접근 |
| `ScaledObject` | KEDA. `minReplicaCount=1`, `maxReplicaCount=replicas_max`. Prometheus 트리거 |
| `PodDisruptionBudget` | `minAvailable=1` — 롤링 업데이트 중 가용성 보장 |

모든 pod에 `runtime/role: pool` 라벨 부착 → NetworkPolicy가 일반화된 selector로 처리.

**RBAC**: backend SA(`backend-admin`)에 `runtime` 네임스페이스 한정으로 위 4종에 대한 `create/update/delete/get/list/patch` 권한(`backend-k8s-rbac.yaml`).

#### Reconciler (`backend.reconciler`)

60초 간격 백그라운드 태스크:

- `status='pending'` 행이 5분 초과 → K8s 4종 강제 삭제 + `status='failed'` 마킹 (앱 크래시 복구)
- `status='active'` 행 ↔ Deployment 존재 검사: 누락/잉여 로그 경고 (자동 복구는 admin 액션 요구)
- `status='retired'` 후 K8s 리소스 잔존 시 강제 정리

#### Scale 정책

`minReplicas=1` 등록 기본값 — idle 비용 절감을 위해 baseline을 가볍게 유지. scale-to-zero 미지원 (ext-authz 라우팅 단순화의 전제 조건). prod-grade 가용성이 필요한 image는 admin이 `PATCH /api/admin/custom-images/{kind}/{slug}`로 `replicas_max ≥ 2`까지 상향.

### Bundle 저장소

admin backend가 **bundle 파일의 물리적 저장**도 책임진다. deploy-api는 `bundle_uri`만 읽고 파일을 소유하지 않는다.

- **MVP**: 로컬 디스크(`BUNDLE_STORAGE_DIR=/var/lib/admin/bundles`). k8s에서는 PVC(ReadOnlyMany로 pool에도 마운트) 또는 admin backend가 read-only HTTP `GET /bundles/{sha256}.zip` 제공.
- **S3/MinIO**: `BUNDLE_STORAGE_BACKEND=s3` 설정 시 admin backend가 업로드를 받아 S3에 stream 저장. `bundle_uri`는 **항상 HTTP URL** (`{BUNDLE_PUBLIC_BASE_URL}/{sha256}.zip`) 형태로 저장 — pool pod의 `BundleLoader`가 `http/https` scheme만 지원하므로 `s3://` URI를 직접 저장하지 않는다. pool pod이 해당 URL을 GET하면 backend가 presigned URL을 생성해 **307 redirect** → pool pod이 S3에서 직접 다운로드. S3 자격증명은 **admin backend 전용**, deploy-api·agent-base·mcp-base에는 불필요.
- **번들 다운로드 흐름 (S3 모드)**:
  ```
  pool pod → GET {BUNDLE_PUBLIC_BASE_URL}/{sha256}.zip
           → backend: aioboto3 presigned URL 생성 → 307 redirect
           → pool pod: S3에서 직접 다운로드 (presigned URL, 별도 인증 불필요)
  ```
- **S3 클라이언트 호환성 — checksum trailer opt-out**: aioboto3/boto3 1.36부터 `PutObject`/`UploadPart`에 `Content-Encoding: aws-chunked` + `x-amz-trailer: x-amz-checksum-crc32` 트레일러를 기본 삽입한다. NCP Object Storage(IBM Cleversafe 백엔드)는 이 트레일러를 인가되지 않은 페이로드로 보고 **403 AccessDenied**를 반환한다 — 자격증명·ACL이 모두 정상이고 List/Head/Delete는 통과해도 PutObject만 핀포인트로 실패하는 게 진단 시그니처. `S3BundleStorage._client_kwargs`에서 `botocore.config.Config(request_checksum_calculation="when_required", response_checksum_validation="when_required")`로 트레일러를 끈다. 같은 패턴이 일부 MinIO·GCS interop·Backblaze 환경에서도 보고되므로 default로 유지하고, 트레일러 체크섬을 명시적으로 원하는 백엔드가 등장하면 그때 재고.
- **업로드 플로우 (zip 전용 `POST /api/source-meta/bundle`)**:
  1. 프런트엔드: `<input type=file>` → `FormData`로 POST (multipart). 파트는 `file`(zip), 선택적으로 `sig`(서명 blob), `meta`(JSON: `{kind,name,version,runtime_pool,entrypoint,config?}`).
  2. backend: Starlette streaming으로 tmp 파일에 기록 + sha256 누적. 같은 방식으로 sig 받음.
  3. 크기 상한: `MAX_BUNDLE_SIZE_MB` (기본 200). Content-Length 헤더 + 실시간 누적 둘 다 체크(헤더 위조 방어) → 초과 시 413.
  4. **ZIP 무결성 검증**: `zipfile.ZipFile(tmp).testzip()` — 손상된 zip은 tmp 삭제 후 400.
  5. **Atomic commit**: 로컬은 `os.replace(tmp, {sha256}.zip)`, S3는 `put_object` 후 tmp 삭제. 같은 sha256 동시 업로드가 있어도 최종 파일은 항상 완전체. sig도 동일 규칙.
  6. `source_meta` INSERT (`bundle_uri` = `{BUNDLE_PUBLIC_BASE_URL}/{sha256}.zip`, `sig_uri` = `{BUNDLE_PUBLIC_BASE_URL}/{sha256}.sig` or null). 로컬/S3 백엔드 모두 동일 형태.
  7. 같은 `(kind,name,version)` 중복 409. 같은 sha256 재업로드는 파일 재사용(덮어써도 내용 동일).
- **서명만 추가/교체 (`POST /api/source-meta/{id}/signature`)**: zip은 그대로 두고 sig만 업로드. multipart `sig` 파트 → atomic write → `sig_uri` 갱신. 기존 파일은 덮어씀(서명 rotate).
- **URI 모드 (`POST /api/source-meta` with `bundle_uri`)**:
  - `http(s)://` → backend가 **서버에서 직접 fetch → sha256 계산 → 내부 저장소에 복사** 후 `bundle_uri`는 내부 경로로 덮어씀. 외부 URI는 출처 추적용으로만 `source_meta.source_uri`(별 컬럼 — 현재 없음, 도입 시 마이그레이션) 또는 감사 로그에 기록.
  - `s3://` / `oci://` → backend가 자격증명으로 pre-sign/fetch 가능하면 위와 동일. 불가하면 sha256을 body에 `checksum` 필드로 **강제 요구**(없으면 400).
  - `file://` → 개발용. backend가 로컬 경로 존재 + sha256 계산.
  - 어느 경우든 최종 `source_meta.checksum`은 **필수 non-null** — warm-registry affinity가 checksum 키 기반이라 null이면 런타임이 고장.
- **Retire vs Delete**: retire는 행 플래그만. delete(하드)는 bundle 파일도 함께 정리 — 다른 `source_meta` 행이 같은 checksum을 참조 중이면 파일 유지. 참조 검사는 `ix_source_meta_checksum` 인덱스 필요(아래 "인덱스").
- **인덱스**: `CREATE INDEX ix_source_meta_checksum ON source_meta (checksum)` — 하드 delete 시 참조 카운트 쿼리용. `backend/migrations/0001_init.sql`에 포함.

### 사용자 / 권한 관리

**테이블 소유권 재배치** (auth DESIGN.md의 기존 "auth read+write 전용"에서 전환):

| 테이블 | write 소유자 | read 소유자 | 비고 |
|---|---|---|---|
| `users` | admin backend | auth (`/login`에서 `password_hash` 검증, `is_admin` JWT claim 주입) | 비밀번호 해싱은 admin이 수행 |
| `user_resource_access` | admin backend | auth (`/verify` 시 `Principal.access` 구성) | admin UI는 양방향(user별/resource별) 조회 |
| `refresh_tokens` | auth | auth | 런타임 세션 상태 — admin 범위 밖 |

**스키마 보강** (마이그레이션 필요):
- `users.is_admin BOOLEAN NOT NULL DEFAULT false` 컬럼 추가.
- `user_resource_access`에 `created_by`, `note` 선택 컬럼(감사용) — 후행.

**비밀번호 플로우**:
- 생성/변경: admin backend가 `argon2-cffi` 사용(auth와 동일 파라미터 — 같은 `password_hash`를 auth가 검증해야 하므로 alg·params 일치 필수). 초기엔 admin에서 직접 import, 중복되면 `runtime_common.passwords`로 승격.
- 비밀번호 정책: 최소 길이 12, 공통 비밀번호 블랙리스트(MVP는 상위 N개 리스트만, 후행으로 zxcvbn 등 복잡도 체크). 정책 위반은 400.
- 응답에 `password_hash`는 절대 싣지 않음. DTO 레벨에서 제외.

**token revoke 브릿지 호출 규칙** — 다음 전이에서 admin backend는 `POST {AUTH_URL}/admin/revoke-tokens?user_id=` (auth 신설 경로)를 반드시 호출해 해당 user의 refresh 전부 revoke한다. JWT access TTL만큼 기존 세션이 살아있는 허점을 차단:

| 이벤트 | revoke 대상 | 근거 |
|---|---|---|
| `POST /api/users/{id}/password` (관리자 강제) | 그 user의 모든 refresh | 새 비번 적용 후 이전 세션 무효 |
| `POST /api/me/password` (본인) | 본인의 모든 refresh | 위와 동일 |
| `PATCH /api/users/{id}` with `disabled=true` | 그 user의 모든 refresh | 계정 정지 즉시 반영 |
| `PATCH /api/users/{id}` with `is_admin=false` | 그 user의 모든 refresh | admin 권한 회수 즉시 반영(기존 JWT의 is_admin claim 무효화 필요) |
| `DELETE /api/users/{id}` | 그 user의 모든 refresh | FK cascade로 `refresh_tokens` 자동 삭제지만, in-flight JWT의 즉시 401화를 위해 추가로 revoke-tokens 호출(auth 캐시 무효화) |
| `DELETE /api/users/{id}/access` | revoke 안 함 | `Principal.access`는 `/verify`가 매번 fresh DB 조회이므로 다음 요청에 즉시 반영 — 세션 끊을 필요 없음 |

실패 시 backend는 해당 admin 액션을 500으로 롤백(또는 재시도 큐). 핵심 보안 작업이 "성공했는지 모호"한 상태는 피한다.

**권한(access) 관리 모델**:
- 행 단위: `(user_id, kind, name)`. kind ∈ {`agent`,`mcp`}, name은 `source_meta.name`과 같은 어휘. 버전별 ACL은 없음(auth DESIGN.md와 동일).
- 부여: source-meta의 `name`이 실제 존재하는지 존재검사 후 INSERT(FK 없는 느슨한 참조이지만 admin 쓰기 경로에서 정합성 책임).
- 회수: 단일 행 DELETE. 캐스케이드 필요 없음.
- 대량 부여: `POST /api/users/{id}/access:bulk` 로 `[{kind,name}]` 배열(MVP엔 넣지 않음, 필요해지면 추가).

**자기 잠금(self-lockout) 방지**:
- 자기 자신의 `is_admin=false` 로 업데이트 금지(400).
- 자기 자신의 `disabled=true` 로 업데이트 금지.
- 자기 자신 DELETE 금지.
- 시스템에 `is_admin=true`인 active user가 1명이면 그 사용자의 `is_admin` 토글/disabled/삭제 금지(마지막 admin 보호).

**Bootstrap (첫 admin 생성)**:
- admin backend 기동 시 `users`가 비어있을 때만 발동. `INITIAL_ADMIN_USERNAME` + `INITIAL_ADMIN_PASSWORD`를 argon2 해시 후 INSERT. 이후 가동에는 no-op.
- **credential 주입은 Secret Volume 파일로** — `INITIAL_ADMIN_PASSWORD_FILE=/etc/backend/initial-admin-password`를 읽는다. env로 직접 받지 않음(`kubectl describe pod` / env dump / crash log 경유 노출 차단).
- 첫 로그인 후 **비밀번호 변경 강제** 플래그: `users.must_change_password BOOLEAN NOT NULL DEFAULT FALSE` 컬럼 추가(마이그레이션). seed 계정은 TRUE. `POST /api/auth/login` 응답 또는 `GET /api/me`에 플래그 노출 → 프런트엔드가 로그인 직후 `/me` 비번 변경 화면으로 강제 이동. 변경 완료 시 FALSE로 업데이트.
- k8s Secret: `backend-bootstrap` (dev overlay에서만 패치, prod는 외부 Secret Manager 또는 수동 주입). Secret 삭제 후 rollout하면 이미 users 테이블이 비어있지 않으므로 안전.

### Validation (서버측 강제)

프런트엔드의 힌트와 **별개로** 백엔드가 반드시 재검증한다. 클라이언트 체크는 UX용일 뿐 보안 경계가 아님.

| 필드 | 규칙 | 실패 시 |
|---|---|---|
| `kind` | ∈ `{"agent", "mcp"}` | 400 |
| `runtime_pool` | Bundle 모드: ∈ `{"agent:compiled_graph", "agent:adk", "mcp:fastmcp", "mcp:mcp_sdk", "mcp:didim_rag", "mcp:t2sql"}` + `kind` prefix 일치. Image 모드: `parse_runtime_pool()` 통과 + slug 규칙 준수 | 400 |
| `name` | `^[a-z0-9][a-z0-9-]{0,127}$` | 400 |
| `version` | `^[a-zA-Z0-9._-]{1,64}$` | 400 |
| `entrypoint` | `^[\w.]+:[\w]+$` | 400 |
| `bundle_uri` (URI 모드) | scheme ∈ `{http,https,s3,oci,file}` | 400 |
| `checksum` | `^sha256:[0-9a-f]{64}$` (있으면) | 400 |
| `config`, `user_meta.config` | `dict`, 직렬화 ≤ `MAX_CONFIG_BYTES` (기본 64KB). Image 모드는 merge 결과 ≤ 16 KB (ext-authz 헤더 budget) | 400 / 413 |
| `secrets_ref` | `^(vault|env|aws-sm)://.+$` | 400 |
| `username` | `^[a-zA-Z0-9_.-]{3,128}$` + case-insensitive unique | 400 / 409 |
| `password` | 길이 ≥ `PASSWORD_MIN_LENGTH` + 공통 블랙리스트(상위 N) miss | 400 |
| `principal_id` | `^[\w.:@-]{1,128}$` | 400 |
| `user_resource_access.(kind, name)` | `source_meta.name` 존재검사 → 없으면 404 | 404 |

enum 목록은 `runtime_common.schemas.AgentRuntimeKind` / `McpRuntimeKind`를 유일 출처로. 하드코드 금지.

### PATCH 화이트리스트 (명시적 거절 규정)

불변 필드가 body에 섞여 들어와도 조용히 무시하지 않고 **400으로 거절**한다 — 의도치 않은 상태 변경 감지가 목적.

- `PATCH /api/source-meta/{id}` 허용: `{entrypoint?, sig_uri?, runtime_pool?, config?}`. 거절: `name`, `version`, `kind`, `checksum`, `bundle_uri`, `retired`, `created_at` (+ 알 수 없는 키).
- `PATCH /api/users/{id}` 허용: `{tenant?, disabled?, is_admin?}`. 거절: `password`, `password_hash`, `username`, `id`, `created_at`, `updated_at` (+ 알 수 없는 키). 비밀번호는 전용 엔드포인트(`POST /api/users/{id}/password` 또는 `POST /api/me/password`)로만.
- `PUT /api/user-meta` 허용: `{source_meta_id, principal_id, config?, secrets_ref?}`. 거절: `id`, `updated_at`.

### Chat invoke (Envoy 스트리밍 프록시)

`POST /api/chat/invoke` — 프런트엔드 `/chat`이 이 한 경로로 agent를 호출. Envoy(`ENVOY_URL`) → ext-authz(auth+routing) → agent-pool로 연결되고, pool 응답을 단순 패스스루하지 않고 **클라이언트가 그대로 렌더할 수 있는 단일 SSE 포맷으로 정규화**한다. agent-base의 emit 포맷이 runtime_kind별로 다르고(LangGraph `astream_events` v2 / ADK Event / CUSTOM) 그걸 프런트가 알 필요 없게 BFF에서 추상화하는 게 목적.

**Request body (`ChatInvokeRequest`)**:
- `agent: str` (필수), `version: str | None`, `input: dict` (예: `{"message": "..."}`), `session_id: str | None`, `stream: bool = True`.
- `principal`은 **본문에 싣지 않는다** — gateway가 forwarded JWT로 자체 Principal을 만들어 pool에 전달. BFF가 임의 principal을 주입할 수 있게 두는 것은 신뢰경계상 부적절.

**인증 포워딩**: cookie의 `access_token` JWT(또는 `request.state.new_access_token`이 set돼 있으면 refresh된 새 토큰)를 `Authorization: Bearer …` + `x-runtime-name: <agent>` 헤더로 Envoy에 전달. ext-authz가 Bearer 강제이므로 빠뜨리면 401.

**응답 포맷** — `text/event-stream` 단일 채널, 세 종류의 이벤트만 노출:

| 이벤트 | 의미 | 종료 |
|---|---|---|
| `data: {"text": "<token delta>"}\n\n` | 어시스턴트 텍스트 델타. 프런트는 누적 append. | no |
| `data: {"error": "<detail>"}\n\n` | 인밴드 에러. 항상 종료 직전 1회. | yes |
| `data: [DONE]\n\n` | 정상 종료 마커. | yes |

**SSE 정규화 규칙** (`_extract_text()`):
- LangGraph `compiled_graph`: `astream_events` v2 이벤트 중 `event=="on_chat_model_stream"`만 surface, `data.chunk.content` 추출 (string·LangChain content-block list 양쪽 처리).
- ADK: `Event.model_dump(mode="json")` 결과의 `content.parts[*].text` join.
- CUSTOM: `{chunk: ...}` (per-chunk)·`{output: ...}` (final). LangGraph state-style `output.messages[-1].content`도 처리.
- 알 수 없는 이벤트는 silent skip — 노이즈가 프런트로 흘러가지 않게.

**에러 통합 규약**: 
- 게이트웨이 4xx/5xx 응답 → `data: {"error": "HTTP <code>: <detail>"}` 후 종료.
- agent-base 인밴드 `data: {"error": "..."}` (`run_stream`이 예외 시 emit) → 그대로 패스 후 종료.
- `httpx.RequestError`(연결 실패 등) → `data: {"error": "Failed to reach Envoy: ..."}`.
- 200 헤더 송출 후 발생한 에러도 client에 도달 — `StreamingResponse`가 시작된 뒤 `HTTPException`을 raise하면 상태코드 변경 불가라서 인밴드 프레임 규약이 필수.

**`stream=False`**: 직접 사용 케이스가 없으므로(UI는 항상 `True` 송신) 운영에서 비권장. 본문 필드는 forward-compat 목적으로만 노출.

### Pagination / 공통 응답 규약

모든 list 엔드포인트(`GET /api/source-meta`, `GET /api/users`, `GET /api/users/{id}/access`, `GET /api/source-meta/{id}/access`)에 동일 규약 적용:

- 쿼리: `?limit=<1..100, default 50>&offset=<>=0, default 0>`. `limit>100`은 서버가 100으로 clamp(400 아님).
- 응답: `{"items": [...], "total": N, "limit": L, "offset": O}`. `total`은 같은 filter의 전체 카운트(cursor가 아니라 offset 기반이라 cheap).
- 정렬: list 별 기본값 고정 (source-meta: `created_at DESC`; users: `username ASC`). 오버라이드는 MVP에선 지원 X.

### 설정 (env)

| 변수 | 기본값 | 용도 |
|---|---|---|
| `POSTGRES_DSN` | — | write primary (asyncpg URL). `runtime_common.db.make_engine` |
| `POSTGRES_PGBOUNCER` | `false` | pgbouncer 경유 시 true |
| `AUTH_URL` | — | auth 서비스 |
| `ADMIN_USERNAMES` | — | 쉼표 구분 allowlist. `users.is_admin` 마이그레이션 전 부트스트랩용 폴백. 정상화 후 제거. |
| `INITIAL_ADMIN_USERNAME` | — | 첫 설치 seed 계정 (한 번 생성 후 env 제거 권장) |
| `INITIAL_ADMIN_PASSWORD` | — | 동일. 강력한 임시 비번 사용 + 로그인 직후 변경 강제 |
| `PASSWORD_MIN_LENGTH` | `12` | 생성/변경 시 최소 길이 |
| `CORS_ORIGINS` | `http://localhost:5173` | 프런트엔드 origin |
| `SESSION_COOKIE_SECURE` | `true` | dev에서만 `false` |
| `CSRF_COOKIE_NAME` | `csrf_token` | |
| `BUNDLE_STORAGE_BACKEND` | `local` | `local` \| `s3` |
| `BUNDLE_STORAGE_DIR` | `/var/lib/admin/bundles` | 로컬 저장 경로 (`local` 모드) |
| `BUNDLE_PUBLIC_BASE_URL` | — | pool이 bundle을 fetch할 HTTP base URL (예: `http://backend.runtime.svc/bundles`). 로컬·S3 공통 사용 — `bundle_uri`에 저장되는 값의 prefix |
| `MAX_BUNDLE_SIZE_MB` | `200` | |
| `S3_BUCKET` | — | S3 버킷명 (`s3` 모드) |
| `S3_ENDPOINT_URL` | — | MinIO 등 호환 엔드포인트 (예: `https://kr.object.ncloudstorage.com`). 비워두면 AWS 기본값 |
| `S3_REGION` | `us-east-1` | S3 리전 |
| `S3_PREFIX` | `bundles/` | 버킷 내 object key prefix |
| `S3_ACCESS_KEY_ID` | — | 명시 자격증명. 비워두면 IAM Role / 인스턴스 프로파일 사용 |
| `S3_SECRET_ACCESS_KEY` | — | 위와 쌍 |
| `S3_PRESIGN_EXPIRY_SEC` | `3600` | presigned URL 유효시간(초) |
| `ENVOY_URL` | `http://envoy.runtime.svc.cluster.local:8080` | Envoy 데이터플레인 URL (chat invoke용) |
| `K8S_IN_CLUSTER` | `true` | `true`면 ServiceAccount 토큰으로 K8s API 접근. `false`면 `~/.kube/config` (로컬 개발용) |
| `RUNTIME_NAMESPACE` | `runtime` | image 모드 pool을 배포할 K8s 네임스페이스 |
| `CLUSTER_DOMAIN` | `cluster.local` | K8s 클러스터 DNS 도메인 |
| `DEPLOY_API_URL` | `http://deploy-api.runtime.svc.cluster.local:8080` | image 모드 pod가 사용할 deploy-api URL (K8s Deployment env로 주입) |
| `ALLOW_HARD_DELETE` | `false` | prod는 false, dev는 true |
| `BACKEND_SERVE_SPA` | `true` | true면 `dist/`를 `/`에 mount (prod). dev(`uv run uvicorn ...`)는 `false` 권장 — Vite 5173을 씀 |
| `LOG_LEVEL` | `INFO` | |


