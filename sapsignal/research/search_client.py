"""Search + RSS discovery.

The search provider is an open decision (see the design doc). Everything downstream talks to the
SearchClient protocol, so swapping Tavily for Exa/Brave/Serper means adding one class here and
changing `search.provider` in config.yaml. Run the ~20-query bake-off before committing.
"""
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

import feedparser
import requests

from ..config import get_config
from .source_registry import canonical_url, excluded_domains, is_aggregator, is_excluded


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""
    published: Optional[str] = None
    source: str = ""


class SearchClient(Protocol):
    def search(self, query: str, max_results: int = 8, days: Optional[int] = None,
               include_domains: Optional[list[str]] = None) -> list[SearchHit]: ...


class SearchUnavailable(RuntimeError):
    """The search provider refuses all requests (credits used up / bad key). Not worth continuing the run."""


class TavilyClient:
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str):
        self.key = api_key
        self.cache: dict = {}          # identical query in one run = one paid request
        self.credits_used = 0
        self.blocked: str = ""         # once the plan limit is hit, fail fast without network calls

    def search(self, query: str, max_results: int = 8, days: Optional[int] = None,
               include_domains: Optional[list[str]] = None) -> list[SearchHit]:
        body = {"query": query, "max_results": max_results,
                "exclude_domains": ["news.google.com", "msn.com", "news.yahoo.com", "flipboard.com"]
                                   + excluded_domains()}
        if include_domains:
            body["include_domains"] = include_domains
        if days:
            body.update({"topic": "news", "days": days})
        if self.blocked:
            raise SearchUnavailable(self.blocked)
        key = (query.strip().lower(), max_results, days, tuple(include_domains or ()))
        if key in self.cache:
            return list(self.cache[key])
        r = requests.post(self.URL, json=body, headers={"Authorization": f"Bearer {self.key}"}, timeout=30)
        if r.status_code in (432, 433):
            self.blocked = ("Tavily search credits are used up (HTTP 432 'plan limit exceeded'). Top up or "
                            "upgrade at https://app.tavily.com, then rerun.")
            raise SearchUnavailable(self.blocked)
        if r.status_code == 401:
            self.blocked = "Tavily rejected the API key (HTTP 401). Check the TAVILY_API_KEY secret."
            raise SearchUnavailable(self.blocked)
        r.raise_for_status()
        self.credits_used += 1
        hits = [
            SearchHit(title=x.get("title", ""), url=x["url"], snippet=x.get("content", "")[:300],
                      published=x.get("published_date"), source="tavily")
            for x in r.json().get("results", [])
            if not is_excluded(x.get("url", ""))
        ]
        self.cache[key] = hits
        return list(hits)


_client: Optional[SearchClient] = None


def reset_search_client() -> None:
    """New run, new cache and credit counter."""
    global _client
    _client = None


class GoogleNewsClient:
    """Free news search via Google News RSS (no key, no credits). News-only, many outlets per story:
    ideal for corroboration and for finding a readable copy of a paywalled article. Wrapper links are
    decoded to the publisher URL; excluded/aggregator publishers are dropped before decoding."""
    URL = "https://news.google.com/rss/search"

    def __init__(self, locale: tuple[str, str, str] = ("en-US", "US", "US:en")):
        self.hl, self.gl, self.ceid = locale
        self.cache: dict = {}
        self.credits_used = 0          # free provider: always 0
        self.blocked: str = ""

    def search(self, query: str, max_results: int = 8, days: Optional[int] = None,
               include_domains: Optional[list[str]] = None) -> list[SearchHit]:
        from .url_resolver import decode_google_news
        q = query.strip()
        if include_domains:
            q += " (" + " OR ".join(f"site:{d}" for d in include_domains[:10]) + ")"
        if days:
            q += f" when:{max(1, int(days))}d"
        key = (q.lower(), max_results)
        if key in self.cache:
            return list(self.cache[key])
        r = requests.get(self.URL, params={"q": q, "hl": self.hl, "gl": self.gl, "ceid": self.ceid},
                         headers={"User-Agent": _FEED_UA}, timeout=20)
        if r.status_code in (429, 503):
            self.blocked = f"Google News search is rate-limiting (HTTP {r.status_code})"
            raise SearchUnavailable(self.blocked)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        picked = []
        for e in feed.entries:
            src = e.get("source") if isinstance(e.get("source"), dict) else {}
            publisher = (src or {}).get("href", "")
            if publisher and (is_excluded(publisher) or is_aggregator(publisher)):
                continue
            picked.append(e)
            if len(picked) >= max_results:
                break
        decoded = decode_google_news([e.get("link", "") for e in picked])
        hits = []
        for e in picked:
            url = decoded.get(e.get("link", ""))
            if not url or is_excluded(url):
                continue
            title = re.sub(r"\s+-\s+[^-]{2,60}$", "", e.get("title", "")).strip()
            snippet = re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")
            ts = e.get("published_parsed")
            hits.append(SearchHit(title=title, url=url, snippet=" ".join(snippet.split())[:300],
                                  published=datetime(*ts[:6], tzinfo=timezone.utc).isoformat() if ts else None,
                                  source="google_news"))
        self.cache[key] = hits
        return list(hits)


