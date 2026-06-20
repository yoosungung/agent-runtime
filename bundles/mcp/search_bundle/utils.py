"""Shared helpers for search_bundle."""

from __future__ import annotations

import html.parser
import ipaddress
import socket
from urllib.parse import urlparse


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_naver_tags(text: str) -> str:
    """Naver wraps query matches in <b>...</b> — strip for readability."""
    return text.replace("<b>", "").replace("</b>", "")


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def _check_host_ip(host: str, *, allow_private_network: bool) -> None:
    if allow_private_network:
        return
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"could not resolve host: {host!r}") from exc
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if _is_blocked_ip(ip):
            raise ValueError(f"blocked address: {ip_str}")


def validate_fetch_url(url: str, *, allow_private_network: bool = False) -> str:
    """Validate URL for fetch_url; raises ValueError on SSRF-risk targets."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("only http and https URLs are allowed")
    host = parsed.hostname
    if not host:
        raise ValueError("URL must include a host")
    host_lower = host.lower()
    if host_lower in ("localhost", "metadata.google.internal"):
        raise ValueError(f"blocked host: {host}")
    if host_lower.endswith(".localhost"):
        raise ValueError(f"blocked host: {host}")

    try:
        literal = ipaddress.ip_address(host)
        if _is_blocked_ip(literal) and not allow_private_network:
            raise ValueError(f"blocked address: {host}")
        return url
    except ValueError as exc:
        if "blocked" in str(exc):
            raise

    _check_host_ip(host, allow_private_network=allow_private_network)
    return url
