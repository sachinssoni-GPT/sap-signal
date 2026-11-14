"""The whole weekly pipeline offline: discovery -> briefs -> the Take -> Radar -> LinkedIn kit -> approve.
Every LLM call and every web request is replaced by a fake; nothing leaves the machine."""
import json
import shutil
from datetime import date, timedelta

import pytest
from pypdf import PdfReader

import main
from sapsignal import config, db, deadlines
from sapsignal.agents import crews
from sapsignal.editorial import briefing as br
from sapsignal.research.events import Hit
from sapsignal.research.page_fetcher import Page
from sapsignal.schemas import (DeadlineProposal, DeadlineProposals, LinkedInPack, QuotedClaim, StoryBrief, Take,
                               TakePlan, TakeSection, TriagePick, TriageResult)

TODAY = date.today()
NEXT_YEAR = TODAY.year + 1

ARTICLES = {
    "https://news.sap.com/2026/x": (
        "SAP said on Monday that customers on SAP Integration Suite must move off the legacy Neo environment. "
        f"The Neo environment will be retired on 31 March {NEXT_YEAR}, the company confirmed in a statement to "
        "customers. SAP said migration tooling is available at no extra cost for subscription customers. " * 6),
    "https://www.theregister.com/2026/y": (
        "Rimini Street said its third-party support customer count rose 12 percent in the quarter, as more "
        "ECC customers weigh staying on the platform beyond the mainstream maintenance deadline. "
        "Analysts said the shift reflects price pressure from RISE contracts. " * 8),
    "https://diginomica.com/2026/z": (
        "SAP published new clean core guidance that grades custom code in four levels, from A to D, and said "
        "level D code will block upgrades in the cloud editions. Customers are asked to classify extensions "
        "before their next release upgrade. " * 8),
}


def _hits():
    return [Hit("SAP to retire Neo environment, sets 31 March deadline", "https://news.sap.com/2026/x", "sap.com"),
            Hit("SAP sets deadline to retire the Neo environment for BTP", "https://www.theregister.com/2026/neo",
                "theregister.com"),
            Hit("Rimini Street third-party support customers rise as ECC deadline nears",
                "https://www.theregister.com/2026/y", "theregister.com"),
            Hit("SAP grades custom code A to D in new clean core guidance", "https://diginomica.com/2026/z",
                "diginomica.com")]


