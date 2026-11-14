"""What gets sent, and when.

  draft ready  -> email: the whole issue + the three LinkedIn posts + Approve / Reject / Regenerate
                  telegram: headlines, Radar additions, the same buttons
  approved     -> telegram: the Tuesday kit (article page, cover, title, share post), one message each
                  email: the same, with every file attached
  thursday     -> telegram: the story post (reminder)
  saturday     -> telegram: the carousel PDF + caption (reminder)
  no issue     -> email + telegram: why (gate failures, diagnostics)
"""
from __future__ import annotations

import html
import os
import time
from pathlib import Path

import markdown as md

from .. import deadlines as dl
from ..config import get_config
from ..publishing.edition import LINKEDIN_DIR, linkedin_texts, load_edition
from .channels import send_email, send_telegram, send_telegram_document, send_telegram_photo
from .signing import decision_link

_CSS = ("body{font-family:Georgia,serif;max-width:680px;margin:auto;color:#17202a;line-height:1.55}"
        "h1,h2,h3{font-family:Helvetica,Arial,sans-serif}a{color:#0a6cff}"
        ".bar{background:#eef4ff;border:1px solid #c9dcff;padding:16px;border-radius:8px;margin:16px 0}"
        ".btn{display:inline-block;padding:10px 18px;margin:4px 8px 4px 0;border-radius:6px;color:#fff!important;"
        "text-decoration:none;font-family:Helvetica,Arial,sans-serif;font-weight:bold}"
        ".ok{background:#1f7a3a}.no{background:#a62b2b}.re{background:#555}"
        "pre{white-space:pre-wrap;background:#f6f6f6;padding:12px;border-radius:6px;font-family:inherit}"
        ".warn{color:#8a5a00;font-size:14px}")


def _pub() -> dict:
    return get_config().get("publication", {}) or {}


def _repo_link(path: str) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repo}/blob/main/{path}" if repo else ""


def _links(edition_id: str) -> dict[str, str]:
    a = get_config().get("approval", {}) or {}
    url, ttl = a.get("worker_url", ""), int(a.get("link_ttl_hours", 72))
    if not url or "YOUR-SUBDOMAIN" in url:
        raise RuntimeError("Set approval.worker_url in config.yaml to your deployed approval Worker")
    return {act: decision_link(url, act, edition_id, ttl) for act in ("approve", "reject", "regenerate")}


def _blocking(ed) -> list[str]:
    out = [f"{c.name}: {c.detail}" for c in ed.quality.checks if not c.passed and c.severity == "block"]
    return out + [w for w in ed.warnings if w.startswith("BLOCKING")]