class ChainSearchClient:
    """Try providers in order: the free one first, the paid one only when the free one fails or finds
    nothing. Raises SearchUnavailable only if every provider is unavailable."""

    def __init__(self, providers: list):
        self.providers = providers

    @property
    def credits_used(self) -> int:
        return sum(getattr(p, "credits_used", 0) for p in self.providers)

    @property
    def blocked(self) -> str:
        msgs = [p.blocked for p in self.providers if getattr(p, "blocked", "")]
        return "; ".join(msgs) if len(msgs) == len(self.providers) else ""

    def search(self, query: str, max_results: int = 8, days: Optional[int] = None,
               include_domains: Optional[list[str]] = None) -> list[SearchHit]:
        last: Exception | None = None
        unavailable = 0
        for p in self.providers:
            try:
                hits = p.search(query, max_results=max_results, days=days, include_domains=include_domains)
                if hits:
                    return hits
            except SearchUnavailable as exc:
                unavailable += 1
                last = exc
            except Exception as exc:
                last = exc
        if unavailable == len(self.providers):
            raise SearchUnavailable(str(last))
        return []


def get_search_client() -> SearchClient:
    """config `search.provider`: "googlenews+tavily" (default: free first, paid fallback), "googlenews",
    or "tavily"."""
    global _client
    if _client is None:
        provider = (get_config().get("search", {}) or {}).get("provider", "googlenews+tavily")
        if provider == "tavily+googlenews":
            provider = "googlenews+tavily"
        chain = []
        for name in provider.split("+"):
            if name == "googlenews":
                chain.append(GoogleNewsClient())
            elif name == "tavily":
                key = os.environ.get("TAVILY_API_KEY")
                if key:
                    chain.append(TavilyClient(key))
                elif provider == "tavily":
                    raise RuntimeError("TAVILY_API_KEY is not set (see .env.example)")
            else:
                raise ValueError(f"Unknown search provider: {name}")
        _client = chain[0] if len(chain) == 1 else ChainSearchClient(chain)
    return _client


_FEED_UA = "Mozilla/5.0 (compatible; DTI-feed-reader/0.3; +https://github.com)"


def _load_feed(url: str):
    r = requests.get(url, timeout=20, headers={"User-Agent": _FEED_UA,
                                               "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    r.raise_for_status()
    return feedparser.parse(r.content)


def discover_rss(feeds: list[str], lookback_hours: int, diagnostics: list[str] | None = None) -> list[SearchHit]:
    """Read publisher RSS feeds. A broken feed is logged and skipped, never fatal."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    hits: list[SearchHit] = []
    for url in feeds:
        try:
            feed = _load_feed(url)
        except Exception as exc:
            if diagnostics is not None:
                diagnostics.append(f"feed failed: {url} ({type(exc).__name__})")
            continue
        for e in feed.entries[:40]:
            # Google News items name the real publisher in <source url=...>; honour the source policy early.
            publisher = (e.get("source") or {}).get("href", "") if isinstance(e.get("source"), dict) else ""
            if is_excluded(e.get("link", "")) or (publisher and is_excluded(publisher)):
                continue
            ts = e.get("published_parsed") or e.get("updated_parsed")
            when = datetime(*ts[:6], tzinfo=timezone.utc) if ts else None
            if when and when < cutoff:
                continue
            hits.append(SearchHit(title=e.get("title", ""), url=e.get("link", ""),
                                  snippet=(e.get("summary", "") or "")[:500],
                                  published=when.isoformat() if when else None,
                                  source=feed.feed.get("title", "rss")))
    return hits


def check_feeds(feeds: list[str]) -> list[tuple[str, str, int]]:
    """For `main.py check-sources`: (feed, status, entries)."""
    out = []
    for url in feeds:
        try:
            feed = _load_feed(url)
            out.append((url, "ok" if feed.entries else "empty", len(feed.entries)))
        except Exception as exc:
            out.append((url, f"error: {type(exc).__name__}: {str(exc)[:80]}", 0))
    return out


def dedupe_hits(hits: list[SearchHit], skip_urls: set[str] | None = None) -> list[SearchHit]:
    seen: set[str] = set(skip_urls or ())
    seen_titles: set[str] = set()
    out: list[SearchHit] = []
    for h in hits:
        if not h.url:
            continue
        if is_excluded(h.url):
            continue
        cu = canonical_url(h.url)
        tkey = " ".join(h.title.lower().split())[:80]
        if cu in seen or (tkey and tkey in seen_titles):
            continue
        seen.add(cu)
        seen_titles.add(tkey)
        out.append(h)
    return out
