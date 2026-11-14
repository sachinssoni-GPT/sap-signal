"""CLI for The SAP Signal (weekly, LinkedIn-first).

  python main.py run                      build this week's DRAFT issue (or a no-issue report)
  python main.py run --notify             same, then email + Telegram you the result (walk away)
  python main.py run --force              build even if an issue was already made in the last 5 days
  python main.py scan                     show what the news net catches right now (no AI, no cost)
  python main.py list                     issues and their status
  python main.py radar                    the Deadline Radar as it stands
  python main.py notify draft|no-story|published [--edition ID]
  python main.py approve <id> [--notify]  approve: drafts/<id> -> published/<id>, Radar rows + notes filed
  python main.py reject <id> [--reason ..] [--notify]
  python main.py remind thursday|saturday send that day's LinkedIn post to Telegram (latest approved issue)
  python main.py collect-notes            save your Telegram /take messages and voice notes to notes/
  python main.py control-panel            send a pinnable Telegram message with "build now" / "collect notes" buttons
  python main.py check-sources            test the search/LLM keys and secrets

In GitHub Actions, approve/reject come from the signed buttons in the email/Telegram (via the approval
Worker). Nothing goes anywhere public: you post on LinkedIn yourself.
"""
import argparse
import json
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from sapsignal import db
from sapsignal.config import get_config, path_for, today_iso


def _edition(value: str) -> str:
    import re
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(-([2-9]|[1-9]\d))?", value or ""):
        raise argparse.ArgumentTypeError(f"not an issue id (YYYY-MM-DD): {value!r}")
    date.fromisoformat(value[:10])
    return value


def _gh_output(**kv) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


def _folder(stage: str, edition_id: str) -> Path:
    return path_for(stage) / edition_id


def _recent_issue(day: str, within_days: int = 5):
    """A draft or published issue made in the last few days (the weekly trigger can fire twice)."""
    d0 = date.fromisoformat(day)
    for r in db.list_editions():
        try:
            d = date.fromisoformat(r["edition_date"][:10])
        except ValueError:
            continue
        if r["status"] in ("draft", "published") and timedelta(0) <= d0 - d < timedelta(days=within_days):
            return r
    return None


def _run(args) -> tuple[str, str]:
    db.init_db()
    edition_id = args.edition or today_iso()
    if not args.edition and not args.force:
        recent = _recent_issue(edition_id)
        if recent:
            print(f"Issue {recent['edition_date']} ({recent['status']}) was made in the last few days; not making "
                  "another. Use Regenerate, or --force.")
            _gh_output(status="already_made", edition=recent["edition_date"])
            return "already_made", recent["edition_date"]
    existing = db.get_edition(edition_id)
    if existing and existing["status"] == "published":
        print(f"Issue {edition_id} is already approved; not regenerating.")
        _gh_output(status="already_published", edition=edition_id)
        return "already_published", edition_id
    from sapsignal.flow import WeeklyIssueFlow   # lazy: list/approve work without LLM keys
    flow = WeeklyIssueFlow()
    flow.state.edition_date = edition_id[:10]
    flow.state.edition_id = edition_id
    flow.kickoff()
    s = flow.state
    print(f"\nRun {s.run_id} (issue {edition_id}): {s.status}")
    if s.package_path:
        print(f"Draft issue: {s.package_path}")
    if s.reason:
        print(f"Reason: {s.reason[:400]}")
    if s.diagnostics:
        print("Diagnostics:", *s.diagnostics, sep="\n  - ")
    _gh_output(status=s.status, edition=edition_id, run_id=s.run_id)
    return s.status, edition_id


_BILLING_HINTS = ("insufficient_quota", "credit_balance_exhausted", "exceeded your current quota")


def _explain_fatal(exc: Exception) -> str | None:
    text = f"{type(exc).__name__}: {exc}"
    if any(h in text for h in _BILLING_HINTS):
        return ("SAP Signal run stopped: your OpenAI account has no credits left. Top up, then press Regenerate "
                "or rerun the workflow. Nothing was posted.")
    if "invalid_api_key" in text or "Incorrect API key" in text:
        return "SAP Signal run stopped: the OpenAI API key is invalid. Update the OPENAI_API_KEY secret."
    if "TAVILY" in text and ("401" in text or "432" in text or "usage limit" in text.lower()):
        return "SAP Signal run stopped: Tavily rejected the request (key or monthly credits)."
    return None


