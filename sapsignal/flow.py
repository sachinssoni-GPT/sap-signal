"""The weekly issue as a CrewAI Flow: deterministic Python control, LLM calls only where needed.

  discover   a week of SAP news (beat queries on Google News + feeds) -> cluster into events
             -> triage keeps what has buyer impact (money, deadline, risk, effort), sorted into 6 beats
  briefing   per story, in parallel: read a readable outlet carrying it -> one call writes its claims
             (exact quotes) + the item -> code checks every quote -> beat-balanced selection
  the take   pick the Signal + a rotating format -> deep verification -> write / red-team / revise,
             from YOUR notes (Telegram /take or notes/) when there are any
  radar      dated changes proposed from the verified claims; code keeps only dates stated in a quote
  linkedin   Tuesday share post, Thursday story post, Saturday carousel caption
  package    the issue as a draft; nothing is posted until you approve
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Optional

from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel, Field

from . import db, deadlines
from .agents import crews
from .config import get_config, path_for, today_iso
from .editorial import briefing as br
from .editorial.evidence_ledger import apply_gate, check_quotes
from .editorial.quality_gate import check_take
from .notes import read_notes
from .publishing.edition import build_edition, write_edition
from .publishing.renderer import write_json
from .research.events import cluster, drop_already_covered, read_feeds, read_telegram, section_sources, triage_rows
from .research.source_registry import canonical_url, registrable_domain
from .schemas import (BEATS, Brief, Candidate, LinkedInPack, QualityReport, StoryBrief, Take, TakePlan,
                      TAKE_FORMATS, VerificationReport)

TIMED_OUT = object()
_BILLING = ("insufficient_quota", "credit_balance_exhausted", "invalid_api_key")


def with_model_fallback(fn, *args, diag: list | None = None, **kwargs):
    """Call an LLM step; if it fails for a reason other than billing/keys, retry once with every role on
    the backup model (config `models.fallback`)."""
    import os
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if any(b in str(exc) for b in _BILLING):
            raise
        backup = (get_config().get("models", {}) or {}).get("fallback", "gpt-4o-mini")
        roles = [r for r in get_config().get("models", {}) if not r.startswith(("temperature", "reasoning",
                                                                                   "request_", "max_", "fallback"))]
        saved = {r: os.environ.get(f"MODEL_{r.upper()}") for r in roles}
        if diag is not None:
            diag.append(f"{getattr(fn, '__name__', 'step')} failed ({type(exc).__name__}); retrying on {backup}")
        try:
            for r in roles:
                os.environ[f"MODEL_{r.upper()}"] = backup
            return fn(*args, **kwargs)
        finally:
            for r, v in saved.items():
                if v is None:
                    os.environ.pop(f"MODEL_{r.upper()}", None)
                else:
                    os.environ[f"MODEL_{r.upper()}"] = v


def edition_cfg() -> dict:
    ed = dict(get_config().get("edition", {}) or {})
    ed.setdefault("target_items", 6)
    ed.setdefault("min_items", 4)
    ed.setdefault("max_items", 7)
    ed.setdefault("reserve_factor", 2.0)
    ed.setdefault("min_significance", 45)
    ed.setdefault("radar_rows", 8)
    ed["per_section"] = ed.get("per_section") or {b: {"min": 0, "max": 2} for b in BEATS}
    return ed


def run_bounded(items, fn, workers: int, timeout_s: float):
    """Run fn(item) with at most `workers` in flight; yield (item, result, seconds) as each finishes.
    A story that exceeds timeout_s is yielded as TIMED_OUT and abandoned (daemon thread)."""
    import queue
    import threading
    import time
    q: "queue.Queue" = queue.Queue()
    pending, running = list(items), {}

    def _work(key, item):
        try:
            q.put((key, fn(item)))
        except BaseException as exc:
            q.put((key, {"status": "processing_error", "diag": [f"worker crashed: {type(exc).__name__}: {exc}"]}))

    while pending or running:
        while pending and len(running) < workers:
            item = pending.pop(0)
            key = id(item)
            running[key] = (item, time.monotonic())
            threading.Thread(target=_work, args=(key, item), daemon=True).start()
        try:
            key, result = q.get(timeout=2)
            if key in running:
                item, t0 = running.pop(key)
                yield item, result, time.monotonic() - t0
        except queue.Empty:
            pass
        now = time.monotonic()
        for key, (item, t0) in list(running.items()):
            if now - t0 > timeout_s:
                running.pop(key)
                yield item, TIMED_OUT, now - t0


def recent_issues(n: int = 3) -> list[dict]:
    """The last few published issues (newest first): their headlines and the Take's format/title."""
    out = []
    for f in sorted(path_for("published").glob("*/edition.json"), reverse=True)[:n]:
        try:
            ed = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        take = ed.get("take") or {}
        out.append({"headlines": [s.get("headline", "") for s in ed.get("stories", [])],
                    "format": take.get("format", ""), "title": take.get("title") or ed.get("title", "")})
    return out


