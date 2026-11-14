"""The Deadline Radar: a curated, dated list of SAP changes (deadlines.yaml), kept honest by code.

  load()      rows from deadlines.yaml
  upcoming()  rows still ahead of a date, soonest first
  verify()    proposals from the model -> only rows whose date is literally stated in a verified quote
  merge()     approved proposals -> deadlines.yaml (status: new), skipping duplicates

A model can suggest a row; it can't put a date on the Radar that no page it read actually says.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from . import config
from .config import get_config
from .schemas import DeadlineProposal, VerificationReport

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
_SHORT = [m[:3] for m in MONTHS]


def path() -> Path:
    return config.ROOT / (get_config().get("paths", {}) or {}).get("deadlines", "deadlines.yaml")


def load(p: Path | None = None) -> list[dict]:
    p = p or path()
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [r for r in (data.get("rows") or []) if isinstance(r, dict) and r.get("date") and r.get("item")]


def _as_date(value: str) -> date | None:
    """'2027-12-31' -> that day; '2027-12' -> the last day of that month (a month-precision deadline)."""
    value = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
        if re.fullmatch(r"\d{4}-\d{2}", value):
            y, m = int(value[:4]), int(value[5:])
            nxt = date(y + (m == 12), m % 12 + 1, 1)
            return date.fromordinal(nxt.toordinal() - 1)
    except ValueError:
        return None
    return None


def label(value: str) -> str:
    """'2027-12-31' -> '31 Dec 2027'; '2027-12' -> 'Dec 2027'."""
    value = str(value).strip()
    d = _as_date(value)
    if d is None:
        return value
    return d.strftime("%-d %b %Y") if len(value) == 10 else d.strftime("%b %Y")


def upcoming(rows: list[dict], today: date, limit: int | None = None) -> list[dict]:
    out = [r for r in rows if (d := _as_date(r["date"])) and d >= today and r.get("status") != "passed"]
    out.sort(key=lambda r: (_as_date(r["date"]), r.get("item", "")))
    return out[:limit] if limit else out


def days_until(value: str, today: date) -> int | None:
    d = _as_date(value)
    return (d - today).days if d else None


# ------------------------------------------------------------------ verification of proposals
def _date_stated(value: str, text: str) -> bool:
    """True when the quote literally states the proposed date: the year AND the month (by name, short
    name or number), and the day too when a full date is proposed."""
    d = _as_date(value)
    if d is None:
        return False
    t = text.lower()
    if str(d.year) not in t:
        return False
    month_ok = (re.search(rf"\b({MONTHS[d.month - 1]}|{_SHORT[d.month - 1]}\.?)\b", t) is not None
                or re.search(rf"\b{d.year}-{d.month:02d}\b|\b{d.month:02d}[/.]{d.year}\b", t) is not None)
    # "end of 2027" / "by end-2027" states 31 Dec 2027 (or Dec 2027) without naming the month
    year_end = d.month == 12 and d.day == 31 and re.search(rf"\bend[- ]?(of )?{d.year}\b", t) is not None
    if not (month_ok or year_end):
        return False
    if len(str(value).strip()) == 10 and not year_end:
        day_ok = re.search(rf"(?<!\d){d.day}(st|nd|rd|th)?(?!\d)", t) is not None or f"{d.isoformat()}" in t
        return day_ok
    return True


def verify(proposals: list[DeadlineProposal], reports: dict[str, VerificationReport], today: date,
           existing: list[dict]) -> tuple[list[dict], list[str]]:
    """Keep a proposal only if (1) its claim exists in a verified report, (2) the date is stated in that
    claim's verified quote, (3) it's in the future and (4) it's not already on the Radar.
    Returns (rows, notes on what was dropped)."""
    quotes: dict[str, tuple[str, str]] = {}          # "story:claim" and bare claim -> (quote, url)
    for sid, rep in reports.items():
        for e in rep.evidence:
            if e.quote_verified and e.stance == "supports":
                quotes.setdefault(f"{sid}:{e.claim_id}", (e.quote, e.resolved_url or e.url))
    kept, notes = [], []
    seen = {(r.get("product", "").lower(), str(r["date"])) for r in existing}
    seen_items = {(r.get("item", "").lower(), str(r["date"])) for r in existing}
    for p in proposals:
        key = p.claim_id if ":" in p.claim_id else None
        hit = quotes.get(key) if key else next((v for k, v in quotes.items() if k.endswith(":" + p.claim_id)), None)
        if hit is None:
            notes.append(f"radar: dropped '{p.item}' ({p.claim_id} is not a verified claim)")
            continue
        quote, url = hit
        if not _date_stated(p.date, quote):
            notes.append(f"radar: dropped '{p.item}' ({p.date} is not stated in the quote)")
            continue
        d = _as_date(p.date)
        if d is None or d < today:
            notes.append(f"radar: dropped '{p.item}' ({p.date} is past or not a date)")
            continue
        if (p.product.lower(), p.date) in seen or (p.item.lower(), p.date) in seen_items:
            continue
        seen.add((p.product.lower(), p.date))
        kept.append({"item": p.item.strip(), "product": p.product.strip(), "date": p.date, "kind": p.kind,
                     "source": url, "status": "new"})
    return kept, notes


def merge(new_rows: list[dict], p: Path | None = None) -> int:
    """Append approved rows to deadlines.yaml, keeping the file's header comments. Returns rows added."""
    p = p or path()
    rows = load(p)
    have = {(r.get("product", "").lower(), str(r["date"])) for r in rows}
    add = [r for r in new_rows if (r.get("product", "").lower(), str(r["date"])) not in have]
    if not add:
        return 0
    text = p.read_text(encoding="utf-8") if p.exists() else "rows:\n"
    if "rows:" not in text:
        text += "\nrows:\n"
    chunk = yaml.safe_dump(add, sort_keys=False, allow_unicode=True, width=200)
    chunk = "\n".join("  " + ln if ln.strip() else ln for ln in chunk.splitlines())
    p.write_text(text.rstrip("\n") + "\n" + chunk + "\n", encoding="utf-8")
    return len(add)