def cmd_run(args) -> int:
    from sapsignal.notify.channels import send_telegram
    try:
        status, edition_id = _run(args)
    except Exception as exc:
        import traceback
        tail = traceback.format_exc().strip().splitlines()[-1][:300]
        msg = _explain_fatal(exc)
        if msg or args.notify:
            print(send_telegram(msg or f"SAP Signal run CRASHED: {type(exc).__name__}. {tail}", html=False))
        raise
    if not args.notify:
        return 0
    from sapsignal.notify import messages
    if status == "draft_ready":
        print(*messages.notify_draft(_folder("drafts", edition_id)), sep="\n")
    elif status == "no_story":
        reports = sorted(path_for("reports").glob("*-no-story.json"))
        if reports:
            print(*messages.notify_no_story(json.loads(reports[-1].read_text(encoding="utf-8"))), sep="\n")
    return 0


def cmd_list(_args) -> int:
    db.init_db()
    rows = db.list_editions()
    if not rows:
        print("No issues yet.")
    for r in rows:
        print(f"{r['edition_date']}  {r['status']:<10} {r['stories']} items  |  {r['title']}")
    return 0


def cmd_radar(_args) -> int:
    from sapsignal import deadlines as dl
    today = date.fromisoformat(today_iso())
    rows = dl.upcoming(dl.load(), today)
    for r in rows:
        print(f"{dl.label(r['date']):>12}  {r.get('status', ''):<9} {r['item']}  ({r.get('product', '')})")
    print(f"\n{len(rows)} upcoming row(s) in {dl.path().name}")
    return 0


def _latest(stage: str) -> str | None:
    found = sorted(p.parent.name for p in path_for(stage).glob("*/edition.json"))
    return found[-1] if found else None


def cmd_notify(args) -> int:
    from sapsignal.notify import messages
    if args.kind in ("draft", "published"):
        stage = "drafts" if args.kind == "draft" else "published"
        edition_id = args.edition or _latest(stage)
        folder = _folder(stage, edition_id or "none")
        if not edition_id or not (folder / "edition.json").exists():
            print(f"No {args.kind} issue {edition_id or ''}. Nothing sent.")
            return 1
        results = messages.notify_draft(folder) if args.kind == "draft" else messages.notify_published(folder)
    else:
        reports = sorted(path_for("reports").glob("*-no-story.json"))
        if not reports:
            print("No no-story report found.")
            return 1
        results = messages.notify_no_story(json.loads(reports[-1].read_text(encoding="utf-8")))
    print(*results, sep="\n")
    return 0


def cmd_approve(args) -> int:
    from sapsignal import deadlines as dl
    from sapsignal.editorial.quality_gate import find_banned
    from sapsignal.notes import archive_notes
    from sapsignal.publishing.edition import all_output_text, set_status
    db.init_db()
    src = _folder("drafts", args.edition)
    if not (src / "edition.json").exists():
        print(f"No draft issue {args.edition}.")
        return 1
    banned = find_banned(all_output_text(src))
    if banned and not args.force:
        msg = (f"Not approved: issue {args.edition} contains banned term(s) {banned}. Edit the files in "
               f"content/drafts/{args.edition}/ (or Regenerate), then approve again.")
        print(msg)
        if args.notify:
            from sapsignal.notify.channels import send_telegram
            print(send_telegram(msg, html=False))
        return 2
    ed = set_status(src, "published")
    added = dl.merge(ed.deadlines_new)
    dst = _folder("published", args.edition)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(src), str(dst))
    moved = archive_notes(dst / "notes_used")
    db.decide_edition(args.edition, "published", str(dst))
    print(f"Approved -> {dst}\nDeadline Radar: {added} row(s) added. Notes filed: {moved}.")
    if args.notify:
        from sapsignal.notify.messages import notify_published
        print(*notify_published(dst), sep="\n")
    return 0


def cmd_reject(args) -> int:
    from sapsignal.notify.messages import notify_decision
    from sapsignal.publishing.edition import set_status
    db.init_db()
    src = _folder("drafts", args.edition)
    if not (src / "edition.json").exists():
        print(f"No draft issue {args.edition}.")
        return 1
    set_status(src, "rejected")
    dst = path_for("rejected") / args.edition
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(src), str(dst))
    db.decide_edition(args.edition, "rejected", str(dst), args.reason)
    print(f"Rejected -> {dst}  (your notes are kept for the next run)")
    if args.notify:
        print(*notify_decision(args.edition, "rejected", args.reason), sep="\n")
    return 0


