"""Discovery and selection (shared engine): clustering, coverage counts, tips, reading order, beat balance."""
from sapsignal.editorial import briefing as br
from sapsignal.research import events as ev
from sapsignal.research.events import Hit
from sapsignal.schemas import Claim, Evidence, VerificationReport


def test_same_event_from_several_outlets_is_one_event_with_a_coverage_count():
    hits = [Hit("RBI holds repo rate at 5.5% as inflation cools", "https://www.livemint.com/a", "livemint.com"),
            Hit("RBI keeps repo rate unchanged at 5.5%, inflation cools", "https://www.reuters.com/b", "reuters.com"),
            Hit("Repo rate held at 5.5% by RBI", "https://economictimes.indiatimes.com/c", "indiatimes.com"),
            Hit("Russia and Ukraine delegations meet in Abu Dhabi", "https://www.dw.com/d", "dw.com")]
    out = ev.cluster(hits)
    assert len(out) == 2
    rbi = out[0]
    assert rbi.id == "E1" and len(rbi.outlets) == 3                      # most-covered event first
    assert rbi.title.startswith("RBI keeps")                             # headline from the wire (tier 1)


def test_two_word_overlap_does_not_glue_unrelated_stories():
    hits = [Hit("India China talks", "https://a.com/1", "a.com"), Hit("India China trade deficit widens", "https://b.com/2", "b.com"),
            Hit("India cricket squad named", "https://c.com/3", "c.com")]
    assert len(ev.cluster(hits)) >= 2


def test_telegram_tip_boosts_an_event_but_is_never_an_outlet():
    hits = [Hit("Fed cuts interest rates by quarter point", "https://www.cnbc.com/a", "cnbc.com"),
            Hit("BREAKING: Fed cuts interest rates by a quarter point", "https://t.me/s/chan", via="telegram"),
            Hit("Telegram-only rumour about a merger nobody reported", "https://t.me/s/chan", via="telegram")]
    out = ev.cluster(hits)
    assert len(out) == 1                                                 # tip-only clusters are dropped
    assert out[0].tips == 1 and out[0].outlets == ["cnbc.com"] and "t.me" not in " ".join(out[0].urls())
    assert "TIP" in ev.triage_rows(out)


def test_telegram_web_preview_is_parsed():
    html = ('<div class="tgme_widget_message_wrap x"><div class="tgme_widget_message_text js">Big news: '
            'parliament passes the data protection amendment after a long debate.</div>'
            '<time datetime="2099-01-01T10:00:00+00:00"></time></div>')
    hits = ev.read_telegram(["@chan"], 24, fetch=lambda name: html)
    assert len(hits) == 1 and hits[0].via == "telegram" and hits[0].title.startswith("Big news")





def test_every_section_query_becomes_a_free_google_news_feed():
    cfg = {"sections": {"india": {"region": "IN", "queries": ["RBI policy"], "feeds": ["https://x/rss"]},
                        "tech": {"queries": ["AI chips"]}}}
    out = ev.section_sources(cfg, days=1)
    assert out[0][1] == "india" and "q=RBI+policy+when%3A1d" in out[0][0] and "gl=IN" in out[0][0]
    assert ("https://x/rss", "india") in out and "gl=US" in out[2][0]


def test_stories_from_recent_issues_are_not_repeated():
    e = ev.cluster([Hit("RBI holds repo rate at 5.5% as inflation cools", "https://www.livemint.com/a", "livemint.com"),
                    Hit("Oil falls below 60 dollars after OPEC deal", "https://www.cnbc.com/b", "cnbc.com")])
    left = ev.drop_already_covered(e, ["RBI holds repo rate at 5.5 per cent as inflation cools"])
    assert [x.title for x in left] == ["Oil falls below 60 dollars after OPEC deal"]





def test_section_balance_guarantees_minimums_and_caps():
    scored = [(f"W{i}", "world", 90 - i) for i in range(8)] + [("I1", "india", 50), ("I2", "india", 48),
                                                                ("T1", "tech", 40)]
    per = {"india": {"min": 2, "max": 4}, "world": {"min": 2, "max": 4}, "economy": {"min": 1, "max": 3},
           "tech": {"min": 1, "max": 3}}
    out = br.balanced(scored, 8, per)
    assert out[0] == "W0" and {"I1", "I2", "T1"} <= set(out)
    assert sum(x.startswith("W") for x in out) == 4 and len(out) == 7    # world capped; no economy stories exist


def test_merged_ledger_renumbers_claims_so_citations_cannot_collide():
    a = VerificationReport(candidate_id="A", claims=[Claim(id="C1", text="a1"), Claim(id="C2", text="a2")],
                           evidence=[Evidence(claim_id="C2", url="u", quote="q")])
    b = VerificationReport(candidate_id="B", claims=[Claim(id="C1", text="b1")], evidence=[Evidence(claim_id="C1", url="v", quote="q")])
    merged, mapping = br.merge_reports([a, b])
    assert [c.id for c in merged.claims] == ["C1", "C2", "C3"] and mapping == {"A": {"C1": "C1", "C2": "C2"}, "B": {"C1": "C3"}}
    assert [e.claim_id for e in merged.evidence] == ["C2", "C3"]


def test_confidence_and_authenticity_come_from_code():
    assert br.confidence_for("https://www.livemint.com/a", outlets=3) == "high"
    assert br.confidence_for("https://www.livemint.com/a", outlets=1) == "developing"
    assert br.confidence_for("https://randomblog.net/a", outlets=5) == "developing"
    assert br.authentic("https://randomblog.net/a", ["randomblog.net", "reuters.com"])
    assert not br.authentic("https://randomblog.net/a", ["randomblog.net", "otherblog.org"])





def test_todays_real_near_duplicates_are_caught():
    from sapsignal.flow import _same_event
    assert _same_event("Nvidia board meets to decide Jensen Huang's fate",
                       "Alice Huang allegedly accessed Jensen Huang's Nvidia insights via private conversations")
    assert _same_event("Russia agrees prisoner swap with Ukraine after Abu Dhabi talks",
                       "Russia attends Abu Dhabi talks but is not ready to make peace")
    assert not _same_event("Moody's retains India FY27 growth forecast at 7%",
                           "India says BTA talks on track despite Republican midterm loss")


def test_opinion_columns_and_video_pages_are_never_briefed_from():
    urls = ["https://www.aljazeera.com/opinions/2026/11/11/putin-is-not-ready", "https://www.modernghana.com/videonews/aljazeera/1/7",
            "https://www.aljazeera.com/news/2026/11/11/prisoner-exchange"]
    assert br.reading_order(urls) == ["https://www.aljazeera.com/news/2026/11/11/prisoner-exchange"]


def test_broad_coverage_authenticates_a_story_without_a_listed_outlet():
    assert br.authentic("https://www.digitimes.com/x", ["digitimes.com", "taipeitimes.com", "focustaiwan.tw"])
    assert not br.authentic("https://www.digitimes.com/x", ["digitimes.com", "focustaiwan.tw"])


