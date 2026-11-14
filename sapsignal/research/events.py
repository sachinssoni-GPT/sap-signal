"""Discovery: a wide, free net over the week, clustered into events.

  sections (config `sections:`) -> Google News search feeds + publisher RSS per section (free, no credits)
  + optional public Telegram channels (tips only: never evidence, never a source)
  -> every headline becomes a Hit with its publisher domain
  -> hits about the same event are clustered; an Event knows how many DISTINCT outlets carry it

Coverage breadth is the strongest cheap signal of significance there is: a story five outlets ran
independently matters more than one outlet's exclusive, and it gives the verifier several readable
copies to choose from when the first one is paywalled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from ..config import get_config
from .source_registry import classify, is_aggregator, is_excluded, registrable_domain

from ..schemas import BEATS

SECTIONS = BEATS
SECTION_LABELS = {"ecc_exit": "ECC exit & S/4HANA", "clean_core": "Clean Core & BTP",
                  "integration": "Integration & events", "data_ai": "Data & AI",
                  "commercials": "Licensing & commercials", "ecosystem": "Ecosystem"}

_LOCALES = {"IN": ("en-IN", "IN", "IN:en"), "US": ("en-US", "US", "US:en"), "GB": ("en-GB", "GB", "GB:en")}


@dataclass
class Hit:
    title: str
    url: str
    publisher: str = ""          # registrable domain of the real publisher (never news.google.com)
    snippet: str = ""
    published: str | None = None
    section_hint: str = ""
    via: str = ""                # "feed", "gnews", "telegram"


@dataclass
class Event:
    id: str
    title: str
    hits: list[Hit] = field(default_factory=list)
    section_hints: dict[str, int] = field(default_factory=dict)
    tips: int = 0                # Telegram tips pointing at this event

    @property
    def outlets(self) -> list[str]:
        seen: list[str] = []
        for h in self.hits:
            if h.publisher and h.via != "telegram" and h.publisher not in seen:
                seen.append(h.publisher)
        return seen

    @property
    def latest(self) -> str:
        return max((h.published or "" for h in self.hits), default="")

    def urls(self) -> list[str]:
        out = []
        for h in self.hits:
            if h.via != "telegram" and h.url not in out:
                out.append(h.url)
        return out


# ------------------------------------------------------------------ feeds
def gnews_url(query: str, region: str = "IN", days: int = 1) -> str:
    hl, gl, ceid = _LOCALES.get(region, _LOCALES["IN"])
    return (f"https://news.google.com/rss/search?q={quote_plus(query)}+when%3A{max(1, days)}d"
            f"&hl={hl}&gl={gl}&ceid={ceid}")


def section_sources(cfg: dict | None = None, days: int = 1) -> list[tuple[str, str]]:
    """[(feed_url, section)] for every section query and feed in config `sections:`."""
    cfg = cfg or get_config()
    out = []
    for name, sec in (cfg.get("sections") or {}).items():
        region = sec.get("region", "US")
        for q in sec.get("queries", []) or []:
            out.append((gnews_url(q, region, days), name))
        for f in sec.get("feeds", []) or []:
            out.append((f, name))
    return out


_FEED_UA = "Mozilla/5.0 (compatible; SAPSignal-reader/1.0)"


def _load(url: str):
    import feedparser
    import requests
    r = requests.get(url, timeout=20, headers={"User-Agent": _FEED_UA,
                                               "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    r.raise_for_status()
    return feedparser.parse(r.content)


def _strip_publisher(title: str) -> str:
    return re.sub(r"\s+[-|–—]\s+[^-|–—]{2,60}$", "", title or "").strip()


def read_feeds(sources: list[tuple[str, str]], lookback_hours: int, diagnostics: list[str] | None = None,
               per_feed: int = 40, loader=_load) -> list[Hit]:
    """Read every feed in parallel. A broken feed is logged and skipped. Google News items keep their
    wrapper URL (decoded later, only for stories we actually read) and name the publisher in <source>."""
    from concurrent.futures import ThreadPoolExecutor
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    def one(item):
        url, section = item
        try:
            return item, loader(url), None
        except Exception as exc:
            return item, None, exc

    hits: list[Hit] = []
    failed = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for (url, section), feed, exc in pool.map(one, sources):
            if feed is None:
                failed += 1
                if diagnostics is not None:
                    diagnostics.append(f"feed failed: {url[:90]} ({type(exc).__name__})")
                continue
            for e in feed.entries[:per_feed]:
                link = e.get("link", "")
                src = e.get("source") if isinstance(e.get("source"), dict) else {}
                publisher_url = (src or {}).get("href", "") or link
                if not link or is_excluded(link) or is_excluded(publisher_url) or \
                        (is_aggregator(publisher_url) and publisher_url != link):
                    continue
                ts = e.get("published_parsed") or e.get("updated_parsed")
                when = datetime(*ts[:6], tzinfo=timezone.utc) if ts else None
                if when and when < cutoff:
                    continue
                snippet = re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")
                hits.append(Hit(title=_strip_publisher(e.get("title", "")), url=link,
                                publisher=registrable_domain(publisher_url),
                                snippet=" ".join(snippet.split())[:300],
                                published=when.isoformat() if when else None, section_hint=section,
                                via="gnews" if "news.google.com" in link else "feed"))
    if diagnostics is not None:
        diagnostics.append(f"discovery: {len(sources) - failed}/{len(sources)} feeds read, {len(hits)} headlines")
    return hits


# ------------------------------------------------------------------ telegram tips
def read_telegram(channels: list[str], lookback_hours: int, diagnostics: list[str] | None = None,
                  fetch=None) -> list[Hit]:
    """Public channels via their web preview (t.me/s/<name>). Posts are TIPS: they can raise a story's
    priority and add search leads, but are never shown, quoted or cited."""
    import requests
    from html import unescape
    if not channels:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    hits: list[Hit] = []
    for name in channels:
        name = name.strip().lstrip("@").replace("https://t.me/", "").replace("s/", "", 1).strip("/")
        try:
            html = fetch(name) if fetch else requests.get(f"https://t.me/s/{name}", timeout=20,
                                                          headers={"User-Agent": _FEED_UA}).text
        except Exception as exc:
            if diagnostics is not None:
                diagnostics.append(f"telegram {name} failed ({type(exc).__name__})")
            continue
        n = 0
        for block in re.split(r'<div class="tgme_widget_message_wrap', html)[1:]:
            m = re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
            t = re.search(r'datetime="([^"]+)"', block)
            if not m:
                continue
            when = None
            if t:
                try:
                    when = datetime.fromisoformat(t.group(1).replace("Z", "+00:00"))
                except ValueError:
                    when = None
            if when and when < cutoff:
                continue
            text = " ".join(unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())
            if len(text) < 30:
                continue
            first = re.split(r"(?<=[.!?])\s|\n", text)[0][:200]
            hits.append(Hit(title=first, url=f"https://t.me/s/{name}", snippet=text[:300],
                            published=when.isoformat() if when else None, via="telegram"))
            n += 1
        if diagnostics is not None:
            diagnostics.append(f"telegram {name}: {n} recent posts")
    return hits


# ------------------------------------------------------------------ clustering
_STOP = {"with", "from", "that", "this", "after", "amid", "over", "into", "says", "said", "tells", "will",
         "have", "what", "when", "their", "about", "more", "than", "they", "were", "been", "could", "would",
         "sources", "report", "reports", "official", "officials", "news", "live", "updates", "latest",
         "today", "says", "amid", "first", "year", "years", "week", "new", "how", "why", "here",
         "the", "and", "for", "its", "has", "was", "are", "not", "but", "who", "out", "all", "may", "can",
         "get", "set", "top", "key", "big", "now", "via", "per", "say", "off", "one", "two", "his", "her",
         "sap", "saps", "erp", "enterprise", "software", "company", "customer", "business"}
_SAME = {"pct": "percent", "s4hana": "s4", "s4hana's": "s4", "hana": "hana", "btp": "btp", "raises": "raise",
         "hikes": "raise", "cuts": "cut", "migrations": "migration", "customers": "customer"}


def words(title: str) -> set[str]:
    """Key words of a headline. 3-letter tokens count (INS, RBI, GDP, IMF, EU's...), plurals fold."""
    out = set()
    for w in re.findall(r"[a-z0-9]+", (title or "").lower()):
        w = _SAME.get(w, w)
        if len(w) < 3 or w in _STOP or w.isdigit() and len(w) < 3:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def cluster(hits: list[Hit], threshold: float = 0.45, min_shared: int = 2) -> list[Event]:
    """Greedy single pass: a headline joins the event whose key words it shares most (>= threshold and
    at least `min_shared` words, so two-word headlines don't glue unrelated stories together)."""
    events: list[Event] = []
    keys: list[set[str]] = []
    for h in hits:
        w = words(h.title)
        if not w:
            continue
        best, best_i = 0.0, -1
        for i, k in enumerate(keys):
            s = overlap(w, k)
            if s > best and len(w & k) >= min_shared:
                best, best_i = s, i
        if best >= threshold:
            ev = events[best_i]
            ev.hits.append(h)
            keys[best_i] |= w if len(keys[best_i]) < 14 else set()
        else:
            ev = Event(id="", title=h.title, hits=[h])
            events.append(ev)
            keys.append(set(w))
        if h.via == "telegram":
            ev.tips += 1
        elif h.section_hint:
            ev.section_hints[h.section_hint] = ev.section_hints.get(h.section_hint, 0) + 1
    # Telegram-only clusters stay as tips; real events need at least one outlet.
    events = [e for e in events if e.outlets]
    for e in events:
        e.title = _best_title(e)
    events.sort(key=lambda e: (len(e.outlets) + 2 * e.tips, e.latest), reverse=True)
    for i, e in enumerate(events, start=1):
        e.id = f"E{i}"
    return events


def _best_title(e: Event) -> str:
    """Headline from the most authoritative outlet that carries the event."""
    from ..schemas import SourceTier
    rank = {SourceTier.PRIMARY: 0, SourceTier.TIER1_PRESS: 1, SourceTier.REGIONAL_PRESS: 2,
            SourceTier.TRADE_PRESS: 3, SourceTier.RESEARCH_INSTITUTION: 4}
    real = [h for h in e.hits if h.via != "telegram"]
    real.sort(key=lambda h: (rank.get(classify("https://" + h.publisher), 9), -len(h.title)))
    return real[0].title if real else e.title


def drop_already_covered(events: list[Event], recent_titles: list[str], threshold: float = 0.6) -> list[Event]:
    """Skip events we already ran in the last few issues (unless the story has clearly moved on: that
    shows up as a different headline)."""
    old = [words(t) for t in recent_titles if t]
    return [e for e in events if not any(overlap(words(e.title), o) >= threshold and len(words(e.title) & o) >= 3
                                         for o in old)]


def triage_rows(events: list[Event], limit: int = 180) -> str:
    """Compact one-line-per-event table for the triage model (no JSON truncation mid-item)."""
    rows = []
    for e in events[:limit]:
        hint = max(e.section_hints, key=e.section_hints.get) if e.section_hints else "?"
        outlets = ", ".join(e.outlets[:4]) + (f" +{len(e.outlets) - 4}" if len(e.outlets) > 4 else "")
        snippet = next((h.snippet for h in e.hits if h.snippet and h.via != "telegram"), "")[:160]
        tip = " | TIP" if e.tips else ""
        rows.append(f"{e.id} | {len(e.outlets)} outlets ({outlets}) | hint:{hint}{tip} | {e.title} | {snippet}")
    return "\n".join(rows)
