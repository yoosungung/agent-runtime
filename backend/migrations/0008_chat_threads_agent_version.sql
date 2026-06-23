-- agents-runtime — pin agent version on chat threads
-- Requires: chat_threads (0006_chat_threads.sql), source_meta (0001_init.sql)

ALTER TABLE chat_threads
    ADD COLUMN IF NOT EXISTS agent_version VARCHAR(128);

UPDATE chat_threads AS ct
SET agent_version = COALESCE(
    (
        SELECT sm.version
        FROM source_meta AS sm
        WHERE sm.kind = 'agent'
          AND sm.name = ct.agent_name
          AND sm.retired = false
          AND sm.status != 'pending'
        ORDER BY sm.created_at DESC
        LIMIT 1
    ),
    (
        SELECT sm.version
        FROM source_meta AS sm
        WHERE sm.kind = 'agent'
          AND sm.name = ct.agent_name
        ORDER BY sm.created_at DESC
        LIMIT 1
    ),
    'unknown'
)
WHERE ct.agent_version IS NULL;

ALTER TABLE chat_threads
    ALTER COLUMN agent_version SET NOT NULL;
