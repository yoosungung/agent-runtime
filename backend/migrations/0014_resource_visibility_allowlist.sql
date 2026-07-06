-- Extend source_meta.visibility with allowlist; backfill bundle/image ACL resources.

ALTER TABLE source_meta DROP CONSTRAINT IF EXISTS chk_source_meta_visibility;
ALTER TABLE source_meta
    ADD CONSTRAINT chk_source_meta_visibility
    CHECK (visibility IN ('private', 'tenant', 'public', 'allowlist'));

UPDATE source_meta sm
SET visibility = 'allowlist'
WHERE sm.retired = FALSE
  AND EXISTS (
      SELECT 1
      FROM user_resource_access ura
      WHERE ura.kind = sm.kind
        AND ura.name = sm.name
  );
