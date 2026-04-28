# deploy-api

**런타임 메타 조회 서비스**. Agent/MCP 번들의 코드 정의(`source_meta`)와 사용자별 부가 메타데이터(`user_meta`)를 Postgres에서 조회해 런타임에 제공한다. 등록·수정·삭제는 이 서비스 범위 밖 — 추후 별도 admin 서비스가 담당한다.

이 서비스는 **런타임 크리티컬 경로**다 — 모든 invoke가 한 번 이상 통과한다.

## 설계

### 스키마

- `source_meta(id, kind, name, version, runtime_pool, entrypoint, bundle_uri, checksum, sig_uri, config JSONB, retired, created_at)`; unique(kind, name, version).
  - `kind` ∈ {`agent`, `mcp`}
  - `runtime_pool` = `{kind}:{runtime_kind}` (예: `agent:compiled_graph`, `mcp:fastmcp`)
  - `entrypoint` = `python.module.path:factory_attr`
  - `bundle_uri` = `https://...`, `file://...`, (향후) `oci://...`
  - `config` — **번들 기본 config** (버전 고정, immutable). user_meta.config와 **runtime에서 shallow merge**(user wins) 후 factory에 주입.
- `user_meta(id, source_meta_id FK, principal_id, config JSONB, secrets_ref, updated_at)`; unique(source_meta_id, principal_id).
  - `principal_id` — `Principal` 식별자 (또는 tenant_id)
  - `config` — per-user 실행 파라미터(tool allowlist, 모델 선택, tone 등). **source_meta.config의 덮어쓰기**.
  - `secrets_ref` — 실제 비밀값은 저장하지 않음. Vault/Secret Manager의 키만 보관
  - 코드 정의는 **immutable/versioned**, user_meta는 **mutable** — 수명이 다르므로 별 테이블로 분리
- **config 병합은 runtime(agent-base/mcp-base)이 수행** — deploy-api는 `source.config` / `user.config`를 **그대로** 내려보낸다. 병합·재구성 X. 이유는 (1) source는 checksum 단위로 cache, user는 updated_at 단위로 cache → 수명이 다르므로 분리 유지. (2) admin UI·감사 로그가 "어느 쪽 값이 이긴 건지" 추적 가능. (3) 정책 변경(deep merge, override 금지 키 등) 발생 시 runtime 층에서만 수정.

### 엔드포인트

| method | path | 용도 | 주 소비자 |
|---|---|---|---|
| **`GET /v1/resolve`** | **런타임 lookup**. `?kind=&name=&version=&principal=` → `{source, user}` 한 묶음 | **agent-base / mcp-base / gateway** |

`/v1/resolve` 응답:
```json
{
  "source": {
    "kind": "agent", "name": "ticket-triage", "version": "v3",
    "runtime_pool": "agent:compiled_graph",
    "entrypoint": "app:build_graph",
    "bundle_uri": "s3://...", "checksum": "sha256:...",
    "config": {"model": "gpt-4o", "max_tools": 10, "tone": "neutral"}
  },
  "user": {
    "principal_id": "u_42",
    "config": {"max_tools": 5, "tone": "formal"},
    "secrets_ref": "vault://agents/u_42/ticket-triage"
  }
}
```
runtime은 두 config를 shallow merge → factory가 보는 값: `{"model": "gpt-4o", "max_tools": 5, "tone": "formal"}` (user가 덮어쓴 키는 `max_tools`, `tone`; source-only 키 `model`은 유지).
- `version` 생략 시 최신 버전.
- 해당 principal의 `user_meta`가 없으면 `user: null`.
- 캐시 친화적으로 `ETag` + `Cache-Control: max-age=<small>` 지정. 클라이언트(특히 pool)는 조건부 요청 + 로컬 LRU로 부하 감소.
- **ETag 계산식**: `W/"{source.checksum}|{user.updated_at_epoch or 0}"` (약한 ETag). `source`는 `(kind,name,version)` 단위 immutable이므로 checksum 단독으로 충분하지만, `user`가 mutable이라 `updated_at`을 합쳐야 user 변경 시 무효화된다. principal이 달라지면 키가 달라 자연 분리.
- `If-None-Match` 일치 시 `304 Not Modified` 바디 없음.

### 동작 원칙

- **Postgres에 붙는 유일한 서비스**. gateway·agent-base·mcp-base는 DB DSN을 모르며 이 API만 쓴다.
- 무상태. 수평 확장 가능. 런타임 경로이므로 replica ≥ 2 권장.

### DB 연결 구조 (PgBouncer + Read Replica)

```
deploy-api (write)  →  pgbouncer-rw  →  Postgres primary
deploy-api (read)   →  pgbouncer-ro  →  read replica (dev: primary와 동일)
```

- **쓰기 경로**: `POST /v1/source-meta`, `PUT /v1/user-meta` 등 — `POSTGRES_DSN` (→ pgbouncer-rw)
- **읽기 경로**: `GET /v1/resolve`, `GET /v1/source-meta`, `GET /v1/user-meta` — `POSTGRES_READ_DSN` (→ pgbouncer-ro). 설정 없으면 쓰기 DSN으로 폴백.
- **PgBouncer transaction mode**: asyncpg prepared statement 캐시 비활성화 필수 → `POSTGRES_PGBOUNCER=true` 설정 시 `statement_cache_size=0` 자동 적용.
- **마이그레이션**: psql은 `+asyncpg` scheme 미지원 → `POSTGRES_DIRECT_DSN`(libpq URL, postgres 직접 연결) 사용.
- **프로덕션 전환**: pgbouncer-ro Deployment의 `POSTGRESQL_HOST`를 kustomize overlay로 실제 read replica 엔드포인트로 오버라이드.

#### 환경변수 요약 (postgres-credentials Secret)

| 변수 | 용도 |
|---|---|
| `POSTGRES_DSN` | 앱 쓰기 경로 (asyncpg URL, pgbouncer-rw 경유) |
| `POSTGRES_READ_DSN` | 앱 읽기 경로 (asyncpg URL, pgbouncer-ro 경유) |
| `POSTGRES_PGBOUNCER` | `true` 설정 시 pgbouncer 호환 엔진 옵션 활성화 |
| `POSTGRES_PASSWORD` | pgbouncer가 postgres 인증에 사용 |
| `POSTGRES_DIRECT_DSN` | 마이그레이션 Job 전용 (libpq URL, postgres 직접 연결) |

