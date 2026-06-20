"""HTTP URL fetch provider with SSRF protections."""

from __future__ import annotations

from urllib.parse import urljoin

import httpx
from models import FetchSettings
from utils import html_to_text, validate_fetch_url


class UrlFetcher:
    def __init__(self, *, settings: FetchSettings) -> None:
        self._settings = settings

    async def fetch(
        self,
        *,
        url: str,
        timeout_seconds: float | None = None,
        extract_text: bool = False,
    ) -> str:
        validate_fetch_url(url, allow_private_network=self._settings.allow_private_network)
        timeout = timeout_seconds if timeout_seconds is not None else self._settings.timeout_seconds
        headers = {"User-Agent": self._settings.user_agent}

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers=headers,
        ) as client:
            current_url = url
            for _ in range(self._settings.max_redirects + 1):
                validate_fetch_url(
                    current_url,
                    allow_private_network=self._settings.allow_private_network,
                )
                resp = await client.get(current_url)
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        resp.raise_for_status()
                    current_url = urljoin(current_url, location)
                    continue
                resp.raise_for_status()
                text = resp.text[: self._settings.max_bytes]
                content_type = resp.headers.get("content-type", "")
                if extract_text and "text/html" in content_type.lower():
                    return html_to_text(text)[: self._settings.max_bytes]
                return text

        raise ValueError("too many redirects")
