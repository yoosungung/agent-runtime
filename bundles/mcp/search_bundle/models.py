"""Shared data models for search_bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

NaverCategory = Literal["web", "blog", "news"]
NaverSort = Literal["sim", "date"]


@dataclass
class SearchItem:
    title: str
    link: str
    description: str | None = None
    pub_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"title": self.title, "link": self.link}
        if self.description:
            data["description"] = self.description
        if self.pub_date:
            data["pub_date"] = self.pub_date
        return data


@dataclass
class SearchResult:
    query: str
    category: NaverCategory
    total: int
    items: list[SearchItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "category": self.category,
            "total": self.total,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class SearchSettings:
    max_display: int = 10
    default_category: NaverCategory = "web"

    @classmethod
    def from_cfg(cls, cfg: dict) -> SearchSettings:
        section = cfg.get("search") or {}
        return cls(
            max_display=int(section.get("max_display", 10)),
            default_category=str(section.get("default_category", "web")),  # type: ignore[arg-type]
        )


@dataclass
class FetchSettings:
    max_bytes: int = 8192
    timeout_seconds: float = 10.0
    user_agent: str = "agents-runtime-search-bundle/1.0"
    allow_private_network: bool = False
    max_redirects: int = 5

    @classmethod
    def from_cfg(cls, cfg: dict) -> FetchSettings:
        section = cfg.get("fetch") or {}
        return cls(
            max_bytes=int(section.get("max_bytes", 8192)),
            timeout_seconds=float(section.get("timeout_seconds", 10.0)),
            user_agent=str(section.get("user_agent", "agents-runtime-search-bundle/1.0")),
            allow_private_network=bool(section.get("allow_private_network", False)),
            max_redirects=int(section.get("max_redirects", 5)),
        )


@dataclass
class NaverCredentials:
    client_id: str
    client_secret: str

    @classmethod
    def from_cfg(cls, cfg: dict, secrets) -> NaverCredentials | None:
        section = cfg.get("naver") or {}
        client_id = section.get("client_id")
        client_secret = section.get("client_secret")
        secret_ref = section.get("client_secret_ref")
        if secret_ref and not client_secret:
            client_secret = secrets.resolve(str(secret_ref))
        if not (client_id and client_secret):
            return None
        return cls(client_id=str(client_id), client_secret=str(client_secret))