def _quote(url, start, n=14):
    words = ARTICLES[url].split()
    return " ".join(words[start:start + n])


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A temp project root with the real deadlines.yaml, and every outside call faked."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    shutil.copy(config.PROJECT_DIR / "deadlines.yaml", tmp_path / "deadlines.yaml")
    import sapsignal.flow as flow
    monkeypatch.setattr(flow, "read_feeds", lambda *a, **k: _hits())
    monkeypatch.setattr(flow, "read_telegram", lambda *a, **k: [])

    def triage(rows, max_picks, strict=False):
        assert "E1" in rows
        return TriageResult(picks=[
            TriagePick(event_id="E1", title="SAP retires the Neo environment", section="clean_core", significance=88,
                       why="A hard migration deadline for BTP customers"),
            TriagePick(event_id="E2", title="Third-party support grows", section="commercials", significance=70),
            TriagePick(event_id="E3", title="Clean core grades custom code A to D", section="clean_core",
                       significance=65)])
    monkeypatch.setattr(crews, "run_triage_events", triage)

    def readable(cand, publishers=None, **k):
        for u in [cand.url, *cand.related_urls]:
            if u in ARTICLES:
                return u, Page(url=u, final_url=u, text=ARTICLES[u], ok=True)
        return None
    monkeypatch.setattr(br, "find_readable", readable)

    def brief(c, article, url, also, feedback=""):
        return StoryBrief(claims=[QuotedClaim(id="C1", text="the change", quote=_quote(url, 0)),
                                  QuotedClaim(id="C2", text="the detail", quote=_quote(url, 14, 20))],
                          headline=c.title, summary="It changed [C1], with detail [C2].",
                          why_it_matters="Plan for it.", section=c.section)
    monkeypatch.setattr(crews, "run_story_brief", brief)
    monkeypatch.setattr(crews, "run_verification", lambda c: (_ for _ in ()).throw(RuntimeError("offline")))
    seen = {}

    def plan(items, recent_formats, recent_titles, notes="", prefer_topics=None):
        seen["plan_notes"], seen["plan_items"], seen["prefer"] = notes, items, prefer_topics
        return TakePlan(story_id=items[0]["candidate_id"], format="decision_guide", angle="Move now or wait?",
                        intro="A deadline week.")
    monkeypatch.setattr(crews, "run_plan_take", plan)

    def take(plan, title, report, opening, notes="", feedback=""):
        seen["take_notes"] = notes
        body = " ".join(["Neo retirement is real [C1] and the detail matters [C2]."] * 30)
        return Take(format=plan.format, title="Neo is going: move before the rush", dek="Why waiting costs more.",
                    sections=[TakeSection(heading="The date that matters", body=body),
                              TakeSection(heading="Three ways to move", body=body)],
                    watch=["Migration tooling updates [C1]"], social_post="Neo is going.", slug="neo")
    monkeypatch.setattr(crews, "run_take", take)

    def proposals(claims_by_story):
        sid = next(iter(claims_by_story))
        return DeadlineProposals(rows=[
            DeadlineProposal(item="Neo environment retired", product="SAP BTP Neo", date=f"{NEXT_YEAR}-03-31",
                             kind="retirement", claim_id=f"{sid}:C2", quote=f"31 March {NEXT_YEAR}"),
            DeadlineProposal(item="Invented date", product="SAP Something", date=f"{NEXT_YEAR}-07-01",
                             kind="other", claim_id=f"{sid}:C2", quote="1 July")])
    monkeypatch.setattr(crews, "run_deadlines", proposals)
    monkeypatch.setattr(crews, "run_linkedin", lambda *a, **k: LinkedInPack(
        share_post="Neo has a date.", story_post="Years ago... [YOUR STORY: a platform sunset you lived through]",
        story_needs_input=True, carousel_caption="Save this.", carousel_title="What's due in SAP"))
    return {"root": tmp_path, "seen": seen}


def _args(**kw):
    import argparse
    base = dict(edition=None, notify=False, force=False, reason="")
    base.update(kw)
    return argparse.Namespace(**base)


def test_a_full_week_produces_the_linkedin_kit_and_a_verified_radar(world):
    root = world["root"]
    (root / "notes").mkdir()
    (root / "notes" / "tg-1.md").write_text("Don't wait for the tooling to mature; inventory your Neo apps now.")
    status, eid = main._run(_args())
    assert status == "draft_ready"
    folder = root / "content" / "drafts" / eid
    ed = json.loads((folder / "edition.json").read_text())
    # the Signal leads, the Take was written from the author's notes
    assert ed["stories"][0]["headline"] == "SAP retires the Neo environment"
    assert ed["take_from_notes"] is True and "inventory your Neo apps" in world["seen"]["take_notes"]
    # Radar: the stated date survives, the invented one is dropped by code
    assert [r["item"] for r in ed["deadlines_new"]] == ["Neo environment retired"]
    assert ed["deadlines_new"][0]["source"] == "https://news.sap.com/2026/x"
    issue = (folder / "issue.md").read_text()
    assert "## This week's Signal" in issue and "## The Architect's Take" in issue and "## Deadline Radar" in issue
    assert "[C1]" not in issue and "[1]" in issue                         # citations renumbered for LinkedIn
    assert "**NEW**" in issue and "Mainstream maintenance ends for ECC 6.0" in issue
    li = folder / "linkedin"
    for f in ("1-tuesday-newsletter.html", "1-tuesday-title.txt", "1-tuesday-cover.png", "1-tuesday-share-post.txt",
              "2-thursday-story-post.txt", "3-saturday-carousel.pdf", "3-saturday-caption.txt"):
        assert (li / f).exists(), f
    pages = len(PdfReader(str(li / "3-saturday-carousel.pdf")).pages)
    assert pages == 2 + 1 + len(ed["stories"])                            # cover, radar, stories, follow
    assert "<h2>The Architect's Take</h2>" in (li / "1-tuesday-newsletter.html").read_text()
    # the weekly trigger firing twice does not make a second issue
    assert main._run(_args())[0] == "already_made"

    # approve: Radar row filed, notes archived, draft moved
    assert main.cmd_approve(_args(edition=eid)) == 0
    pub = root / "content" / "published" / eid
    assert (pub / "edition.json").exists() and not folder.exists()
    rows = deadlines.load()
    assert any(r["item"] == "Neo environment retired" and r["status"] == "new" for r in rows)
    assert (pub / "notes_used" / "tg-1.md").exists() and not list((root / "notes").glob("*.md"))
    assert db.get_edition(eid)["status"] == "published"


