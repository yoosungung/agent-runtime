from __future__ import annotations

from backend.pipeline_helpers import pipeline_blob_settings
from backend.settings import Settings


def test_pipeline_blob_settings_maps_runtime_s3_creds(monkeypatch):
    monkeypatch.delenv("PIPELINE_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("S3_SECRET_KEY", raising=False)
    from path_graph.config import get_settings

    get_settings.cache_clear()

    backend = Settings(
        POSTGRES_DSN="postgresql+asyncpg://x/x",
        S3_ENDPOINT_URL="http://garage:3900",
        S3_BUCKET="runtime-bundles",
        S3_REGION="garage",
        S3_ACCESS_KEY_ID="access-id",
        S3_SECRET_ACCESS_KEY="secret-key",
    )
    pg = pipeline_blob_settings(backend, "postgresql://x/x")

    assert pg.pipeline_storage_backend == "s3"
    assert pg.s3_endpoint_url == "http://garage:3900"
    assert pg.s3_bucket == "runtime-bundles"
    assert pg.s3_access_key == "access-id"
    assert pg.s3_secret_key == "secret-key"
    assert pg.s3_region == "garage"

    get_settings.cache_clear()
