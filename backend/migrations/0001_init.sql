-- agents-runtime — initial schema
--
-- 단일 Postgres에 쓰는 모든 테이블을 한 번에 생성. 쓰기 소유자는 admin backend.
-- runtime 서비스(deploy-api / auth)는 각자 read-only 영역만 가짐 — 자세한 위임은
-- /DESIGN.md "Postgres 스키마 (참고)".
--
-- 순서: 참조 없는 테이블 → FK 있는 테이블.

-- ---------------------------------------------------------------------------
-- auth 도메인
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id                   BIGSERIAL PRIMARY KEY,
    username             VARCHAR(128) NOT NULL,
    password_hash        VARCHAR(256) NOT NULL,      -- argon2id
    tenant               VARCHAR(64),
    disabled             BOOLEAN      NOT NULL DEFAULT FALSE,
    is_admin             BOOLEAN      NOT NULL DEFAULT FALSE,
    must_change_password BOOLEAN      NOT NULL DEFAULT FALSE,  -- bootstrap admin = TRUE
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_username UNIQUE (username)
);

CREATE TABLE IF NOT EXISTS user_resource_access (
    user_id    BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       VARCHAR(16)  NOT NULL,                -- 'agent' | 'mcp'
    name       VARCHAR(128) NOT NULL,                -- source_meta.name과 동일 어휘 (FK 없음)
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, kind, name)
);
CREATE INDEX IF NOT EXISTS ix_ura_kind_name ON user_resource_access (kind, name);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(128) NOT NULL UNIQUE,        -- sha256(plaintext)
    expires_at  TIMESTAMPTZ  NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);

CREATE TABLE IF NOT EXISTS api_keys (
    id         SERIAL       PRIMARY KEY,
    key_hash   VARCHAR(128) UNIQUE NOT NULL,         -- argon2id(plaintext) — 컬럼명은 legacy
    name       VARCHAR(128) NOT NULL,
    tenant     VARCHAR(64),
    disabled   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- 번들 메타 도메인
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source_meta (
    id           BIGSERIAL PRIMARY KEY,
    kind         VARCHAR(16)  NOT NULL,              -- 'agent' | 'mcp'
    name         VARCHAR(128) NOT NULL,
    version      VARCHAR(64)  NOT NULL,
    runtime_pool VARCHAR(64)  NOT NULL,              -- '{kind}:{runtime_kind}'
    entrypoint   VARCHAR(256) NOT NULL,              -- 'module.path:factory_attr'
    bundle_uri   VARCHAR(512) NOT NULL,              -- https:// | file:// | s3:// | oci://
    checksum     VARCHAR(128),                       -- sha256:...
    sig_uri      VARCHAR(512),                       -- 서명 파일 URI (선택)
    config       JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- 번들 기본 config (user_meta.config와 runtime merge)
    retired      BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_source_meta_nv UNIQUE (kind, name, version)
);
CREATE INDEX IF NOT EXISTS ix_source_meta_name ON source_meta (name);
CREATE INDEX IF NOT EXISTS ix_source_meta_kind_name_created ON source_meta (kind, name, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_source_meta_checksum ON source_meta (checksum);  -- hard delete 참조 카운트

CREATE TABLE IF NOT EXISTS user_meta (
    id             BIGSERIAL PRIMARY KEY,
    source_meta_id BIGINT       NOT NULL REFERENCES source_meta(id) ON DELETE CASCADE,
    principal_id   VARCHAR(128) NOT NULL,
    config         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    secrets_ref    VARCHAR(512),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_meta_source_principal UNIQUE (source_meta_id, principal_id)
);
CREATE INDEX IF NOT EXISTS ix_user_meta_principal ON user_meta (principal_id);

-- ---------------------------------------------------------------------------
-- audit_log table (added after initial schema)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    action     VARCHAR(128) NOT NULL,
    actor_id   BIGINT       NOT NULL,
    actor      VARCHAR(128) NOT NULL,
    details    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_log_actor_id  ON audit_log (actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_action    ON audit_log (action);
CREATE INDEX IF NOT EXISTS ix_audit_log_created   ON audit_log (created_at DESC);
