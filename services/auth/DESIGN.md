# auth

런타임의 인증 서비스. **JWT 발급(로그온)과 검증**을 모두 담당한다. 사용자/클라이언트는 `/login`으로 토큰을 발급받고, 두 게이트웨이는 `/verify`로 토큰을 검증한다.

권한 모델은 **scope 기반이 아님**. 이 저장소는 런타임이므로 권한 등록/정책 엔진을 두지 않는다. 대신 "어떤 사용자가 어떤 agent/mcp를 쓸 수 있는가"를 **매핑 테이블(`user_resource_access`)** 로 표현한다.

Postgres는 아키텍처 상 **auth / deploy-api에만 연결**된다. 따라서 게이트웨이는 이 테이블을 직접 읽지 않고, **`/verify` 응답에 사용자의 허용 리소스 목록(`access`)이 함께 실려 내려온다**. 게이트웨이는 그 리스트만으로 invoke 인가 판단을 끝낸다.

## 설계

### Endpoints
- `POST /login` — `{username, password}` → `{access_token, token_type, expires_in}`.
  - `users` 테이블에서 조회 → `password_hash` 검증(argon2id) → JWT 서명 발급.
  - 발급 claim: `sub`(username), `user_id`, `tenant`, `iss`, `iat`, `exp`.
  - 비활성(`disabled=true`) 사용자 / 불일치 / 미존재 모두 **401** (username enumeration 방지로 메시지 동일).
- `POST /verify` — `{token, grace_sec?: int = 0}` → `Principal{sub, user_id, tenant?, access, grace_applied: bool}`.
  - 토큰 서명/issuer/필수 claim은 **항상 엄격** 검증. `exp`만 `now <= exp + effective_grace` 로 완화.
  - `effective_grace = min(grace_sec, GRACE_MAX_SEC)` — caller가 큰 값을 요청해도 서버가 clamp. 기본 `GRACE_MAX_SEC=600`.
  - `grace_applied` 는 `now > exp and now <= exp + effective_grace` 일 때 `true`. 감사·관측용.
  - 이후 `user_id`로 `user_resource_access`를 **매번 fresh** 조회해 허용 리소스 목록을 `access`에 실어 반환. grace 구간에도 권한 회수는 즉시 반영.
  - `access`: `list[{kind, name}]` (예: `[{"kind":"agent","name":"chat-bot"}, {"kind":"mcp","name":"rag"}]`). 게이트웨이는 이 리스트만으로 invoke 인가 판정.
  - Postgres 왕복은 발생하나, 게이트웨이가 매 invoke마다 별도 authorize 호출을 하지 않아도 되도록 한 호출로 번들. auth 내부에 짧은 TTL 캐시(`user_id → access`)를 두어 반복 비용 완화(TODO).
  - **감사 로그**: grace_applied=true 요청은 `token.jti/sub, exp, now, delta, caller_hint` 를 구조화 로그로 남긴다.
- `POST /logout` — JWT는 무상태이므로 현재는 noop. 즉시 revoke 필요해지면 blocklist(예: Redis) 도입 고려(TODO).

### 서명 키
- 발급(서명): `JWT_PRIVATE_KEY` (PEM) — **신규**.
- 검증: `JWT_PUBLIC_KEY` (PEM) — 기존.
- 알고리즘: RS256/ES256. Issuer: `JWT_ISSUER`.

### 만료 유예 (grace)
- `GRACE_MAX_SEC` (env, 기본 `600`): `/verify` 호출자가 요청하는 `grace_sec`의 서버측 절대 상한.
- `grace_sec`이 0 초과인 호출을 **허용할지**는 auth가 판정하지 않는다 — caller(gateway)가 내부 경로 식별 후에만 0 초과 값을 보내야 한다. auth는 어차피 `GRACE_MAX_SEC`로 clamp하므로 악의적 caller의 최대 악영향은 상한까지.
- 엣지 gateway는 `grace_sec` 생략(=0). 전체 정책은 `/DESIGN.md`의 "내부 호출의 토큰 Grace Period" 참조.

### 테이블 (신규)
마이그레이션은 [`backend/migrations/0001_init.sql`](../../backend/migrations/0001_init.sql)에 통합(모든 테이블 단일 파일).

#### `users`
| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | `BIGSERIAL` | PK |
| `username` | `VARCHAR(128)` | UNIQUE NOT NULL |
| `password_hash` | `VARCHAR(256)` | NOT NULL — argon2id |
| `tenant` | `VARCHAR(64)` | NULL |
| `disabled` | `BOOLEAN` | NOT NULL DEFAULT `FALSE` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` |

인덱스/제약
- `UNIQUE (username)` — `uq_users_username`
- (추후) `INDEX (tenant)` — 테넌트 내 관리 쿼리 도입 시

#### `user_resource_access`
사용자 ↔ agent/mcp 리소스 매핑. 한 행이 존재하면 해당 사용자는 그 리소스의 **모든 버전**을 invoke 가능.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `user_id` | `BIGINT` | NOT NULL, FK `users(id) ON DELETE CASCADE` |
| `kind` | `VARCHAR(16)` | NOT NULL — `'agent'` \| `'mcp'` (`source_meta.kind`와 동일 어휘) |
| `name` | `VARCHAR(128)` | NOT NULL — `source_meta.name`과 동일 어휘 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `now()` |

제약/인덱스
- `PRIMARY KEY (user_id, kind, name)`
- `INDEX (kind, name)` — 리소스 기준 역조회 (예: "이 agent를 쓸 수 있는 사용자 목록")

설계 결정
- `source_meta`에 FK는 **걸지 않는다** — `source_meta`는 `(kind, name, version)` 단위로 다행이 존재하는 반면 매핑은 `(kind, name)`까지만 필요. 정합성은 admin 쓰기 경로의 책임.
- 버전별 접근 제어는 하지 않는다 — 런타임이 최신/지정 버전을 해석하는 것은 게이트웨이 몫이고, 인가는 "리소스 자체의 사용 가능 여부"까지만 다룸.
- 와일드카드 행(`name='*'`)은 도입하지 않는다 — 필요해지면 그때 추가.

### 인가 lookup 배치 (확정)

**`/verify` 응답에 `access` 번들**.

근거
- Postgres는 아키텍처상 auth·deploy-api에만 연결됨 → 게이트웨이가 `user_resource_access`를 직접 읽지 못함.
- deploy-api에 위임하면 auth 도메인 테이블이 다른 서비스로 새어 나가고 책임 경계가 흐려짐.
- 별도 `POST /authorize`로 쪼개면 게이트웨이가 매 invoke마다 auth를 두 번 호출(verify + authorize)하게 됨 — verify에 번들하는 편이 왕복이 적고 캐시 적중률도 좋음.

흐름
```
게이트웨이 invoke
  └─ AuthClient.verify(token) → Principal{sub, user_id, tenant?, access}
  └─ (kind, req.name) ∈ access ? → OK : 403
  └─ deploy-api resolve → runtime_pool → pool로 프록시
```


