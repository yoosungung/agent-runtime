"""Provider factory for search_bundle."""

from __future__ import annotations

from models import FetchSettings, NaverCredentials, SearchSettings

from providers.fetch import UrlFetcher
from providers.naver import NaverProvider
from runtime_common.secrets import SecretResolver


def get_naver_provider(cfg: dict, secrets: SecretResolver) -> NaverProvider:
    creds = NaverCredentials.from_cfg(cfg, secrets)
    settings = SearchSettings.from_cfg(cfg)
    return NaverProvider(credentials=creds, settings=settings)


def get_url_fetcher(cfg: dict) -> UrlFetcher:
    return UrlFetcher(settings=FetchSettings.from_cfg(cfg))
