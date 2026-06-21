"""Settings env wiring for auth cache tuning."""

from auth.settings import Settings


def test_access_cache_defaults_without_env(monkeypatch):
    for key in ("ACCESS_CACHE_TTL_SEC", "ACCESS_CACHE_MAX_SIZE"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.access_cache_ttl_sec == 5.0
    assert settings.access_cache_max_size == 1024


def test_access_cache_from_env(monkeypatch):
    monkeypatch.setenv("ACCESS_CACHE_TTL_SEC", "30")
    monkeypatch.setenv("ACCESS_CACHE_MAX_SIZE", "4096")
    settings = Settings()
    assert settings.access_cache_ttl_sec == 30.0
    assert settings.access_cache_max_size == 4096
