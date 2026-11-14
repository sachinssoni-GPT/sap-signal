"""Safe page retrieval with redirect validation and bounded response size.

Fetched page content is untrusted data. This module does not execute page scripts.
"""
import ipaddress
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
import trafilatura

from ..config import get_config

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36 DTI-research/0.3")
_MAX_CHARS = 300_000
_MAX_BYTES = 5 * 1024 * 1024
_MAX_REDIRECTS = 5
_REDIRECT_CODES = {301, 302, 303, 307, 308}


@dataclass
class Page:
    url: str
    final_url: str = ""
    title: str = ""
    text: str = ""
    published: Optional[str] = None
    retrieved_at: str = ""
    ok: bool = False
    error: str = ""
    via: str = "direct"      # "direct" or "tavily_extract"


_cache: dict[str, Page] = {}


def clear_page_cache() -> None:
    """Clear the per-process cache (useful in tests and long-running workers)."""
    _cache.clear()


def _is_public_http_url(url: str) -> bool:
    """Reject non-HTTP URLs, credentials, private/reserved IPs and non-public DNS results."""
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return False
        host = parsed.hostname.rstrip(".").lower()
        # IP literals must be globally routable.
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = []
            for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM):
                addresses.append(ipaddress.ip_address(info[4][0]))
        if not addresses:
            return False
        return all(address.is_global for address in addresses)
    except (ValueError, OSError, socket.gaierror):
        return False
    except Exception:
        return False


def _read_limited(response: requests.Response) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > _MAX_BYTES:
                raise ValueError(f"response exceeds {_MAX_BYTES} byte limit")
        except ValueError as exc:
            if "limit" in str(exc):
                raise
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > _MAX_BYTES:
            raise ValueError(f"response exceeds {_MAX_BYTES} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_page(url: str) -> Page:
    """Fetch a page directly; if that fails (paywall/bot wall/JS page), fall back to Tavily Extract.

    The fallback still returns the publisher's own text for the publisher's own URL, so the
    verbatim-quote check stays meaningful. Aggregator wrapper URLs are never "rescued" this way:
    resolve them to the publisher first (see url_resolver.py).
    """
    if url in _cache:
        return _cache[url]
    page = _fetch_direct(url)
    if not page.ok and _fallback_enabled():
        alt = _fetch_via_tavily(page.final_url or url)
        if alt is not None and alt.ok:
            alt.url = url
            alt.error = f"direct fetch failed ({page.error}); used tavily_extract"
            page = alt
    return _cache_page(url, page)


def _fallback_enabled() -> bool:
    cfg = get_config().get("fetch", {})
    return cfg.get("fallback", "tavily_extract") == "tavily_extract" and bool(os.environ.get("TAVILY_API_KEY"))


def _fetch_via_tavily(url: str) -> Optional[Page]:
    from .source_registry import is_aggregator
    if is_aggregator(url) or urlparse(url).scheme not in {"http", "https"}:
        return None
    try:
        r = requests.post("https://api.tavily.com/extract",
                          json={"urls": [url], "extract_depth": "basic"},
                          headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"}, timeout=45)
        r.raise_for_status()
        results = r.json().get("results") or []
    except Exception:
        return None
    if not results:
        return None
    text = (results[0].get("raw_content") or "").strip()
    return Page(url=url, final_url=results[0].get("url") or url, text=text[:_MAX_CHARS],
                title="", retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ok=len(text) >= 200, via="tavily_extract",
                error="" if len(text) >= 200 else "tavily_extract returned no usable text")


def _fetch_direct(url: str) -> Page:

    page = Page(url=url, retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    current_url = url
    timeout = get_config()["verification"].get("fetch_timeout_s", 20)
    try:
        with requests.Session() as session:
            session.headers.update({"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"})
            for redirect_count in range(_MAX_REDIRECTS + 1):
                # Validate EVERY hop, not only the initial URL.
                if not _is_public_http_url(current_url):
                    page.error = "blocked or invalid URL/redirect destination"
                    return page

                response = session.get(
                    current_url,
                    timeout=(5, timeout),
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    if response.status_code in _REDIRECT_CODES:
                        location = response.headers.get("Location")
                        if not location:
                            page.error = f"HTTP {response.status_code} redirect without Location"
                            return page
                        if redirect_count >= _MAX_REDIRECTS:
                            page.error = "too many redirects"
                            return page
                        current_url = urljoin(current_url, location)
                        continue

                    page.final_url = response.url or current_url
                    # Validate the final URL as an additional safeguard.
                    if not _is_public_http_url(page.final_url):
                        page.error = "blocked final URL"
                        return page
                    if response.status_code >= 400:
                        page.error = f"HTTP {response.status_code}"
                        return page

                    raw = _read_limited(response)
                    html = raw.decode(response.encoding or "utf-8", errors="replace")
                    extracted = trafilatura.extract(html, include_comments=False, favor_precision=True) or ""
                    metadata = trafilatura.extract_metadata(html)
                    page.text = extracted[:_MAX_CHARS]
                    page.title = (metadata.title if metadata and metadata.title else "") or ""
                    page.published = metadata.date if metadata and metadata.date else None
                    page.ok = bool(page.text)
                    if not page.ok:
                        page.error = "no extractable text"
                    return page
                finally:
                    response.close()
    except Exception as exc:  # network errors are diagnostics, not silent success
        page.error = f"{type(exc).__name__}: {exc}"

    return page


def _cache_page(original_url: str, page: Page) -> Page:
    _cache[original_url] = page
    return page
