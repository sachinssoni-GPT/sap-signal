"""SQLite editorial history: metadata, evidence excerpts, review decisions, predictions.
Full source page text is deliberately NOT stored."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import path_for

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS candidates(
  run_id TEXT, cand_id TEXT, title TEXT, url TEXT, canonical_url TEXT, published TEXT,
  topic TEXT, relevance INTEGER, status TEXT, PRIMARY KEY(run_id, cand_id));
CREATE TABLE IF NOT EXISTS claims(
  run_id TEXT, cand_id TEXT, claim_id TEXT, text TEXT, central INTEGER, verdict TEXT,
  PRIMARY KEY(run_id, cand_id, claim_id));
CREATE TABLE IF NOT EXISTS evidence(
  run_id TEXT, cand_id TEXT, claim_id TEXT, url TEXT, quote TEXT, origin TEXT, stance TEXT,
  source_tier TEXT, retrieved_at TEXT, quote_verified INTEGER);
CREATE TABLE IF NOT EXISTS rankings(
  run_id TEXT, cand_id TEXT, total REAL, detail_json TEXT, PRIMARY KEY(run_id, cand_id));
CREATE TABLE IF NOT EXISTS articles(
  slug TEXT PRIMARY KEY, run_id TEXT, title TEXT, status TEXT, path TEXT,
  quality_verdict TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS reviews(
  slug TEXT, decision TEXT, reason TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS editions(
  edition_date TEXT PRIMARY KEY, run_id TEXT, title TEXT, status TEXT, path TEXT, stories INTEGER,
  created_at TEXT, decided_at TEXT, decision_reason TEXT);
CREATE TABLE IF NOT EXISTS triggers(
  day TEXT, kind TEXT, at TEXT, PRIMARY KEY(day, kind));
CREATE TABLE IF NOT EXISTS predictions(
  slug TEXT, statement TEXT, horizon_date TEXT, confidence REAL, falsifiers_json TEXT,
  outcome TEXT, scored_at TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(path_for("db"))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


def start_run(run_id: str) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?)", (run_id, now(), None, "running", ""))


def finish_run(run_id: str, status: str, reason: str = "") -> None:
    with connect() as c:
        c.execute("UPDATE runs SET finished_at=?, status=?, reason=? WHERE run_id=?",
                  (now(), status, reason, run_id))


def save_candidates(run_id: str, cands, canonical) -> None:
    with connect() as c:
        for x in cands:
            c.execute("INSERT OR REPLACE INTO candidates VALUES(?,?,?,?,?,?,?,?,?)",
                      (run_id, x.id, x.title, x.url, canonical(x.url), x.published, x.topic,
                       x.relevance, "discovered"))


def set_candidate_status(run_id: str, cand_id: str, status: str) -> None:
    with connect() as c:
        c.execute("UPDATE candidates SET status=? WHERE run_id=? AND cand_id=?", (status, run_id, cand_id))


def selected_canonical_urls() -> set[str]:
    """URLs of stories that already became an edition; used to prevent repeats."""
    with connect() as c:
        rows = c.execute(
            "SELECT canonical_url FROM candidates WHERE status IN ('selected','published')").fetchall()
    return {r[0] for r in rows}


def save_verification(run_id: str, report) -> None:
    verdicts = {v.claim_id: v.verdict for v in report.verdicts}
    with connect() as c:
        for cl in report.claims:
            c.execute("INSERT OR REPLACE INTO claims VALUES(?,?,?,?,?,?)",
                      (run_id, report.candidate_id, cl.id, cl.text, int(cl.central), verdicts.get(cl.id)))
        for e in report.evidence:
            c.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (run_id, report.candidate_id, e.claim_id, e.url, e.quote, e.origin, e.stance,
                       e.source_tier.value, e.retrieved_at,
                       None if e.quote_verified is None else int(e.quote_verified)))


def save_ranking(run_id: str, cand_id: str, total: float, detail: dict) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO rankings VALUES(?,?,?,?)",
                  (run_id, cand_id, total, json.dumps(detail)))


def save_article(slug: str, run_id: str, title: str, status: str, path: str, quality: str) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO articles VALUES(?,?,?,?,?,?,?)",
                  (slug, run_id, title, status, path, quality, now()))


def set_article_status(slug: str, status: str, path: str | None = None) -> None:
    with connect() as c:
        if path:
            c.execute("UPDATE articles SET status=?, path=? WHERE slug=?", (status, path, slug))
        else:
            c.execute("UPDATE articles SET status=? WHERE slug=?", (status, slug))


def get_article(slug: str):
    with connect() as c:
        return c.execute("SELECT * FROM articles WHERE slug=?", (slug,)).fetchone()


def list_articles(status: str | None = None):
    with connect() as c:
        if status:
            return c.execute("SELECT * FROM articles WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
        return c.execute("SELECT * FROM articles ORDER BY created_at DESC").fetchall()


def save_review(slug: str, decision: str, reason: str = "") -> None:
    with connect() as c:
        c.execute("INSERT INTO reviews VALUES(?,?,?,?)", (slug, decision, reason, now()))


def save_prediction(slug: str, p) -> None:
    with connect() as c:
        c.execute("INSERT INTO predictions VALUES(?,?,?,?,?,?,?)",
                  (slug, p.statement, p.horizon_date, p.confidence, json.dumps(p.falsifiers), None, None))


# ---------------------------------------------------------------- editions
# The `edition_date` column holds the EDITION ID: "2026-11-05" for the day's first edition,
# "2026-11-05-2", "-3" ... for extra same-day editions (`main.py run --extra`).
def save_edition(edition_date: str, run_id: str, title: str, status: str, path: str, stories: int) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO editions VALUES(?,?,?,?,?,?,?,?,?)",
                  (edition_date, run_id, title, status, path, stories, now(), None, None))


def get_edition(edition_date: str):
    with connect() as c:
        return c.execute("SELECT * FROM editions WHERE edition_date=?", (edition_date,)).fetchone()


def list_editions(status: str | None = None):
    with connect() as c:
        if status:
            return c.execute("SELECT * FROM editions WHERE status=? ORDER BY edition_date DESC", (status,)).fetchall()
        return c.execute("SELECT * FROM editions ORDER BY edition_date DESC").fetchall()


def decide_edition(edition_date: str, status: str, path: str, reason: str = "") -> None:
    """Record the human decision. Rejected editions release their stories for future runs."""
    with connect() as c:
        c.execute("UPDATE editions SET status=?, path=?, decided_at=?, decision_reason=? WHERE edition_date=?",
                  (status, path, now(), reason, edition_date))
        row = c.execute("SELECT run_id FROM editions WHERE edition_date=?", (edition_date,)).fetchone()
        if row:
            new = "published" if status == "published" else "edition_rejected"
            c.execute("UPDATE candidates SET status=? WHERE run_id=? AND status='selected'", (new, row[0]))


def next_edition_id(day: str) -> str:
    """First free edition id for a calendar date: 2026-11-05, then 2026-11-05-2, -3 ..."""
    with connect() as c:
        rows = c.execute("SELECT edition_date FROM editions WHERE edition_date=? OR edition_date LIKE ?",
                         (day, day + "-%")).fetchall()
    used = {r[0] for r in rows}
    if day not in used:
        return day
    n = 2
    while f"{day}-{n}" in used:
        n += 1
    return f"{day}-{n}"


def claim_trigger(day: str, kind: str) -> bool:
    """Record that a scheduled run of `kind` started for `day`. False if one already did (the Cloudflare
    trigger and GitHub's backup schedule can both fire; only the first one runs)."""
    with connect() as c:
        cur = c.execute("INSERT OR IGNORE INTO triggers VALUES(?,?,?)", (day, kind, now()))
        return cur.rowcount == 1
