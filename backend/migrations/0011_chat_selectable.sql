-- Chat picker visibility for agents (all deploy modes).
ALTER TABLE source_meta
    ADD COLUMN IF NOT EXISTS chat_selectable BOOLEAN NOT NULL DEFAULT true;

CREATE INDEX IF NOT EXISTS ix_source_meta_chat_selectable
    ON source_meta (kind, chat_selectable)
    WHERE kind = 'agent';