# ------------------------------------------------------------------ draft ready
def notify_draft(folder: Path) -> list[str]:
    ed = load_edition(folder)
    links = _links(ed.edition_id)
    name = _pub().get("name", "Weekly issue")
    issue_html = md.markdown((folder / "issue.md").read_text(encoding="utf-8"), extensions=["extra", "sane_lists"])
    t = linkedin_texts(ed)
    pre = lambda x: f"<pre>{html.escape(x)}</pre>"
    blocking = _blocking(ed)
    block_html = ("<div style='background:#fde8e8;border:2px solid #a62b2b;padding:14px;border-radius:8px'>"
                  "<b>BLOCKING ISSUES. Do not approve as-is: edit the files or press Regenerate.</b><ul>"
                  + "".join(f"<li>{html.escape(b)}</li>" for b in blocking) + "</ul></div>") if blocking else ""
    warn = "".join(f"<li>{html.escape(w)}</li>" for w in ed.warnings[:15] if not w.startswith("BLOCKING"))
    radar = "".join(f"<li><b>{dl.label(r['date'])}</b> · {html.escape(r['item'])} · {html.escape(r.get('product', ''))} "
                    f"(<a href='{html.escape(r.get('source', ''))}'>source</a>)</li>" for r in ed.deadlines_new)
    buttons = (f'<a class="btn ok" href="{links["approve"]}">Approve</a>'
               f'<a class="btn no" href="{links["reject"]}">Reject</a>'
               f'<a class="btn re" href="{links["regenerate"]}">Regenerate</a>')
    notes_line = ("<p><b>The Take was written from your notes.</b></p>" if ed.take_from_notes else
                  "<p class='warn'>No notes from you this week: the Take is an AI draft in your voice. Read it as "
                  "your own before approving.</p>")
    story_flag = ("<p class='warn'><b>The Thursday post has a [YOUR STORY: ...] gap</b> for you to fill before "
                  "posting.</p>" if t["story_needs_input"] else "")
    body = f"""<html><head><style>{_CSS}</style></head><body>
<p style="font-family:Helvetica,Arial,sans-serif;color:#666">{html.escape(name)} · DRAFT · issue {ed.issue_no} · {ed.edition_id}</p>
<div class="bar">{buttons}<br><small>Nothing is posted until you approve (and you post on LinkedIn yourself).
Links expire in {get_config().get('approval', {}).get('link_ttl_hours', 72)}h.</small></div>
{block_html}{notes_line}
<h1>{html.escape(ed.title)}</h1><p><i>{html.escape(ed.description)}</i></p>
{issue_html}
<hr><h2>New Deadline Radar rows (added on approval)</h2>{f'<ul>{radar}</ul>' if radar else '<p>None this week.</p>'}
<hr><h2>Your LinkedIn posts</h2>
<h3>Tuesday · with the newsletter</h3>{pre(t['share'])}
<h3>Thursday · story post</h3>{story_flag}{pre(t['story'])}
<h3>Saturday · carousel caption</h3>{pre(t['caption'])}
{f'<hr><h3>Editorial warnings</h3><ul class="warn">{warn}</ul>' if warn else ''}
<div class="bar">{buttons}</div></body></html>"""
    text = (f"{name} draft {ed.edition_id}: {ed.title}\n\n"
            + "\n".join(f"{s.rank}. {s.headline}" for s in ed.stories)
            + f"\n\nApprove: {links['approve']}\nReject: {links['reject']}\nRegenerate: {links['regenerate']}\n")
    li = folder / LINKEDIN_DIR
    results = [send_email(f"[DRAFT] {name} · issue {ed.issue_no} · {ed.title}", body, text,
                          attachments=[li / "1-tuesday-cover.png", li / "3-saturday-carousel.pdf"])]
    tg = (("<b>BLOCKING ISSUES, do not approve as-is:</b>\n" + "\n".join(html.escape(b) for b in blocking) + "\n\n")
          if blocking else "")
    tg += (f"<b>Draft ready · issue {ed.issue_no}</b>\n\n<b>The Take:</b> {html.escape(ed.title)}"
           + (" <i>(from your notes)</i>" if ed.take_from_notes else " <i>(AI draft, no notes this week)</i>") + "\n\n"
           + "\n".join(f"{'Signal' if s.rank == 1 else s.rank - 1}. {html.escape(s.headline)}"
                       + (" <i>(vendor source)</i>" if s.vendor_only else "") for s in ed.stories)
           + (f"\n\nRadar: {len(ed.deadlines_new)} new dated row(s)" if ed.deadlines_new else "")
           + ("\nThursday post needs your story." if t["story_needs_input"] else "")
           + (f"\n{len(ed.warnings)} warning(s)." if ed.warnings else "") + "\n\nFull draft is in your email.")
    rows = [[("Approve", links["approve"])], [("Reject", links["reject"]), ("Regenerate", links["regenerate"])]]
    gh = _repo_link(f"content/drafts/{ed.edition_id}/issue.md")
    if gh:
        rows.append([("Read draft on GitHub", gh)])
    results.append(send_telegram(tg, rows))
    return results


# ------------------------------------------------------------------ approved: the Tuesday kit
def notify_published(folder: Path) -> list[str]:
    ed = load_edition(folder)
    li = folder / LINKEDIN_DIR
    t = linkedin_texts(ed)
    name = _pub().get("name", "Weekly issue")
    results = [send_email(
        f"[APPROVED] {name} · issue {ed.issue_no} · your LinkedIn kit",
        f"""<html><head><style>{_CSS}</style></head><body><h2>Approved: {html.escape(ed.title)}</h2>
<p><b>Tuesday:</b> open <i>1-tuesday-newsletter.html</i> (attached) in a browser and follow the box at the top.
Cover image and carousel are attached too.</p>
<h3>Title + subtitle</h3><pre>{html.escape(t['title'])}</pre><h3>Tuesday · share post</h3><pre>{html.escape(t['share'])}</pre>
<h3>Thursday · story post</h3><pre>{html.escape(t['story'])}</pre><h3>Saturday · caption</h3><pre>{html.escape(t['caption'])}</pre>
</body></html>""",
        f"Approved: {ed.title}\n\nTITLE:\n{t['title']}\nSHARE POST:\n{t['share']}\n\nSTORY POST:\n{t['story']}\n\n"
        f"CAPTION:\n{t['caption']}",
        attachments=[li / "1-tuesday-newsletter.html", li / "1-tuesday-cover.png", li / "3-saturday-carousel.pdf"])]
    results.append(send_telegram(f"<b>Approved · issue {ed.issue_no}</b> · {html.escape(ed.title)}\n\n"
                                 "Your Tuesday kit is below, one message per piece. Thursday's post and Saturday's "
                                 "carousel will come as reminders on the day."))
    results.append(send_telegram_document(li / "1-tuesday-newsletter.html",
                                          "The article: open on your laptop, copy everything below the line, paste "
                                          "into LinkedIn's article editor"))
    results.append(send_telegram_photo(li / "1-tuesday-cover.png", "Cover image for the edition"))
    results.append(send_telegram("<b>Title + subtitle</b>"))
    results.append(send_telegram(t["title"], html=False))
    results.append(send_telegram("<b>Share post</b> (goes with the edition)"))
    results.append(send_telegram(t["share"], html=False))
    return results


