"""Search provider protocol for search_bundle."""

from __future__ import annotations

from typing import Protocol

from models import NaverCategory, NaverSort, SearchResult


class NaverSearchProvider(Protocol):
    async def search(
        self,
        *,
        query: str,
        display: int,
        start: int = 1,
        category: NaverCategory = "web",
        sort: NaverSort = "sim",
    ) -> SearchResult: ...
