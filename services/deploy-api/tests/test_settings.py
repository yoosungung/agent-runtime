"""Settings env wiring for deploy-api resolve cache tuning."""

from deploy_api.settings import Settings


def test_resolve_cache_defaults_without_env(monkeypatch):
    for key in ("RESOLVE_CACHE_TTL_SEC", "RESOLVE_CACHE_MAX"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.resolve_cache_ttl_sec == 5.0
    assert settings.resolve_cache_max == 2048


def test_resolve_cache_from_env(monkeypatch):
    monkeypatch.setenv("RESOLVE_CACHE_TTL_SEC", "15")
    monkeypatch.setenv("RESOLVE_CACHE_MAX", "8192")
    settings = Settings()
    assert settings.resolve_cache_ttl_sec == 15.0
    assert settings.resolve_cache_max == 8192
