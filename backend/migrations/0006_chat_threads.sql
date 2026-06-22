-- agents-runtime — chat thread registry (admin backend owned)
-- Requires: users (0001_init.sql)

CREATE TABLE IF NOT EXISTS chat_threads (
    id                    UUID         PRIMARY KEY,
    user_id               BIGINT       NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    agent_name            VARCHAR(128) NOT NULL,
    thread_type           VARCHAR(16)  NOT NULL,
    provider_session_id   VARCHAR(128) NOT NULL,
    provider_meta         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    title                 VARCHAR(256) NOT NULL DEFAULT 'New Chat',
    last_message_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at            TIMESTAMPTZ,
    purged_at             TIMESTAMPTZ,
    CONSTRAINT chk_chat_threads_type CHECK (thread_type IN ('langgraph', 'adk', 'custom'))
);

CREATE INDEX IF NOT EXISTS ix_chat_threads_user_list
    ON chat_threads (user_id, deleted_at, last_message_at DESC);

CREATE INDEX IF NOT EXISTS ix_chat_threads_user_agent
    ON chat_threads (user_id, agent_name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_threads_user_provider_session
    ON chat_threads (user_id, provider_session_id);
