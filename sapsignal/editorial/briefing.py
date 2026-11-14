"""v4 briefing: read each story once, write its item from that page, check every quote in code.

For each story:
  1. pick a READABLE copy: any outlet in the event's cluster (most authoritative first, paywalled sites
     last), decoding Google News wrappers only for the handful we actually read
  2. one LLM call returns claims + exact quotes + the reader-facing item (StoryBrief)
  3. code keeps only claims whose quote really is on the page; an item citing a dropped claim is retried
     once, then rebuilt from the surviving claims
  4. confidence comes from code: "high" when the page is a recognised outlet AND 2+ outlets carry the story,
     otherwise "developing" (rendered with attribution)

Nothing here can invent a source: sources come from the page we read and the outlets in today's feeds.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import get_config
from ..research.page_fetcher import Page, fetch_page
from ..research.source_registry import classify, is_aggregator, is_excluded, is_opinion_or_media, registrable_domain
from ..schemas import (Candidate, Claim, ClaimVerdict, Evidence, SourceTier, StoryBrief, VerificationReport)
from .evidence_ledger import quote_in_text
from .quality_gate import cited_ids

MIN_ARTICLE_CHARS = 1200      # video stubs and teaser pages are shorter; a real report is longer

RECOGNISED = {SourceTier.PRIMARY, SourceTier.TIER1_PRESS, SourceTier.REGIONAL_PRESS, SourceTier.TRADE_PRESS,
              SourceTier.RESEARCH_INSTITUTION}
_RANK = {SourceTier.PRIMARY: 0, SourceTier.TIER1_PRESS: 1, SourceTier.REGIONAL_PRESS: 2,
         SourceTier.TRADE_PRESS: 3, SourceTier.RESEARCH_INSTITUTION: 4}


def paywalled() -> set[str]:
    from ..agents.crews import paywalled_domains
    return paywalled_domains()


def reading_order(urls: list[str], publishers: dict[str, str] | None = None) -> list[str]:
    """Most authoritative readable outlet first; paywalled outlets last; excluded outlets never."""
    publishers = publishers or {}
    pw = paywalled()

    def key(u):
        dom = publishers.get(u) or registrable_domain(u)
        tier = classify("https://" + dom) if dom else SourceTier.UNKNOWN
        return (dom in pw, _RANK.get(tier, 8))
    seen, out = set(), []
    for u in sorted(urls, key=key):
        dom = publishers.get(u) or registrable_domain(u)
        if dom in seen or is_excluded(u) or (dom and is_excluded("https://" + dom)) or is_opinion_or_media(u):
            continue
        seen.add(dom)
        out.append(u)
    return out


def find_readable(cand: Candidate, publishers: dict[str, str] | None = None, attempts: int = 4,
                  fetch=fetch_page, decode=None) -> tuple[str, Page] | None:
    """The first copy of the story we can actually read, trying the outlets in the cluster in order."""
    from ..research.url_resolver import decode_google_news
    decode = decode or decode_google_news
    order = reading_order([cand.url, *cand.related_urls], publishers)
    pw = paywalled()
    tried = 0
    for u in order:
        if tried >= attempts:
            break
        if is_aggregator(u):
            real = decode([u]).get(u)
            if not real:
                continue
            u = real
        if registrable_domain(u) in pw or is_opinion_or_media(u):
            continue
        tried += 1
        page = fetch(u)
        if page.ok and len(page.text) >= MIN_ARTICLE_CHARS and not is_opinion_or_media(page.final_url or u):
            return u, page
    return None


def light_report(cand: Candidate, url: str, page: Page, brief: StoryBrief) -> tuple[VerificationReport, list[str]]:
    """Claims whose quote is on the page become 'supported' with a verified Evidence row; the rest are
    dropped. Returns the report and the ids that were dropped."""
    final = page.final_url or url
    tier = classify(final)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    claims, evidence, verdicts, dropped = [], [], [], []
    for qc in brief.claims:
        if not qc.quote.strip() or not quote_in_text(qc.quote, page.text):
            dropped.append(qc.id)
            continue
        claims.append(Claim(id=qc.id, text=qc.text, central=qc.central))
        evidence.append(Evidence(claim_id=qc.id, url=url, quote=qc.quote, origin=cand.source_name or registrable_domain(final),
                                 stance="supports", source_tier=tier, resolved_url=final, retrieved_at=now,
                                 quote_verified=True))
        verdicts.append(ClaimVerdict(claim_id=qc.id, verdict="supported", notes="quote found on the page read"))
    report = VerificationReport(candidate_id=cand.id, claims=claims, evidence=evidence, verdicts=verdicts,
                                summary=f"Read at {registrable_domain(final)}; {len(claims)} claim(s) matched verbatim.")
    return report, dropped


def confidence_for(page_url: str, outlets: int) -> str:
    return "high" if classify(page_url) in RECOGNISED and outlets >= 2 else "developing"


def authentic(page_url: str, outlet_names: list[str], breadth: int = 3) -> bool:
    """A story needs a recognised outlet behind it (the page we read, or another outlet carrying it), or
    broad independent coverage: `breadth`+ distinct outlets running it the same day."""
    if classify(page_url) in RECOGNISED:
        return True
    if any(classify("https://" + d) in RECOGNISED for d in outlet_names):
        return True
    return len(set(outlet_names)) >= breadth


def brief_problems(brief: StoryBrief, report: VerificationReport, dropped: list[str]) -> list[str]:
    known = {c.id for c in report.claims}
    problems = []
    bad = sorted(cited_ids(brief.summary) - known)
    if bad:
        problems.append(f"the summary cites {bad}, which are not claims backed by an exact quote"
                        + (f" (quotes for {dropped} were not found verbatim in the article)" if dropped else ""))
    if not report.claims:
        problems.append("no claim had a quote copied exactly from the article")
    return problems


def fallback_brief(brief: StoryBrief, report: VerificationReport) -> StoryBrief:
    """Last resort: the item rebuilt from the verified claims only (never from unverified text)."""
    text = " ".join(f"{c.text.rstrip('.')}. [{c.id}]" for c in report.claims[:3])
    return brief.model_copy(update={"summary": text})


# ------------------------------------------------------------------ selection
def balanced(scored: list[tuple[str, str, float]], n: int, per_section: dict, *, max_n: int | None = None) -> list[str]:
    """[(id, section, score)] -> ids. Each section first gets its minimum (best first, when it has
    stories), then the rest fill by score up to each section's max. Best overall stays first."""
    ranked = sorted(scored, key=lambda t: t[2], reverse=True)
    count: dict[str, int] = {}
    chosen: list[str] = []
    lim = lambda s, k: int((per_section.get(s) or {}).get(k, 0 if k == "min" else n))
    for sec in per_section:
        for cid, s, _ in ranked:
            if count.get(sec, 0) >= lim(sec, "min") or len(chosen) >= n:
                break
            if s == sec and cid not in chosen:
                chosen.append(cid); count[sec] = count.get(sec, 0) + 1
    for cid, s, _ in ranked:
        if len(chosen) >= (max_n or n):
            break
        if cid in chosen or count.get(s, 0) >= lim(s, "max"):
            continue
        chosen.append(cid); count[s] = count.get(s, 0) + 1
    order = {cid: i for i, (cid, _, _) in enumerate(ranked)}
    return sorted(chosen, key=lambda c: order[c])


def merge_reports(reports: list[VerificationReport]) -> tuple[VerificationReport, dict[str, dict[str, str]]]:
    """Several stories' claims as ONE ledger for the big read: ids renumbered C1..Cn so citations can't
    collide. Returns the merged report and {story_id: {old_id: new_id}}."""
    claims, evidence, verdicts, mapping = [], [], [], {}
    n = 0
    for r in reports:
        m = {}
        for c in r.claims:
            n += 1
            m[c.id] = f"C{n}"
            claims.append(c.model_copy(update={"id": f"C{n}"}))
        mapping[r.candidate_id] = m
        evidence += [e.model_copy(update={"claim_id": m[e.claim_id]}) for e in r.evidence if e.claim_id in m]
        verdicts += [v.model_copy(update={"claim_id": m[v.claim_id]}) for v in r.verdicts if v.claim_id in m]
    lead = reports[0].candidate_id if reports else ""
    return VerificationReport(candidate_id=lead, claims=claims, evidence=evidence, verdicts=verdicts,
                              summary="combined ledger"), mapping
