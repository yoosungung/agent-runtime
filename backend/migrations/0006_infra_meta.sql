-- Platform-wide infra env registry (admin-managed, reconciled to K8s pool pods).
CREATE TABLE IF NOT EXISTS infra_meta (
    id           BIGSERIAL PRIMARY KEY,
    scope        VARCHAR(16)  NOT NULL DEFAULT 'global',
    scope_key    VARCHAR(128) NOT NULL DEFAULT '',
    env          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    secret_keys  JSONB        NOT NULL DEFAULT '[]'::jsonb,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_infra_meta_scope UNIQUE (scope, scope_key)
);

INSERT INTO infra_meta (scope, scope_key)
VALUES ('global', '')
ON CONFLICT (scope, scope_key) DO NOTHING;
