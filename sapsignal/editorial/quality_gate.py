"""Deterministic quality checks. The LLM editor handles judgment (generic writing, tone, certainty);
everything checkable in plain Python is checked here so it cannot be talked around."""
import re
from ..schemas import CheckResult, QualityReport, VerificationReport

CITE = re.compile(r"\[(C\d+)\]")
_GROUP = re.compile(r"\[((?:C\d+)(?:\s*[,;\-–]\s*C?\d+)*)\]")


def cited_ids(text: str) -> set[str]:
    """Every claim id cited, including grouped markers like [C3, C4], [C3, 4] or ranges like [C1-C4]."""
    from ..publishing.text import _ids
    out = set()
    for g in _GROUP.findall(text or ""):
        out |= {i for i in _ids(g) if i.startswith("C")}
    return out


# ------------------------------------------------------------------ privacy
def banned_terms() -> list[str]:
    """Words that must never appear in output (employer, clients...): env BANNED_TERMS (comma-separated,
    kept out of git) plus config privacy.banned_terms."""
    import os
    from ..config import get_config
    env = [t.strip() for t in os.environ.get("BANNED_TERMS", "").split(",") if t.strip()]
    cfg = [str(t).strip() for t in ((get_config().get("privacy", {}) or {}).get("banned_terms") or []) if str(t).strip()]
    return sorted(set(env + cfg), key=str.lower)


def find_banned(text: str, terms: list[str] | None = None) -> list[str]:
    terms = banned_terms() if terms is None else terms
    low = (text or "").lower()
    return [t for t in terms if re.search(rf"(?<![a-z0-9]){re.escape(t.lower())}(?![a-z0-9])", low)]


# ------------------------------------------------------------------ the Architect's Take
STOCK_HEADINGS = {"background", "analysis", "conclusion", "what happened", "my read", "why it matters",
                  "introduction", "context", "summary", "overview", "what to watch", "the take"}
_FORECAST = re.compile(r"\b(\d{1,3}\s?% (?:confident|chance|probability|likely)|check me on|i predict that)\b", re.I)


def take_text(t) -> str:
    return "\n\n".join(s.body for s in t.sections)


def check_take(t, report: VerificationReport, cfg: dict) -> QualityReport:
    """Made-up citations and banned terms block; the rest are warnings shown in the approval message."""
    tc = (cfg.get("edition", {}) or {}).get("take", {}) or {}
    lo, hi = int(tc.get("min_words", 400)), int(tc.get("max_words", 650))
    checks: list[CheckResult] = []

    def add(name, ok, detail="", severity="info"):
        checks.append(CheckResult(name=name, passed=ok, severity=severity, detail=detail))

    body = take_text(t)
    everything = "\n".join([t.title, t.dek, body, *t.watch, t.social_post])
    known = {c.id for c in report.claims}
    unknown = sorted(cited_ids(everything) - known)
    add("citations_reference_real_claims", not unknown, f"unknown claim ids: {unknown}", "block")
    add("cites_evidence", bool(cited_ids(body) & known), "the piece cites no verified claim", "block")
    banned = find_banned(everything)
    add("no_banned_terms", not banned, f"contains banned term(s): {banned}", "block")
    wc = len(body.split())
    add("word_count_in_range", lo * 0.8 <= wc <= hi * 1.25, f"{wc} words (aim {lo}-{hi})")
    add("has_sections", 2 <= len(t.sections) <= 5, f"{len(t.sections)} sections")
    stock = [s.heading for s in t.sections if s.heading.strip().lower().rstrip(":?") in STOCK_HEADINGS]
    add("headings_are_specific", not stock, f"stock headings: {stock}")
    lowered = everything.lower()
    hits = [p for p in cfg.get("quality", {}).get("banned_phrases", []) if p in lowered]
    add("no_generic_phrases", not hits, f"found: {hits}")
    add("no_dated_forecasts", not _FORECAST.search(everything), "contains odds or 'check me on' language")
    add("title_length", len(t.title.split()) <= 14, f"{len(t.title.split())} words")
    blocked = [c for c in checks if not c.passed and c.severity == "block"]
    issues = [f"{c.name}: {c.detail}" for c in checks if not c.passed]
    return QualityReport(verdict="reject" if blocked else "pass", checks=checks, issues=issues,
                         feedback="; ".join(issues))