def test_banned_terms_block_approval(world, monkeypatch):
    monkeypatch.setenv("BANNED_TERMS", "Acme Corp, Neo")
    status, eid = main._run(_args())
    assert status == "draft_ready"
    ed = json.loads((world["root"] / "content" / "drafts" / eid / "edition.json").read_text())
    assert ed["take"] is None                                              # the Take kept failing the privacy gate
    assert any(w.startswith("BLOCKING") for w in ed["warnings"])
    assert main.cmd_approve(_args(edition=eid)) == 2                        # refused
    assert (world["root"] / "content" / "drafts" / eid).exists()


def test_without_notes_the_take_is_flagged_as_an_ai_draft(world):
    status, eid = main._run(_args())
    ed = json.loads((world["root"] / "content" / "drafts" / eid / "edition.json").read_text())
    assert status == "draft_ready" and ed["take_from_notes"] is False and world["seen"]["take_notes"] == ""


def test_reminders_send_the_right_piece(world, monkeypatch):
    from sapsignal.notify import messages
    sent = []
    monkeypatch.setattr(messages, "send_telegram", lambda text, *a, **k: sent.append(("text", text)) or "ok")
    monkeypatch.setattr(messages, "send_telegram_document", lambda p, c="": sent.append(("doc", p.name)) or "ok")
    status, eid = main._run(_args())
    main.cmd_approve(_args(edition=eid))
    main.cmd_remind(_args(day="thursday"))
    assert any("[YOUR STORY" in t for k, t in sent if k == "text") and any("gap" in t for k, t in sent if k == "text")
    sent.clear()
    main.cmd_remind(_args(day="saturday"))
    assert ("doc", "3-saturday-carousel.pdf") in sent


def test_avoided_topics_never_get_the_take_without_notes(world):
    # make the top story a security patch story
    orig = crews.run_triage_events
    def triage(rows, max_picks, strict=False):
        r = orig(rows, max_picks)
        r.picks[0].title = "SAP patches four CVE-rated vulnerabilities on Patch Day"
        return r
    crews.run_triage_events = triage
    try:
        status, eid = main._run(_args())
    finally:
        crews.run_triage_events = orig
    assert status == "draft_ready"
    ids = [i["headline"] for i in world["seen"]["plan_items"]]
    assert all("Patch Day" not in h for h in ids) and world["seen"]["prefer"][0].startswith("Application architecture")
    ed = json.loads((world["root"] / "content" / "drafts" / eid / "edition.json").read_text())
    assert ed["stories"][0]["headline"] != "SAP patches four CVE-rated vulnerabilities on Patch Day"
    assert any("Patch Day" in s["headline"] for s in ed["stories"])          # still in the issue as news


def test_outlets_with_one_owner_count_once():
    from sapsignal.flow import distinct_owners
    assert distinct_owners(["erp.today", "sapinsider.org", "theregister.com"]) == 2
    assert distinct_owners(["erp.today", "sapinsider.org"]) == 1
