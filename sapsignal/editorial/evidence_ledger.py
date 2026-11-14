"""Deterministic verification gate. The model proposes evidence; code decides what counts.

Rules (all enforced here, none delegated to an LLM):
  1. A quote only counts if it appears verbatim (after whitespace/quote normalisation) in the page we fetched.
  2. A central claim is 'supported' only with >= N independent origins AND distinct domains among
     verified supporting evidence, and at least one non-aggregator source.
  3. Any verified contradicting evidence on a central claim fails the story.
"""
import re
from dataclasses import dataclass, field
from typing import Callable

from ..research.page_fetcher import Page, fetch_page
from ..research.source_registry import classify, normalize_origin, perspective_of, registrable_domain
from ..schemas import Claim, ClaimVerdict, Evidence, SourceTier, VerificationReport

_MIN_FRAGMENT = 20


def normalize_text(s: str) -> str:
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in_text(quote: str, text: str) -> bool:
    """Every fragment (split on ellipses) must appear verbatim; fragments must be substantial."""
    nt = normalize_text(text)
    fragments = [f for f in re.split(r"\.\.\.|\u2026", quote) if f.strip()]
    if not fragments:
        return False
    for f in fragments:
        nf = normalize_text(f)
        if len(nf) < _MIN_FRAGMENT or nf not in nt:
            return False
    return True


def check_quotes(report: VerificationReport, fetch: Callable[[str], Page] = fetch_page) -> VerificationReport:
    for ev in report.evidence:
        try:
            page = fetch(ev.url)
        except Exception:
            ev.quote_verified = False
            ev.source_tier = SourceTier.UNKNOWN
            ev.source_perspective = "unclassified"
            continue
        # Classify publisher after redirects, not a Google News wrapper.
        ev.resolved_url = page.final_url or ev.url
        ev.source_tier = classify(ev.resolved_url)
        ev.source_perspective = perspective_of(ev.resolved_url)
        ev.retrieved_at = page.retrieved_at
        ev.quote_verified = bool(page.ok and quote_in_text(ev.quote, page.text))
    return report



def authenticate_candidate(candidate, fetch: Callable[[str], Page] = fetch_page):
    """Authenticate the candidate's own publisher page as a fallback source.

    This is deliberately separate from multi-origin corroboration: an authentic
    single-source report may be published as attributed/developing news.
    Returns (is_authentic, evidence, diagnostic).
    """
    try:
        page = fetch(candidate.url)
    except Exception as exc:
        return False, None, f"candidate source fetch failed: {type(exc).__name__}: {exc}"
    final_url = page.final_url or candidate.url
    eligible = {SourceTier.PRIMARY, SourceTier.TIER1_PRESS, SourceTier.TRADE_PRESS,
                SourceTier.RESEARCH_INSTITUTION, SourceTier.REGIONAL_PRESS}
    tier = classify(final_url)
    text = (page.text or "").strip()
    if not page.ok or tier not in eligible or len(text) < 90:
        return False, None, f"candidate source not authenticated (ok={page.ok}, tier={tier.value}, chars={len(text)})"
    # Use a literal excerpt from the fetched publisher page; do not invent a claim.
    excerpt = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
    if len(excerpt) < _MIN_FRAGMENT:
        excerpt = text[:500].strip()
    if len(excerpt) < _MIN_FRAGMENT:
        return False, None, "candidate publisher page has no usable text excerpt"
    evidence = Evidence(
        claim_id="C1", url=candidate.url, quote=excerpt,
        origin=candidate.source_name or registrable_domain(final_url), stance="supports",
        source_tier=tier, source_perspective=perspective_of(final_url),
        resolved_url=final_url, retrieved_at=page.retrieved_at, quote_verified=True,
    )
    return True, evidence, f"authenticated publisher page: {final_url} ({tier.value})"


@dataclass
class GateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    confidence: str = "low"
    corroborated_claims: int = 0
    central_claims: int = 0


