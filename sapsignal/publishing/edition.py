"""Builds and writes the weekly issue package.

  content/drafts/<id>/
    issue.md                         the whole issue (email preview + archive), same text as the LinkedIn article
    edition.json                     everything, structured (approval, Telegram, reminders)
    linkedin/
      1-tuesday-newsletter.html      open in a browser, copy all, paste into LinkedIn's article editor
      1-tuesday-title.txt            edition title + subtitle
      1-tuesday-cover.png            1280x720 cover image for the edition
      1-tuesday-share-post.txt       the text that goes with the edition
      2-thursday-story-post.txt      the personal post (may contain [YOUR STORY: ...] gaps)
      3-saturday-carousel.pdf        LinkedIn document post (+ slides/ as PNGs)
      3-saturday-caption.txt
    evidence/<id>.json, take_evidence.json, quality.json, radar_new.json, EDITORIAL_WARNINGS.md

Sources always come from the evidence ledger, never from model text.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import markdown as md

from .. import deadlines as dl
from ..config import get_config
from ..editorial.quality_gate import find_banned
from ..schemas import Brief, Candidate, Edition, EditionStory, LinkedInPack, QualityReport, SourceRef, VerificationReport
from .renderer import FORMAT_LABELS, take_sources
from .text import MARKERS, _ids, human_dates, reader

LINKEDIN_DIR = "linkedin"


def sources_for(report: VerificationReport) -> list[SourceRef]:
    seen, out = set(), []
    for e in report.evidence:
        if not (e.quote_verified and e.stance == "supports"):
            continue
        url = e.resolved_url or e.url
        if url in seen:
            continue
        seen.add(url)
        out.append(SourceRef(origin=e.origin or "source", url=url, tier=e.source_tier.value,
                             perspective=e.source_perspective))
    return out


def clean_brief(brief: Brief, report: VerificationReport) -> tuple[Brief, list[str]]:
    """Drop citation markers that point at claims this story does not have; strip markers for readers."""
    from ..editorial.quality_gate import cited_ids
    known = {c.id for c in report.claims}
    bad = sorted(cited_ids(brief.summary) - known)
    warnings = [f"{brief.candidate_id}: brief cited unknown claim ids {bad}"] if bad else []
    return brief.model_copy(update={"summary": reader(brief.summary), "headline": reader(brief.headline),
                                    "why_it_matters": reader(brief.why_it_matters)}), warnings


def build_edition(*, edition_date: str, run_id: str, ordered_ids: list[str], edition_id: str = "",
                  candidates: dict[str, Candidate], reports: dict[str, VerificationReport],
                  totals: dict[str, float], confidence: dict[str, str], briefs: list[Brief],
                  quality: QualityReport, take=None, take_ids: list[str] | None = None, take_from_notes: bool = False,
                  intro: str = "", linkedin: LinkedInPack | None = None, radar_new: list[dict] | None = None,
                  issue_no: int = 1) -> Edition:
    from ..research.source_registry import classify, outlet_name, registrable_domain
    from ..schemas import SourceTier
    by_id = {b.candidate_id: b for b in briefs}
    warnings = list(quality.issues)
    stories: list[EditionStory] = []
    for rank, cid in enumerate(ordered_ids, start=1):
        cand, report = candidates[cid], reports[cid]
        brief = by_id.get(cid)
        if brief is None:   # never invent: fall back to the verified claim text
            brief = Brief(candidate_id=cid, headline=cand.title,
                          summary=" ".join(c.text for c in report.claims[:3]) or cand.title, why_it_matters="")
            warnings.append(f"{cid}: brief missing; used verified claim text")
        brief, w = clean_brief(brief, report)
        warnings += w
        srcs = [r.model_copy(update={"origin": outlet_name(r.url)}) for r in sources_for(report)]
        read = {registrable_domain(r.url) for r in srcs}
        also = [SourceRef(origin=outlet_name(d), url="", tier=classify("https://" + d).value)
                for d in cand.outlet_names if d not in read][:4]
        tiers = {classify(r.url) for r in srcs} | {classify("https://" + d) for d in cand.outlet_names}
        vendor_only = bool(tiers) and tiers <= {SourceTier.VENDOR, SourceTier.UNKNOWN, SourceTier.AGGREGATOR}
        stories.append(EditionStory(
            rank=rank, candidate_id=cid, headline=brief.headline, summary=brief.summary,
            why_it_matters=brief.why_it_matters, confidence=confidence.get(cid, "developing"),
            score=totals.get(cid, 0.0), sources=srcs, section=cand.section, also_reported=also,
            vendor_only=vendor_only))
    lead = stories[0]
    if take is not None:
        title, description = reader(take.title), reader(take.dek)
    else:
        title, description = lead.headline, reader(intro) or "This week: " + "; ".join(s.headline for s in stories[1:4])
    return Edition(edition_date=edition_date, edition_id=edition_id or edition_date, run_id=run_id, title=title,
                   description=description, lead_id=ordered_ids[0], stories=stories, take=take,
                   take_ids=list(take_ids or []), take_from_notes=take_from_notes, intro=reader(intro),
                   linkedin=linkedin, deadlines_new=list(radar_new or []), issue_no=issue_no, quality=quality,
                   warnings=warnings)


# ------------------------------------------------------------------ the issue text (LinkedIn article)
def _li_cfg() -> dict:
    return get_config().get("linkedin", {}) or {}


def _numbered(text: str, mapping: dict[str, int]) -> str:
    """[C3] / [C3, C4] -> [1] / [1][2] using the Sources numbering (LinkedIn strips in-page anchors)."""
    def sub(m):
        nums = [mapping[i] for i in _ids(m.group(1)) if i in mapping]
        return "".join(f"[{n}]" for n in nums)
    return re.sub(r"\s+([.,;:])", r"\1", MARKERS.sub(lambda m: (" " + sub(m)) if sub(m) else "", text or "")).strip()


def radar_rows(ed: Edition) -> list[dict]:
    rows = dl.load()
    have = {(r.get("product", "").lower(), str(r["date"])) for r in rows}
    rows += [r for r in ed.deadlines_new if (r.get("product", "").lower(), str(r["date"])) not in have]
    n = int((get_config().get("edition", {}) or {}).get("radar_rows", 8))
    return dl.upcoming(rows, date.fromisoformat(ed.edition_date), n)


def countdown(days: int | None) -> str:
    if days is None:
        return ""
    if days <= 120:
        return f"in {days} days"
    if days <= 730:
        return f"in ~{round(days / 30.4)} months"
    return f"in ~{round(days / 365.25)} years"


def _radar_line(r: dict, today: date) -> str:
    days = dl.days_until(r["date"], today)
    when = countdown(days)
    new = " **NEW**" if r.get("status") == "new" else ""
    src = f" ([source]({r['source']}))" if r.get("source") else ""
    return f"- **{dl.label(r['date'])}**{new} · {r['item']} · *{r.get('product', '')}*" + (f" · {when}" if when else "") + src


def render_issue_md(ed: Edition, take_report: VerificationReport | None) -> str:
    """The whole issue, in reading order: intro, the Signal, the Take, five things, the Radar, sources."""
    from ..research.events import SECTION_LABELS
    name = (get_config().get("publication", {}) or {}).get("name", "")
    author = (get_config().get("publication", {}) or {}).get("author", "")
    today = date.fromisoformat(ed.edition_date)
    lines = []
    if ed.intro:
        lines += [f"*{ed.intro}*", ""]
    lead, rest = ed.stories[0], ed.stories[1:]
    lines += ["## This week's Signal", "", f"**{lead.headline}**", "", lead.summary, ""]
    if lead.why_it_matters:
        lines += [f"**What it changes:** {lead.why_it_matters}", ""]
    if lead.sources:
        lines += ["Source: " + " · ".join(f"[{s.origin}]({s.url})" for s in lead.sources[:2]), ""]
    srcs: list = []
    if ed.take is not None and take_report is not None:
        t = ed.take
        srcs = take_sources("\n".join([*(s.body for s in t.sections), *t.watch]), take_report)
        mapping = {cid: i for i, (cid, _, _) in enumerate(srcs, start=1)}
        lines += ["## The Architect's Take", "", f"### {reader(t.title)}", "",
                  f"*{FORMAT_LABELS.get(t.format, 'The Take')} · {reader(t.dek)}*", ""]
        for sec in t.sections:
            if sec.body.strip():
                lines += [f"**{human_dates(sec.heading).strip()}**", "", human_dates(_numbered(sec.body, mapping)), ""]
        if t.watch:
            lines += ["**What to watch**", ""] + [f"- {human_dates(_numbered(w, mapping))}" for w in t.watch if w.strip()] + [""]
    if rest:
        lines += [f"## {'Five' if len(rest) == 5 else len(rest)} {'thing' if len(rest) == 1 else 'things'} that moved", ""]
        for i, s in enumerate(rest, start=1):
            beat = SECTION_LABELS.get(s.section, s.section.replace("_", " ").title())
            lines += [f"**{i}. {s.headline}**", f"*{beat}*", "", s.summary, ""]
            if s.why_it_matters:
                lines += [f"**What it changes:** {s.why_it_matters}", ""]
            tag = " · vendor source, not independently confirmed" if s.vendor_only else (
                " · developing" if s.confidence == "developing" else "")
            if s.sources:
                lines += ["Source: " + " · ".join(f"[{r.origin}]({r.url})" for r in s.sources[:2]) + tag, ""]
    rows = radar_rows(ed)
    if rows:
        lines += ["## Deadline Radar", "", "Dated SAP changes to plan around, soonest first.", ""]
        lines += [_radar_line(r, today) for r in rows] + [""]
    if srcs:
        lines += ["## Sources for the Take", ""]
        for i, (_, text, links) in enumerate(srcs, start=1):
            link = " · ".join(f"[{o}]({u})" for o, u in links[:2])
            lines.append(f"{i}. {text}" + (f" ({link})" if link else ""))
        lines.append("")
    foot = f"*{name}* is curated and signed off by {author}. Public sources only; views are my own."
    lines += ["---", "", foot]
    li = _li_cfg()
    if li.get("signup_url"):
        lines += ["", f"{li.get('signup_offer', 'Get the free checklist')}: {li['signup_url']}"]
    return "\n".join(lines).strip() + "\n"


_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:Georgia,serif;max-width:720px;margin:32px auto;padding:0 16px;color:#17202a;line-height:1.6}}
.how{{font-family:Helvetica,Arial,sans-serif;background:#eef4ff;border:1px solid #c9dcff;padding:12px 16px;border-radius:8px;
font-size:14px;margin-bottom:28px}} h1{{font-family:Helvetica,Arial,sans-serif}} h2{{font-family:Helvetica,Arial,sans-serif;
border-top:1px solid #dfe3e1;padding-top:18px}} a{{color:#0a6cff}}</style></head><body>
<div class="how"><b>How to post:</b> LinkedIn &rarr; Write article &rarr; choose the newsletter. Paste the title and
subtitle from <i>1-tuesday-title.txt</i>, upload <i>1-tuesday-cover.png</i> as the cover, then select everything
<b>below the line</b> on this page (from "{first}" to the end), copy, and paste into the article body.
Publish, and use <i>1-tuesday-share-post.txt</i> as the post text.</div>
<h1>{title}</h1><p><i>{subtitle}</i></p><hr>
{body}
</body></html>"""


