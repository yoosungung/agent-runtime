-- users.tenant NOT NULL (single-tenant deployment; path-graph Admin Console contract).
-- Requires: users (0001_init.sql)

UPDATE users
SET tenant = 'dev'
WHERE tenant IS NULL OR btrim(tenant) = '';

ALTER TABLE users
    ALTER COLUMN tenant SET NOT NULL;
