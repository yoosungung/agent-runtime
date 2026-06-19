-- Migration 0004: replace is_admin boolean with role enum-like column

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS role VARCHAR(16);

UPDATE users
SET role = CASE WHEN is_admin THEN 'admin' ELSE 'user' END
WHERE role IS NULL;

ALTER TABLE users
    ALTER COLUMN role SET NOT NULL,
    ALTER COLUMN role SET DEFAULT 'user';

ALTER TABLE users
    ADD CONSTRAINT chk_users_role CHECK (role IN ('user', 'developer', 'admin'));

ALTER TABLE users DROP COLUMN IF EXISTS is_admin;