def apply_gate(report: VerificationReport, min_origins: int = 2, claim_type_rules: dict | None = None) -> GateResult:
    failures: list[str] = []
    verdicts: list[ClaimVerdict] = []
    central = [c for c in report.claims if c.central]
    corroborated_central = 0
    if not central:
        failures.append("No central claim identified")
    if not report.claims:
        failures.append("Verification returned no factual claims")

    for claim in report.claims:
        ev = [e for e in report.evidence if e.claim_id == claim.id and e.quote_verified]
        supports = [e for e in ev if e.stance == "supports"]
        eligible_tiers = {
            SourceTier.PRIMARY, SourceTier.TIER1_PRESS, SourceTier.TRADE_PRESS,
            SourceTier.RESEARCH_INSTITUTION, SourceTier.REGIONAL_PRESS,
        }
        contradicts = [
            e for e in ev if e.stance == "contradicts" and e.source_tier in eligible_tiers
        ]
        origins = {normalize_origin(e.origin, e.resolved_url or e.url) for e in supports}
        domains = {registrable_domain(e.resolved_url or e.url) for e in supports}
        independent = min(len(origins), len(domains))
        # Editorial policy: a single credible, quote-verified source can establish
        # an authentic developing report. Higher-risk claims retain stronger thresholds.
        claim_kind = getattr(claim, "claim_type", "general") or "general"
        required = max(1, int((claim_type_rules or {}).get(claim_kind, min_origins)))
        # A listed (recognised) outlet can establish a claim on its own. Outlets NOT on the list can still
        # establish it when at least two independent ones agree. Aggregators, vendors and excluded outlets
        # never count.
        never = {SourceTier.AGGREGATOR, SourceTier.VENDOR, SourceTier.EXCLUDED}
        has_real_source = any(e.source_tier in eligible_tiers for e in supports)
        countable = [e for e in supports if e.source_tier not in never]
        unknown_domains = sorted({registrable_domain(e.resolved_url or e.url) for e in countable
                                  if e.source_tier == SourceTier.UNKNOWN})
        low_risk = (getattr(claim, "claim_type", "general") or "general") in {"general", "official_statement"}
        if not has_real_source and countable and low_risk:
            o = {normalize_origin(e.origin, e.resolved_url or e.url) for e in countable}
            d = {registrable_domain(e.resolved_url or e.url) for e in countable}
            has_real_source = min(len(o), len(d)) >= 2

        if contradicts:
            verdict, note = "contradicted", f"{len(contradicts)} verified contradicting source(s)"
        elif independent >= required and has_real_source:
            verdict = "supported"
            note = (f"{independent} independent origin(s); "
                    + ("corroborated" if independent >= 2 else "single-source developing report; qualify attribution and confidence"))
            if claim.central and independent >= 2:
                corroborated_central += 1
        elif independent >= required:
            verdict = "unverifiable"
            note = (f"{independent} verified source(s), but only from outlets not on the source list "
                    f"({', '.join(unknown_domains) or 'none'}); "
                    + ("a listed outlet or 2+ independent ones are needed. " if low_risk else
                       "this claim type needs at least one listed outlet. ") +
                    "Add credible outlets to `sources:` in config.yaml")
        else:
            verdict, note = "unverifiable", f"only {independent} independent verified origin(s); {required} required"
        verdicts.append(ClaimVerdict(claim_id=claim.id, verdict=verdict, notes=note))

        if claim.central and verdict != "supported":
            failures.append(f"Central claim {claim.id} is {verdict}: {note}")

    report.verdicts = verdicts
    if failures:
        confidence = "insufficient"
    elif corroborated_central == len(central):
        confidence = "high"
    elif corroborated_central:
        confidence = "moderate"
    else:
        confidence = "developing"
    return GateResult(
        passed=not failures,
        failures=failures,
        confidence=confidence,
        corroborated_claims=sum(v.verdict == "supported" and "corroborated" in v.notes for v in verdicts),
        central_claims=len(central),
    )
