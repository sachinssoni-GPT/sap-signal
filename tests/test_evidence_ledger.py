from sapsignal.editorial.evidence_ledger import apply_gate, quote_in_text
from sapsignal.schemas import Claim, Evidence, SourceTier, VerificationReport


def _ev(url, origin, tier=SourceTier.TIER1_PRESS, stance="supports", verified=True):
    return Evidence(
        claim_id="C1", url=url, origin=origin, quote="A sufficiently long verified quotation.",
        stance=stance, source_tier=tier, quote_verified=verified,
    )


def _report(evidence):
    return VerificationReport(
        candidate_id="S1",
        claims=[Claim(id="C1", text="A material factual claim", central=True)],
        evidence=evidence,
    )


def test_quote_requires_substantial_exact_fragment():
    assert quote_in_text("A sufficiently long verified quotation.", "Text: A sufficiently long verified quotation. End.")
    assert not quote_in_text("short quote", "short quote")
    assert not quote_in_text("A fabricated quotation that is not present.", "A different page entirely.")


def test_two_domains_and_origins_pass():
    report = _report([
        _ev("https://reuters.com/story", "Reuters reporting"),
        _ev("https://apnews.com/story", "AP reporting"),
    ])
    result = apply_gate(report, min_origins=2)
    assert result.passed
    assert report.verdicts[0].verdict == "supported"


def test_same_origin_syndicated_across_domains_does_not_pass():
    report = _report([
        _ev("https://news.example.com/a", "Same original press release"),
        _ev("https://another.example.org/b", "Same original press release"),
    ])
    result = apply_gate(report, min_origins=2)
    assert not result.passed
    assert report.verdicts[0].verdict == "unverifiable"


def test_unknown_and_aggregator_sources_do_not_support_claim():
    report = _report([
        _ev("https://unknown-source.invalid/a", "Source A", SourceTier.UNKNOWN),
        _ev("https://news.google.com/a", "Source B", SourceTier.AGGREGATOR),
    ])
    assert not apply_gate(report, min_origins=2).passed


def test_quote_verified_contradiction_blocks_central_claim():
    report = _report([
        _ev("https://reuters.com/story", "Reuters reporting"),
        _ev("https://apnews.com/story", "AP reporting"),
        _ev("https://ft.com/story", "FT reporting", stance="contradicts"),
    ])
    result = apply_gate(report, min_origins=2)
    assert not result.passed
    assert report.verdicts[0].verdict == "contradicted"


def test_unverified_quotes_do_not_count():
    report = _report([
        _ev("https://reuters.com/story", "Reuters reporting", verified=False),
        _ev("https://apnews.com/story", "AP reporting", verified=False),
    ])
    assert not apply_gate(report, min_origins=2).passed


def test_unlisted_outlets_count_only_when_two_agree_on_low_risk_claims():
    one = _report([_ev("https://unknown-one.invalid/a", "Unknown outlet one", SourceTier.UNKNOWN)])
    res = apply_gate(one, min_origins=1)
    assert not res.passed and "not on the source list" in res.failures[0]
    two = _report([
        _ev("https://unknown-one.invalid/a", "Unknown outlet one", SourceTier.UNKNOWN),
        _ev("https://unknown-two.invalid/b", "Unknown outlet two", SourceTier.UNKNOWN),
    ])
    assert apply_gate(two, min_origins=2).passed                   # general claim: two independent unlisted agree


def test_high_risk_claims_still_need_a_listed_outlet():
    from sapsignal.schemas import Claim
    rep = _report([
        _ev("https://unknown-one.invalid/a", "Unknown outlet one", SourceTier.UNKNOWN),
        _ev("https://unknown-two.invalid/b", "Unknown outlet two", SourceTier.UNKNOWN),
    ])
    rep.claims = [Claim(id="C1", text="40 killed in strike", central=True, claim_type="conflict_or_casualty")]
    res = apply_gate(rep, min_origins=1, claim_type_rules={"conflict_or_casualty": 2})
    assert not res.passed and "needs at least one listed outlet" in res.failures[0]


def test_aggregator_and_excluded_never_count_even_when_two_agree():
    rep = _report([
        _ev("https://news.google.com/a", "Agg one", SourceTier.AGGREGATOR),
        _ev("https://www.opindia.com/b", "Excluded", SourceTier.EXCLUDED),
    ])
    assert not apply_gate(rep, min_origins=1).passed


def test_redirected_url_is_used_for_origin_domain_and_tier_checks():
    from sapsignal.editorial.evidence_ledger import check_quotes
    from sapsignal.research.page_fetcher import Page

    text = "A sufficiently long verified quotation."
    def fetch(url):
        return Page(url=url, final_url="https://www.reuters.com/story", text=text,
                    ok=True, retrieved_at="2026-11-04T00:00:00+00:00")

    report = _report([Evidence(
        claim_id="C1", url="https://news.google.com/rss/articles/example",
        origin="Reuters original reporting", quote=text,
    )])
    check_quotes(report, fetch=fetch)
    assert report.evidence[0].quote_verified is True
    assert report.evidence[0].source_tier == SourceTier.TIER1_PRESS
    assert report.evidence[0].resolved_url == "https://www.reuters.com/story"
    assert apply_gate(report, min_origins=1).passed



def test_quote_fetch_exception_marks_evidence_unverified_instead_of_crashing():
    from sapsignal.editorial.evidence_ledger import check_quotes
    report = _report([_ev("https://reuters.com/story", "Reuters")])

    def broken_fetch(url):
        raise TimeoutError("network timeout")

    checked = check_quotes(report, fetch=broken_fetch)
    assert checked.evidence[0].quote_verified is False
    assert checked.evidence[0].source_tier == SourceTier.UNKNOWN


def test_authentic_candidate_page_is_sufficient_for_developing_story():
    from types import SimpleNamespace
    from sapsignal.editorial.evidence_ledger import authenticate_candidate
    candidate = SimpleNamespace(id="S1", title="Government extends strategic framework",
                                url="https://www.reuters.com/b", source_name="Reuters",
                                summary="Government framework update")
    from sapsignal.research.page_fetcher import Page
    page_text = "The government announced on Tuesday that it will extend the strategic framework until 2030 for selected partners. This is a sufficiently detailed publisher article with further reporting and context."
    def fake_fetch(url):
        return Page(url=url, final_url=url, text=page_text, ok=True, retrieved_at="2026-11-05T00:00:00+00:00")
    ok, evidence, note = authenticate_candidate(candidate, fetch=fake_fetch)
    assert ok is True
    assert evidence is not None and evidence.quote_verified is True
    assert evidence.source_tier == SourceTier.TIER1_PRESS
    assert "authenticated publisher page" in note
