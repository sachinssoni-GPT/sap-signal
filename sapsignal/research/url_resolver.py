"""Resolve aggregator links (mainly Google News RSS wrappers) to the original publisher URL.

This was the root cause of the recurring `no_story` runs: Google News RSS links are
`news.google.com/rss/articles/...` wrappers that no longer HTTP-redirect. Fetching them returns a
JavaScript shell (0 characters of article text, tier=aggregator), so every candidate failed
authentication and the verifier had nothing to quote.

Resolution order:
  1. Already a publisher URL -> unchanged.
  2. Google News wrapper -> decode with `googlenewsdecoder` (one batch call).
  3. Still unresolved -> search the exact headline and take the best non-aggregator hit whose
     title matches closely.
  4. Give up -> keep the wrapper; the candidate will fail authentication with a clear diagnostic.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from .source_registry import host_of, is_aggregator, is_excluded

_GOOGLE_HOSTS = {"news.google.com"}


def _is_google_news(url: str) -> bool:
    return host_of(url) in _GOOGLE_HOSTS


def _clean_title(title: str) -> str:
    # Google News titles end with " - Publisher Name"
    title = re.sub(r"\s+[-|–—]\s+[^-|–—]{2,60}$", "", title or "").strip()
    return " ".join(title.lower().split())


def decode_google_news(urls: list[str]) -> dict[str, str]:
    """Return {wrapper_url: publisher_url} for the wrappers that could be decoded."""
    if not urls:
        return {}
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        return {}
    out: dict[str, str] = {}
    try:
        results = gnewsdecoder(list(urls), interval=None, timeout=15)
    except Exception:
        results = []
        for u in urls:   # batch failed: try one by one
            try:
                results.append(gnewsdecoder(u, timeout=15))
            except Exception:
                results.append({})
    if isinstance(results, dict):
        results = [results]
    for wrapper, res in zip(urls, results):
        ok = (res or {}).get("success", (res or {}).get("status"))
        decoded = (res or {}).get("decoded_url")
        if ok and decoded and not is_aggregator(decoded):   # excluded publishers are filtered by the caller
            out[wrapper] = decoded
    return out


def find_by_headline(title: str, search_client) -> Optional[str]:
    """Search the headline; accept a non-aggregator hit with a near-identical title."""
    if not search_client or not title:
        return None
    wanted = _clean_title(title)
    try:
        hits = search_client.search(f'"{wanted}"', max_results=5, days=3)
    except Exception:
        return None
    best, best_score = None, 0.0
    for h in hits:
        if is_aggregator(h.url) or is_excluded(h.url):
            continue
        score = SequenceMatcher(None, wanted, _clean_title(h.title)).ratio()
        if score > best_score:
            best, best_score = h.url, score
    return best if best_score >= 0.72 else None


def resolve_candidates(candidates, search_client=None) -> list[str]:
    """Rewrite candidate.url in place to the publisher URL where possible. Returns diagnostics.
    A candidate whose publisher is excluded by the source policy gets one chance to be re-sourced
    by headline search on allowed outlets; otherwise its url is left excluded and the caller drops it."""
    notes: list[str] = []
    wrappers = [c.url for c in candidates if _is_google_news(c.url)]
    decoded = decode_google_news(wrappers)
    for c in candidates:
        if not is_aggregator(c.url):
            continue
        original = c.url
        new = decoded.get(original) or find_by_headline(c.title, search_client)
        if new:
            c.url = new
            notes.append(f"{c.id}: resolved aggregator link -> {host_of(new)}")
        else:
            notes.append(f"{c.id}: could not resolve aggregator link {host_of(original)}")
    for c in candidates:
        if is_excluded(c.url):
            alt = find_by_headline(c.title, search_client)
            notes.append(f"{c.id}: publisher {host_of(c.url)} excluded by source policy; "
                         + (f"re-sourced to {host_of(alt)}" if alt else "dropped"))
            if alt:
                c.url = alt
    return notes
