-- Bind API keys to users; reuse user_resource_access on /verify.
ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
