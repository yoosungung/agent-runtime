-- Migration 0002: custom image mode support
--
-- source_meta 테이블에 image mode 컬럼 추가.
-- deploy_mode='bundle'이 기존 bundle 모드, 'image'가 신규 image 모드.
-- status 컬럼: 'pending' 행은 deploy-api /v1/resolve에서 제외.

-- runtime_pool 컬럼 확장: image mode는 '{kind}:custom:{slug}' 형식 사용
ALTER TABLE source_meta
    ALTER COLUMN runtime_pool TYPE VARCHAR(128);

-- entrypoint/bundle_uri: image mode에서 NULL 허용
ALTER TABLE source_meta
    ALTER COLUMN entrypoint DROP NOT NULL,
    ALTER COLUMN bundle_uri DROP NOT NULL;

-- image mode 전용 컬럼 추가
ALTER TABLE source_meta
    ADD COLUMN IF NOT EXISTS deploy_mode  VARCHAR(16)  NOT NULL DEFAULT 'bundle',
    ADD COLUMN IF NOT EXISTS image_uri    VARCHAR(512),
    ADD COLUMN IF NOT EXISTS image_digest VARCHAR(128),
    ADD COLUMN IF NOT EXISTS slug         VARCHAR(63),
    ADD COLUMN IF NOT EXISTS status       VARCHAR(16)  NOT NULL DEFAULT 'active';

-- 기존 행 backfill: 모두 bundle 모드, active 상태
UPDATE source_meta
SET deploy_mode = 'bundle',
    status      = 'active'
WHERE deploy_mode IS NULL OR deploy_mode = '';

-- CHECK constraints: mode별 필수 필드 강제
ALTER TABLE source_meta
    ADD CONSTRAINT chk_source_meta_bundle_fields
        CHECK (
            deploy_mode != 'bundle'
            OR (entrypoint IS NOT NULL AND bundle_uri IS NOT NULL)
        ),
    ADD CONSTRAINT chk_source_meta_image_fields
        CHECK (
            deploy_mode != 'image'
            OR (image_uri IS NOT NULL AND slug IS NOT NULL)
        ),
    ADD CONSTRAINT chk_source_meta_deploy_mode
        CHECK (deploy_mode IN ('bundle', 'image')),
    ADD CONSTRAINT chk_source_meta_status
        CHECK (status IN ('pending', 'active', 'failed', 'retired'));

-- (kind, slug) UNIQUE: 같은 slug의 두 이미지 Deployment 공존 불가
CREATE UNIQUE INDEX IF NOT EXISTS uq_source_meta_kind_slug
    ON source_meta (kind, slug)
    WHERE slug IS NOT NULL;

-- slug 인덱스 (status 필터링용)
CREATE INDEX IF NOT EXISTS ix_source_meta_status ON source_meta (status);