def render_linkedin_html(ed: Edition, issue_md: str) -> str:
    import html as h
    body = md.markdown(issue_md, extensions=["extra", "sane_lists"])
    first = "This week's Signal" if not ed.intro else ed.intro[:40]
    return _HTML.format(title=h.escape(ed.title), subtitle=h.escape(ed.description), body=body, first=h.escape(first))


def linkedin_texts(ed: Edition) -> dict:
    """Every ready-to-paste LinkedIn text, with the newsletter link and signup filled in by code."""
    li = _li_cfg()
    url, signup = li.get("newsletter_url", ""), li.get("signup_url", "")
    pack = ed.linkedin or LinkedInPack(share_post=ed.description, story_post="[YOUR STORY: ...]",
                                       story_needs_input=True, carousel_caption=ed.title)
    clean = lambda t: human_dates(reader(t or "")).strip()
    story = clean(pack.story_post)
    caption = clean(pack.carousel_caption)
    if url and url not in story:
        story += f"\n\nThis week's full Take is in the newsletter: {url}"
    if url and url not in caption:
        caption += f"\n\nThe full issue: {url}"
    if signup:
        story += f"\n\n{li.get('signup_offer', 'Free checklist')}: {signup}"
    share = clean(pack.share_post)
    title = f"{ed.title}\n\n{ed.description}\n"
    return {"share": share, "story": story, "caption": caption, "title": title,
            "carousel_title": clean(pack.carousel_title) or "This week in SAP: what changed and what's due",
            "story_needs_input": bool(pack.story_needs_input or "[YOUR STORY" in story.upper())}