def issue_number() -> int:
    return len(list(path_for("published").glob("*/edition.json"))) + 1


def distinct_owners(domains: list[str]) -> int:
    """How many independent outlets: domains with the same owner (config source_owners) count once."""
    owner = {d: g for g, ds in ((get_config().get("source_owners") or {}).items()) for d in (ds or [])}
    return len({owner.get(d, d) for d in domains})


def take_prefs() -> tuple[list[str], list[str]]:
    tc = (edition_cfg().get("take") or {})
    return [str(t) for t in tc.get("prefer_topics") or []], [str(t).lower() for t in tc.get("avoid_topics") or []]


def avoided(headline: str, avoid: list[str]) -> bool:
    h = (headline or "").lower()
    return any(a and a in h for a in avoid)


def _same_event(a: str, b: str) -> bool:
    from .research.events import overlap, words
    wa, wb = words(a), words(b)
    return overlap(wa, wb) >= 0.4 and len(wa & wb) >= 3


class IssueState(BaseModel):
    run_id: str = ""
    edition_date: str = ""
    edition_id: str = ""
    search_blocked: str = ""
    notes: str = ""
    candidates: list[Candidate] = Field(default_factory=list)
    publishers: dict[str, str] = Field(default_factory=dict)
    pool_ids: list[str] = Field(default_factory=list)
    verified: dict[str, VerificationReport] = Field(default_factory=dict)
    briefs: dict[str, StoryBrief] = Field(default_factory=dict)
    confidence: dict[str, str] = Field(default_factory=dict)
    totals: dict[str, float] = Field(default_factory=dict)
    gate_failures: dict[str, list[str]] = Field(default_factory=dict)
    selected_ids: list[str] = Field(default_factory=list)
    plan: Optional[TakePlan] = None
    take: Optional[Take] = None
    take_report: Optional[VerificationReport] = None
    take_ids: list[str] = Field(default_factory=list)
    radar_new: list[dict] = Field(default_factory=list)
    linkedin: Optional[LinkedInPack] = None
    quality: Optional[QualityReport] = None
    status: str = "started"
    reason: str = ""
    diagnostics: list[str] = []
    package_path: str = ""


