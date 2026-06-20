"""Naver OpenAPI search provider."""

from __future__ import annotations

import httpx
from models import (
    NaverCategory,
    NaverCredentials,
    NaverSort,
    SearchItem,
    SearchResult,
    SearchSettings,
)
from utils import strip_naver_tags

_NAVER_ENDPOINTS: dict[NaverCategory, str] = {
    "web": "https://openapi.naver.com/v1/search/webkr.json",
    "blog": "https://openapi.naver.com/v1/search/blog.json",
    "news": "https://openapi.naver.com/v1/search/news.json",
}


class NaverProvider:
    def __init__(
        self,
        *,
        credentials: NaverCredentials | None,
        settings: SearchSettings,
    ) -> None:
        self._credentials = credentials
        self._settings = settings

    @property
    def max_display(self) -> int:
        return max(1, min(100, self._settings.max_display))

    async def search(
        self,
        *,
        query: str,
        display: int,
        start: int = 1,
        category: NaverCategory = "web",
        sort: NaverSort = "sim",
    ) -> SearchResult:
        if not self._credentials:
            raise RuntimeError(
                "naver credentials missing: set source_meta.config.naver.{client_id,client_secret}"
            )

        display = max(1, min(self.max_display, display))
        start = max(1, min(1000, start))
        endpoint = _NAVER_ENDPOINTS[category]
        headers = {
            "X-Naver-Client-Id": self._credentials.client_id,
            "X-Naver-Client-Secret": self._credentials.client_secret,
        }
        params: dict[str, str | int] = {"query": query, "display": display, "start": start}
        if category in ("blog", "news"):
            params["sort"] = sort

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(endpoint, headers=headers, params=params)
            resp.raise_for_status()
            body = resp.json()

        items = [_normalize_item(item, category) for item in body.get("items", [])]
        return SearchResult(
            query=query,
            category=category,
            total=int(body.get("total", 0)),
            items=items,
        )


def _normalize_item(raw: dict, category: NaverCategory) -> SearchItem:
    title = strip_naver_tags(str(raw.get("title", "")))
    link = str(raw.get("link", ""))
    description: str | None = None
    pub_date: str | None = None

    if category == "web":
        desc = raw.get("description")
        if desc:
            description = strip_naver_tags(str(desc))
    elif category == "blog":
        blogger = raw.get("bloggername")
        desc = raw.get("description")
        if blogger or desc:
            parts = [strip_naver_tags(str(p)) for p in (blogger, desc) if p]
            description = " — ".join(parts) if parts else None
        postdate = raw.get("postdate")
        if postdate:
            pub_date = str(postdate)
    elif category == "news":
        desc = raw.get("description")
        if desc:
            description = strip_naver_tags(str(desc))
        pub = raw.get("pubDate")
        if pub:
            pub_date = str(pub)

    return SearchItem(title=title, link=link, description=description, pub_date=pub_date)