def write_linkedin(folder: Path, ed: Edition, issue_md: str) -> Path:
    from .carousel import render_carousel
    from .cover import render_cover
    out = folder / LINKEDIN_DIR
    out.mkdir(parents=True, exist_ok=True)
    t = linkedin_texts(ed)
    (out / "1-tuesday-newsletter.html").write_text(render_linkedin_html(ed, issue_md), encoding="utf-8")
    (out / "1-tuesday-title.txt").write_text(t["title"], encoding="utf-8")
    (out / "1-tuesday-share-post.txt").write_text(t["share"] + "\n", encoding="utf-8")
    (out / "2-thursday-story-post.txt").write_text(t["story"] + "\n", encoding="utf-8")
    (out / "3-saturday-caption.txt").write_text(t["caption"] + "\n", encoding="utf-8")
    pub = get_config().get("publication", {}) or {}
    render_cover(ed, pub, out / "1-tuesday-cover.png")
    render_carousel(ed, pub, t["carousel_title"], radar_rows(ed), out / "3-saturday-carousel.pdf", out / "slides")
    return out


def all_output_text(folder: Path) -> str:
    out = folder / LINKEDIN_DIR
    parts = [(folder / "issue.md").read_text(encoding="utf-8")] if (folder / "issue.md").exists() else []
    parts += [p.read_text(encoding="utf-8") for p in sorted(out.glob("*.txt"))] if out.exists() else []
    return "\n".join(parts)


