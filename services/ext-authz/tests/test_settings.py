"""Settings env wiring for ext-authz client cache tuning."""

from ext_authz.settings import Settings


def test_client_cache_defaults_without_env(monkeypatch):
    for key in (
        "AUTH_CACHE_TTL_SEC",
        "AUTH_CACHE_MAX",
        "DEPLOY_CACHE_TTL_SEC",
        "DEPLOY_CACHE_MAX",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.auth_cache_ttl_sec == 5.0
    assert settings.auth_cache_max == 1024
    assert settings.deploy_cache_ttl_sec == 60.0
    assert settings.deploy_cache_max == 256


def test_client_cache_from_env(monkeypatch):
    monkeypatch.setenv("AUTH_CACHE_TTL_SEC", "10")
    monkeypatch.setenv("AUTH_CACHE_MAX", "2048")
    monkeypatch.setenv("DEPLOY_CACHE_TTL_SEC", "120")
    monkeypatch.setenv("DEPLOY_CACHE_MAX", "512")
    settings = Settings()
    assert settings.auth_cache_ttl_sec == 10.0
    assert settings.auth_cache_max == 2048
    assert settings.deploy_cache_ttl_sec == 120.0
    assert settings.deploy_cache_max == 512