def cmd_remind(args) -> int:
    from sapsignal.notify.messages import remind
    edition_id = args.edition or _latest("published")
    if not edition_id:
        print("No approved issue yet; nothing to remind.")
        return 0
    if not args.edition and date.fromisoformat(today_iso()) - date.fromisoformat(edition_id[:10]) > timedelta(days=7):
        print(f"Latest approved issue {edition_id} is more than a week old; no reminder.")
        return 0
    print(*remind(_folder("published", edition_id), args.day), sep="\n")
    return 0


def cmd_control_panel(_args) -> int:
    from sapsignal.notify.messages import send_control_panel
    print(*send_control_panel(), sep="\n")
    return 0


def cmd_collect_notes(_args) -> int:
    from sapsignal.notes import collect_telegram
    print(*collect_telegram(), sep="\n")
    return 0


def cmd_check_sources(_args) -> int:
    from sapsignal.research.search_client import get_search_client
    bad = 0
    try:
        hits = get_search_client().search("SAP S/4HANA", max_results=2, days=7)
        print(f"[ok] search provider returned {len(hits)} hits")
    except Exception as exc:
        bad += 1
        print(f"[FAIL] search provider: {exc}")
    for key in ("OPENAI_API_KEY", "TAVILY_API_KEY", "APPROVAL_SECRET", "SMTP_USER", "SMTP_PASSWORD",
                "EMAIL_TO", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "BANNED_TERMS"):
        print(f"[{'ok' if os.environ.get(key) else 'missing'}] {key}")
    return 1 if bad else 0


def cmd_scan(args) -> int:
    """Discovery only: what the news net catches right now, clustered into events. No AI, no cost."""
    from sapsignal.research.events import SECTION_LABELS, cluster, read_feeds, section_sources
    cfg = get_config()
    d = cfg.get("discovery", {}) or {}
    diag: list[str] = []
    sources = section_sources(cfg, days=int(d.get("feed_days", 7))) + [(f, "") for f in d.get("rss_feeds", []) or []]
    hits = read_feeds(sources, int(d.get("lookback_hours", 170)), diagnostics=diag)
    events = cluster(hits)
    print(*diag[-6:], sep="\n")
    print(f"\n{len(events)} events from {len(hits)} headlines\n")
    for sec in [*SECTION_LABELS, ""]:
        rows = [e for e in events if (max(e.section_hints, key=e.section_hints.get) if e.section_hints else "") == sec]
        if not rows:
            continue
        print(f"== {SECTION_LABELS.get(sec, 'Unsorted')} ({len(rows)} events)")
        for e in rows[: args.top]:
            print(f"  {len(e.outlets):>2} outlets  {e.title[:100]}")
        print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=lambda a: (db.init_db(), print("DB ready"), 0)[2])
    p = sub.add_parser("run")
    p.add_argument("--edition", type=_edition, help="explicit issue id (used by Regenerate)")
    p.add_argument("--notify", action="store_true", help="email + Telegram me the result when done")
    p.add_argument("--force", action="store_true", help="build even if an issue was made in the last 5 days")
    p.set_defaults(fn=cmd_run)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("radar").set_defaults(fn=cmd_radar)
    p = sub.add_parser("notify"); p.add_argument("kind", choices=["draft", "no-story", "published"])
    p.add_argument("--edition", type=_edition); p.set_defaults(fn=cmd_notify)
    p = sub.add_parser("approve"); p.add_argument("edition", type=_edition)
    p.add_argument("--notify", action="store_true")
    p.add_argument("--force", action="store_true", help="approve even with banned terms (not recommended)")
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("reject"); p.add_argument("edition", type=_edition); p.add_argument("--reason", default="")
    p.add_argument("--notify", action="store_true"); p.set_defaults(fn=cmd_reject)
    p = sub.add_parser("remind"); p.add_argument("day", choices=["thursday", "saturday"])
    p.add_argument("--edition", type=_edition); p.set_defaults(fn=cmd_remind)
    sub.add_parser("collect-notes").set_defaults(fn=cmd_collect_notes)
    sub.add_parser("control-panel").set_defaults(fn=cmd_control_panel)
    sub.add_parser("check-sources").set_defaults(fn=cmd_check_sources)
    p = sub.add_parser("scan"); p.add_argument("--top", type=int, default=15); p.set_defaults(fn=cmd_scan)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