class WeeklyIssueFlow(Flow[IssueState]):

    # ------------------------------------------------------------ 1. discover
    @start()
    def discover(self):
        cfg = get_config()
        s = self.state
        s.edition_date = s.edition_date or today_iso()
        s.edition_id = s.edition_id or s.edition_date
        s.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        s.notes = read_notes()
        if s.notes:
            s.diagnostics.append(f"author notes found ({len(s.notes.split())} words): the Take follows them")
        db.init_db()
        db.start_run(s.run_id)
        d = cfg.get("discovery", {}) or {}
        lookback = int(d.get("lookback_hours", 170))
        sources = section_sources(cfg, days=int(d.get("feed_days", 7)))
        sources += [(f, "") for f in d.get("rss_feeds", []) or []]
        hits = read_feeds(sources, lookback, diagnostics=s.diagnostics)
        hits += read_telegram(d.get("telegram_channels", []) or [], lookback, diagnostics=s.diagnostics)
        used = db.selected_canonical_urls()
        hits = [h for h in hits if canonical_url(h.url) not in used]
        events = cluster(hits)
        recent = [h for e in recent_issues(2) for h in e["headlines"]]
        before = len(events)
        events = drop_already_covered(events, recent)
        s.diagnostics.append(f"clustered into {before} events; {before - len(events)} already covered recently")
        if not events:
            s.diagnostics.append("no events after clustering")
            return
        limit = int(d.get("max_events_to_triage", 200))
        result = with_model_fallback(crews.run_triage_events, triage_rows(events, limit),
                                     int(d.get("max_candidates", 30)), diag=s.diagnostics)
        by_id = {e.id: e for e in events}
        cands: list[Candidate] = []
        for p in result.picks:
            ev = by_id.get(p.event_id.strip())
            if ev is None or any(c.id == ev.id for c in cands):
                continue
            pubs = {h.url: h.publisher for h in ev.hits if h.via != "telegram"}
            s.publishers.update(pubs)
            order = br.reading_order(ev.urls(), pubs)
            if not order:
                continue
            first = order[0]
            cands.append(Candidate(id=ev.id, title=p.title or ev.title, url=first, related_urls=order[1:8],
                                   relevance=p.significance, section=p.section, summary=p.why,
                                   outlets=distinct_owners(ev.outlets), outlet_names=ev.outlets[:10],
                                   source_name=pubs.get(first, registrable_domain(first)),
                                   published=ev.latest or None, topic=p.section))
        cands = self._dedupe_picks(cands)
        floor = int(edition_cfg()["min_significance"])
        s.candidates = sorted([c for c in cands if c.relevance >= floor], key=lambda c: c.relevance, reverse=True)
        s.diagnostics.append(f"triage kept {len(cands)} stories; {len(s.candidates)} at {floor}+ buyer impact "
                             + str({b: sum(c.section == b for c in s.candidates) for b in BEATS}))
        if not s.candidates:
            best = max((c.relevance for c in cands), default=0)
            s.diagnostics.append(f"early stop: no story scored {floor}+ at triage (best {best})")
            return
        ed = edition_cfg()
        pool_n = math.ceil(int(ed["target_items"]) * float(ed["reserve_factor"]))
        s.pool_ids = br.balanced([(c.id, c.section, c.relevance) for c in s.candidates], pool_n, ed["per_section"])
        db.save_candidates(s.run_id, s.candidates, canonical_url)

    def _dedupe_picks(self, cands: list[Candidate]) -> list[Candidate]:
        from .research.events import overlap, words
        kept: list[Candidate] = []
        for c in sorted(cands, key=lambda c: (c.relevance, c.outlets), reverse=True):
            w = words(c.title)
            twin = next((k for k in kept if overlap(w, words(k.title)) >= 0.6 and len(w & words(k.title)) >= 3), None)
            if twin is None:
                kept.append(c)
                continue
            twin.related_urls += [u for u in [c.url, *c.related_urls] if u not in twin.related_urls][:6]
            twin.outlet_names += [o for o in c.outlet_names if o not in twin.outlet_names]
            twin.outlets = distinct_owners(twin.outlet_names)
            self.state.diagnostics.append(f"{c.id}: same event as {twin.id}; merged")
        return kept

    # ------------------------------------------------------------ 2. briefing
    @listen(discover)
    def build_briefing(self):
        s = self.state
        if not s.pool_ids:
            return
        v = get_config().get("verification", {}) or {}
        workers = max(1, int(v.get("parallel", 4)))
        by_id = {c.id: c for c in s.candidates}
        print(f"Reading and writing {len(s.pool_ids)} stories, {workers} at a time...", flush=True)
        self._brief_wave([by_id[i] for i in s.pool_ids], workers, float(v.get("story_timeout_s", 240)))
        ed = edition_cfg()
        target = int(ed["target_items"])
        if len(s.verified) < target:
            rest = [c for c in s.candidates if c.id not in s.pool_ids][: (target - len(s.verified)) * 2]
            if rest:
                s.diagnostics.append(f"second wave: {len(rest)} more stories")
                s.pool_ids += [c.id for c in rest]
                self._brief_wave(rest, workers, float(v.get("story_timeout_s", 240)))
        self._select(target, ed)

    def _brief_wave(self, stories, workers, timeout_s) -> None:
        done = 0
        for cand, res, secs in run_bounded(stories, self._brief_one, workers, timeout_s):
            done += 1
            if res is TIMED_OUT:
                res = {"status": "timeout", "diag": [f"{cand.id}: timed out after {int(secs)}s"]}
            self.state.diagnostics += res.get("diag", [])
            if res.get("report") is not None:
                self.state.verified[cand.id] = res["report"]
                self.state.briefs[cand.id] = res["brief"]
                self.state.confidence[cand.id] = res["confidence"]
                self.state.totals[cand.id] = float(cand.relevance) + (3 if res["confidence"] == "high" else 0)
                db.save_verification(self.state.run_id, res["report"])
            else:
                self.state.gate_failures[cand.id] = res.get("diag", [])
            db.set_candidate_status(self.state.run_id, cand.id, res["status"])
            print(f"  [{done}/{len(stories)}] {cand.id} {res['status']} ({int(secs)}s)  {cand.title[:64]}", flush=True)

    def _brief_one(self, cand: Candidate) -> dict:
        """Worker thread: network + one or two LLM calls. No shared-state writes."""
        out = {"status": "", "diag": [], "report": None, "brief": None, "confidence": ""}
        found = br.find_readable(cand, self.state.publishers)
        if found is None:
            alt = crews._readable_alternative(cand)
            if alt is None:
                out.update(status="unreadable", diag=[f"{cand.id}: no readable copy among {cand.outlets} outlet(s)"])
                return out
            found = alt
        url, page = found
        final = page.final_url or url
        if not br.authentic(final, cand.outlet_names):
            out.update(status="failed_authenticity_check",
                       diag=[f"{cand.id}: no recognised outlet carries it ({registrable_domain(final)})"])
            return out
        cand_view = cand.model_copy(update={"source_name": registrable_domain(final)})
        also = [o for o in cand.outlet_names if o != registrable_domain(final)]
        feedback = ""
        try:
            for _ in range(2):
                brief = crews.run_story_brief(cand_view, page.text[:9000], final, also, feedback)
                report, dropped = br.light_report(cand_view, url, page, brief)
                problems = br.brief_problems(brief, report, dropped)
                if not problems:
                    break
                feedback = "; ".join(problems)
            if not report.claims:
                out.update(status="no_verifiable_claims", diag=[f"{cand.id}: no quote matched the article"])
                return out
            if problems:
                brief = br.fallback_brief(brief, report)
                out["diag"].append(f"{cand.id}: item rebuilt from verified claims ({feedback[:120]})")
        except Exception as exc:
            out.update(status="processing_error", diag=[f"{cand.id}: brief failed: {type(exc).__name__}: {exc}"[:300]])
            return out
        conf = br.confidence_for(final, cand.outlets)
        out.update(status="verified" if conf == "high" else "verified_developing", report=report,
                   brief=brief.model_copy(update={"section": cand.section or brief.section}), confidence=conf)
        return out

    def _select(self, target: int, ed: dict) -> None:
        s = self.state
        by_id = {c.id: c for c in s.candidates}
        kept: list[str] = []
        for cid in sorted(s.totals, key=s.totals.get, reverse=True):
            if any(_same_event(s.briefs[cid].headline, s.briefs[k].headline) for k in kept):
                s.diagnostics.append(f"{cid}: duplicate of an item already in the issue; dropped")
                continue
            kept.append(cid)
        scored = [(cid, by_id[cid].section, s.totals[cid]) for cid in kept]
        s.selected_ids = br.balanced(scored, min(target, int(ed["max_items"])), ed["per_section"])
        if s.selected_ids and len(s.selected_ids) < int(ed["min_items"]):
            s.diagnostics.append(f"thin issue: only {len(s.selected_ids)} items could be read and checked")

    @router(build_briefing)
    def decide(self):
        return "write" if self.state.selected_ids else "no_story"

    # ------------------------------------------------------------ 3. the Architect's Take
    @listen("write")
    def write_take(self):
        s = self.state
        cfg = get_config()
        by_id = {c.id: c for c in s.candidates}
        tc = (edition_cfg().get("take") or {})
        recent = recent_issues(int(tc.get("avoid_recent_formats", 2)))
        recent_formats = [e["format"] for e in recent if e["format"]]
        prefer, avoid = take_prefs()
        eligible = [cid for cid in s.selected_ids if s.notes or not avoided(s.briefs[cid].headline, avoid)]
        if not eligible:
            s.diagnostics.append("take: every story this week is on an avoided topic; no Take")
            self._after_take()
            return
        items = [{"candidate_id": cid, "beat": by_id[cid].section, "headline": s.briefs[cid].headline,
                  "summary": s.briefs[cid].summary, "outlets": by_id[cid].outlets} for cid in eligible]
        try:
            plan = with_model_fallback(crews.run_plan_take, items, recent_formats, [e["title"] for e in recent],
                                       s.notes, prefer, diag=s.diagnostics)
        except Exception as exc:
            s.diagnostics.append(f"take plan failed: {type(exc).__name__}: {exc}"[:300])
            self._after_take()
            return
        if plan.story_id not in eligible:
            s.diagnostics.append(f"take: planner picked {plan.story_id} (not eligible); using {eligible[0]}")
            plan.story_id = eligible[0]
        plan.related_ids = [r for r in plan.related_ids if r in s.selected_ids and r != plan.story_id][:2]
        if plan.format in recent_formats:
            fresh = [f for f in TAKE_FORMATS if f not in recent_formats and (f != "connecting_dots" or plan.related_ids)]
            if fresh:
                s.diagnostics.append(f"take: {plan.format} was used recently; switched to {fresh[0]}")
                plan.format = fresh[0]
        if plan.format != "connecting_dots":
            plan.related_ids = []
        s.plan = plan
        # the Signal leads the issue
        s.selected_ids = [plan.story_id] + [i for i in s.selected_ids if i != plan.story_id]
        lead = by_id[plan.story_id]
        report = self._deep_report(lead)
        merged, _ = br.merge_reports([report] + [s.verified[r] for r in plan.related_ids])
        opening = crews.OPENINGS[int(hashlib.md5(s.edition_id.encode()).hexdigest(), 16) % len(crews.OPENINGS)]
        feedback = ""
        for _ in range(int(cfg.get("quality", {}).get("max_revisions", 1)) + 1):
            try:
                take = with_model_fallback(crews.run_take, plan, s.briefs[plan.story_id].headline, merged,
                                           opening, s.notes, feedback, diag=s.diagnostics)
            except Exception as exc:
                s.diagnostics.append(f"take failed: {type(exc).__name__}: {exc}"[:300])
                break
            q = check_take(take, merged, cfg)
            s.take, s.quality = take, q
            if q.verdict != "reject":
                break
            feedback = q.feedback + ". Cite only the claim ids listed. Never use the banned terms."
        if s.take is not None and s.quality and s.quality.verdict == "reject":
            s.diagnostics.append("take dropped: it kept failing a blocking check (" + s.quality.feedback[:160] + ")")
            s.take = None
        if s.take is not None:
            s.take_report, s.take_ids = merged, [plan.story_id, *plan.related_ids]
        self._after_take()

    def _deep_report(self, lead: Candidate) -> VerificationReport:
        """The Signal gets the full agentic check (search + corroboration). If that fails or comes back
        weaker, the quote-checked briefing ledger is used: never nothing."""
        s = self.state
        light = s.verified[lead.id]
        if not (get_config().get("verification", {}) or {}).get("deep_for_big_read", True):
            return light
        try:
            src = light.evidence[0].resolved_url or light.evidence[0].url if light.evidence else lead.url
            deep = crews.run_verification(lead.model_copy(update={"url": src}))
            deep = check_quotes(deep)
            gate = apply_gate(deep, 1, {})
            supported = [v for v in deep.verdicts if v.verdict == "supported"]
            if gate.passed and len(supported) >= len(light.claims):
                deep.verdicts = supported
                ok = {v.claim_id for v in deep.verdicts}
                deep.claims = [c for c in deep.claims if c.id in ok]
                deep.evidence = [e for e in deep.evidence if e.claim_id in ok and e.quote_verified]
                s.diagnostics.append(f"{lead.id}: deep verification used for the Take ({len(deep.claims)} claims)")
                return deep
        except Exception as exc:
            s.diagnostics.append(f"{lead.id}: deep verification skipped ({type(exc).__name__})")
        return light

    def _after_take(self) -> None:
        self._radar()
        self._linkedin()

    def _radar(self) -> None:
        """Dated changes from this week's verified claims -> proposed Radar rows (dates checked in code)."""
        s = self.state
        reports = {cid: s.verified[cid] for cid in s.selected_ids}
        claims = {}
        for cid, rep in reports.items():
            quotes = {e.claim_id: e.quote for e in rep.evidence if e.quote_verified}
            rows = [(c.id, c.text, quotes[c.id]) for c in rep.claims if c.id in quotes
                    and re.search(r"\b20\d\d\b", quotes[c.id])]
            if rows:
                claims[cid] = rows
        if not claims:
            return
        try:
            props = with_model_fallback(crews.run_deadlines, claims, diag=s.diagnostics)
        except Exception as exc:
            s.diagnostics.append(f"radar extraction failed: {type(exc).__name__}"[:200])
            return
        kept, notes = deadlines.verify(props.rows, reports, date.fromisoformat(s.edition_date), deadlines.load())
        s.radar_new = kept
        s.diagnostics += notes
        if kept:
            s.diagnostics.append(f"radar: {len(kept)} new dated row(s) proposed")

    def _linkedin(self) -> None:
        s = self.state
        heads = [s.briefs[i].headline for i in s.selected_ids]
        radar = [f"{deadlines.label(r['date'])}: {r['item']} ({r.get('product', '')})"
                 for r in deadlines.upcoming(deadlines.load() + s.radar_new, date.fromisoformat(s.edition_date),
                                             int(edition_cfg()["radar_rows"]))]
        url = (get_config().get("linkedin", {}) or {}).get("newsletter_url", "")
        try:
            s.linkedin = with_model_fallback(crews.run_linkedin, s.take, heads, s.plan.intro if s.plan else "",
                                             radar, url, diag=s.diagnostics)
        except Exception as exc:
            s.diagnostics.append(f"linkedin pack failed: {type(exc).__name__}: {exc}"[:300])
            lead = s.take.social_post if s.take else heads[0]
            s.linkedin = LinkedInPack(share_post=lead, story_post="[YOUR STORY: write this week's story post]",
                                      story_needs_input=True, carousel_caption=heads[0])

    @router(write_take)
    def gate_result(self):
        return "package" if self.state.selected_ids else "no_story"

    # ------------------------------------------------------------ terminal outcomes
    @listen("package")
    def build_package(self):
        s = self.state
        briefs = [Brief(candidate_id=cid, headline=s.briefs[cid].headline, summary=s.briefs[cid].summary,
                        why_it_matters=s.briefs[cid].why_it_matters) for cid in s.selected_ids]
        edition = build_edition(
            edition_date=s.edition_date, edition_id=s.edition_id, run_id=s.run_id, ordered_ids=s.selected_ids,
            candidates={c.id: c for c in s.candidates}, reports=s.verified, totals=s.totals,
            confidence=s.confidence, briefs=briefs, take=s.take, take_ids=s.take_ids,
            take_from_notes=bool(s.notes and s.take), intro=s.plan.intro if s.plan else "",
            linkedin=s.linkedin, radar_new=s.radar_new, issue_no=issue_number(),
            quality=s.quality or QualityReport(verdict="pass"))
        edition.warnings = [d for d in s.diagnostics if d.startswith(("thin issue", "take dropped"))] + edition.warnings
        reports = dict(s.verified)
        if s.take_report is not None:
            reports["_take"] = s.take_report
        folder = write_edition(path_for("drafts"), edition, reports, get_config().get("publication", {}))
        s.package_path = str(folder)
        s.status = "draft_ready"
        s.reason = (f"Draft issue with {len(s.selected_ids)} items"
                    + (f" + the Take ({s.take.format.replace('_', ' ')})" if s.take else ", no Take")
                    + (f"; {len(edition.warnings)} warning(s)" if edition.warnings else ""))
        for cid in s.selected_ids:
            db.set_candidate_status(s.run_id, cid, "selected")
        db.save_edition(s.edition_id, s.run_id, edition.title, "draft", str(folder), len(s.selected_ids))
        db.finish_run(s.run_id, s.status, "awaiting human approval")
        self._report("edition")

    @listen("no_story")
    def handle_no_story(self):
        s = self.state
        s.status = "search_unavailable" if s.search_blocked else "no_story"
        s.reason = ("No story could be read and checked. "
                    f"gate_failures={dict(list(s.gate_failures.items())[:8])}")
        db.finish_run(s.run_id, s.status, s.reason[:500])
        self._report("no-story")

    def _report(self, kind: str) -> None:
        s = self.state
        payload = {
            "run_id": s.run_id, "edition_date": s.edition_date, "edition_id": s.edition_id, "status": s.status,
            "reason": s.reason, "package": s.package_path, "diagnostics": s.diagnostics,
            "gate_failures": s.gate_failures, "evidence_confidence_by_candidate": s.confidence,
            "ranking_totals": s.totals, "selected_ids": s.selected_ids,
            "take": s.take.model_dump() if s.take else None, "plan": s.plan.model_dump() if s.plan else None,
            "radar_new": s.radar_new, "candidates": [c.model_dump() for c in s.candidates],
        }
        write_json(path_for("reports") / f"{s.run_id}-{kind}.json", payload)