def write_edition(root: Path, ed: Edition, reports: dict[str, VerificationReport], publication: dict) -> Path:
    folder = root / ed.edition_id
    folder.mkdir(parents=True, exist_ok=True)
    take_report = reports.get("_take")
    issue_md = render_issue_md(ed, take_report)
    banned = find_banned(issue_md + "\n" + "\n".join(str(v) for v in linkedin_texts(ed).values()))
    if banned:
        ed.warnings.insert(0, f"BLOCKING: banned term(s) in the issue or posts: {banned}. Edit before posting.")
    (folder / "issue.md").write_text(issue_md, encoding="utf-8")
    if take_report is not None:
        (folder / "take_evidence.json").write_text(take_report.model_dump_json(indent=2), encoding="utf-8")
    (folder / "evidence").mkdir(exist_ok=True)
    for s in ed.stories:
        (folder / "evidence" / f"{s.candidate_id}.json").write_text(
            reports[s.candidate_id].model_dump_json(indent=2), encoding="utf-8")
    (folder / "radar_new.json").write_text(json.dumps(ed.deadlines_new, indent=2), encoding="utf-8")
    (folder / "quality.json").write_text(ed.quality.model_dump_json(indent=2), encoding="utf-8")
    (folder / "EDITORIAL_WARNINGS.md").write_text(
        "# Editorial warnings\n\n" + ("\n".join(f"- {w}" for w in ed.warnings) if ed.warnings else "- None") + "\n",
        encoding="utf-8")
    (folder / "edition.json").write_text(ed.model_dump_json(indent=2), encoding="utf-8")
    write_linkedin(folder, ed, issue_md)
    return folder


def load_edition(folder: Path) -> Edition:
    return Edition.model_validate_json((folder / "edition.json").read_text(encoding="utf-8"))


def set_status(folder: Path, status: str) -> Edition:
    ed = load_edition(folder)
    ed.status = status
    (folder / "edition.json").write_text(ed.model_dump_json(indent=2), encoding="utf-8")
    return ed