def remind(folder: Path, day: str) -> list[str]:
    """Thursday: the story post. Saturday: the carousel and its caption."""
    ed = load_edition(folder)
    li = folder / LINKEDIN_DIR
    t = linkedin_texts(ed)
    if day == "thursday":
        head = "<b>Thursday post</b> · issue " + str(ed.issue_no)
        if t["story_needs_input"]:
            head += "\nIt has a [YOUR STORY: ...] gap: fill it with a real moment from your career before posting."
        return [send_telegram(head), send_telegram(t["story"], html=False)]
    if day == "saturday":
        return [send_telegram_document(li / "3-saturday-carousel.pdf",
                                       "Saturday carousel: on LinkedIn, Start a post > Add a document > this PDF. "
                                       "Give the document the carousel's title."),
                send_telegram("<b>Caption</b>"), send_telegram(t["caption"], html=False)]
    return [f"unknown reminder day: {day}"]


def notify_decision(edition_id: str, decision: str, reason: str = "") -> list[str]:
    msg = f"Issue {edition_id}: {decision}." + (f" Reason: {reason}" if reason else "")
    return [send_telegram(html.escape(msg))]


# ------------------------------------------------------------------ no issue
def notify_no_story(report: dict) -> list[str]:
    name = _pub().get("name", "Weekly issue")
    fails = report.get("gate_failures") or {}
    diag = report.get("diagnostics") or []
    lines = [f"{cid}: {'; '.join(v)[:220]}" for cid, v in list(fails.items())[:8]]
    text = (f"No issue this week ({report.get('edition_date')}). No story could be read and checked.\n\n"
            f"Scores: {report.get('ranking_totals') or 'none'}\n\nFailures:\n"
            + ("\n".join(lines) or "none") + "\n\nDiagnostics:\n" + "\n".join(d[:200] for d in diag[:12]))
    return [send_email(f"[NO ISSUE] {name} · {report.get('edition_date')}",
                       f"<html><body><pre>{html.escape(text)}</pre></body></html>", text),
            send_telegram(html.escape(text[:3500]))]


# ------------------------------------------------------------------ control panel (pin it in Telegram)
PANEL_DATE = "2000-01-01"     # long-lived panel links are not tied to an issue


def send_control_panel(days: int = 365) -> list[str]:
    """A message with signed buttons to run the pipeline ad hoc. Pin it in the chat; it works for `days`."""
    a = get_config().get("approval", {}) or {}
    url = a.get("worker_url", "")
    if not url or "YOUR-SUBDOMAIN" in url:
        raise RuntimeError("Set approval.worker_url in config.yaml to your deployed approval Worker")
    run = decision_link(url, "run", PANEL_DATE, days * 24)
    notes = decision_link(url, "notes", PANEL_DATE, days * 24)
    text = ("<b>SAP Signal control panel</b>\n\n"
            "<b>Build a new draft now</b>: runs the weekly pipeline immediately (replaces an unapproved draft "
            "from today; never touches an approved issue).\n"
            "<b>Collect my notes now</b>: saves your /take messages and voice notes right away instead of "
            "waiting up to 4 hours.\n\n"
            f"Pin this message. The buttons work until {time.strftime('%d %b %Y', time.gmtime(time.time() + days * 86400))}; "
            "run <code>python main.py control-panel</code> again for fresh ones.")
    return [send_telegram(text, [[("Build a new draft now", run)], [("Collect my notes now", notes)]])]
