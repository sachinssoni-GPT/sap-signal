"""Reader-facing text clean-up, applied when an edition is rendered (the stored drafts keep their raw form,
so the evidence gates still see every [C#] marker).

- human dates: 2027-02-15 -> 15 Feb 2027 (never inside URLs or edition ids in paths)
- citation markers: [C3], [C3, C4] and [PUB1] are internal; readers see superscript links in the editorial
  and nothing in the short story briefs
"""
from __future__ import annotations

import re
from datetime import date

_ISO = re.compile(r"(?<![\w/.-])(\d{4})-(\d{2})-(\d{2})(?![\w/-])")
MARKERS = re.compile(r"\s*\[((?:C|PUB)\d+(?:\s*[,;\-–]\s*(?:C|PUB)?\d+)*)\]")


def human_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso[:10]).strftime("%-d %b %Y")
    except (ValueError, TypeError):
        return iso


def human_dates(text: str) -> str:
    def sub(m):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%-d %b %Y")
        except ValueError:
            return m.group(0)
    return _ISO.sub(sub, text or "")


def strip_markers(text: str) -> str:
    """Remove every internal citation marker (briefs, titles, social)."""
    return re.sub(r"\s+([.,;:])", r"\1", MARKERS.sub("", text or "")).strip()


def _ids(group: str) -> list[str]:
    """'C3, C4' / 'C3; 4' / 'C1-C4' (range) -> ['C3', 'C4'] / ... / ['C1', 'C2', 'C3', 'C4']."""
    ids, prefix = [], "C"
    for part in re.split(r"\s*[,;]\s*", group):
        m = re.match(r"(C|PUB)?(\d+)(?:\s*[-–]\s*(?:C|PUB)?(\d+))?$", part)
        if m:
            prefix = m.group(1) or prefix
            lo = int(m.group(2)); hi = int(m.group(3)) if m.group(3) else lo
            ids += [f"{prefix}{n}" for n in (range(lo, hi + 1) if 0 <= hi - lo < 50 else (lo, hi))]
    return ids


def footnotes(text: str) -> str:
    """[C3, C4] -> superscript links to the matching entries in the editorial's Sources list."""
    def sub(m):
        links = ",".join(f'<a href="#src-{i.lower()}">{i[1:] if i.startswith("C") else i}</a>' for i in _ids(m.group(1)))
        return f"<sup>{links}</sup>"
    return MARKERS.sub(sub, text or "")


def reader(text: str) -> str:
    from .typography import normalize
    return normalize(human_dates(strip_markers(text)))


def tidy_newsletter(md: str) -> str:
    """Apply today's reader rules to an already-rendered newsletter.md (issues published before v3.22)."""
    m = re.match(r"\A(---\n.*?\n---\n)(.*)\Z", md, flags=re.S)
    front, body = (m.group(1), m.group(2)) if m else ("", md)
    cut = body.find('<h2 id="the-editorial">')
    top, ed = (body, "") if cut < 0 else (body[:cut], body[cut:])
    top = "\n".join(human_dates(strip_markers(ln)) if ln.strip() else ln for ln in top.split("\n"))
    src_at = ed.find("### Sources")
    main_part, sources = (ed, "") if src_at < 0 else (ed[:src_at], ed[src_at:])
    sources = re.sub(r"\*\*\[(C(\d+))\]\*\*", lambda x: f'<span id="src-{x.group(1).lower()}"></span>**[{x.group(2)}]**',
                     sources)
    main_part = footnotes(human_dates(main_part))
    return front + top + main_part + sources
