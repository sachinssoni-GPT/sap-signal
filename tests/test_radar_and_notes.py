"""The Deadline Radar's date check and the Telegram notes collector."""
from datetime import date

import pytest

from sapsignal import config, deadlines as dl, notes
from sapsignal.schemas import DeadlineProposal, Evidence, VerificationReport, Claim

T = date(2026, 11, 16)


@pytest.mark.parametrize("value,quote,ok", [
    ("2027-12-31", "mainstream maintenance ends on 31 December 2027 for EHP 6-8", True),
    ("2027-12-31", "Mainstream maintenance ends December 31, 2027.", True),
    ("2027-12-31", "support runs until the end of 2027", True),
    ("2027-12-31", "support runs until 2027", False),                  # year alone is not a date
    ("2027-12-30", "ends on 31 December 2027", False),                 # wrong day
    ("2028-03", "the release is planned for March 2028", True),
    ("2028-03", "the release is planned for 2028", False),
    ("2028-04-01", "from 2028-04-01 the new price list applies", True),
])
def test_a_date_must_be_stated_in_the_quote(value, quote, ok):
    assert dl._date_stated(value, quote) is ok


def _report(sid, quote, url="https://news.sap.com/a"):
    return VerificationReport(candidate_id=sid, claims=[Claim(id="C1", text="x")],
                              evidence=[Evidence(claim_id="C1", url=url, quote=quote, quote_verified=True)])


def test_verify_keeps_only_stated_future_new_dates():
    reports = {"E1": _report("E1", "SAP will retire the API on 30 June 2027, it said"),
               "E2": _report("E2", "the old tool stopped working on 1 March 2026")}
    props = [DeadlineProposal(item="API retired", product="SAP X API", date="2027-06-30", kind="retirement",
                              claim_id="E1:C1", quote="30 June 2027"),
             DeadlineProposal(item="Past", product="Tool", date="2026-03-01", claim_id="E2:C1", quote="1 March 2026"),
             DeadlineProposal(item="No such claim", product="Y", date="2027-06-30", claim_id="E9:C4", quote="30 June 2027"),
             DeadlineProposal(item="Already there", product="SAP ECC 6.0 / Business Suite 7", date="2027-12-31",
                              claim_id="E1:C1", quote="x")]
    existing = [{"item": "ECC", "product": "SAP ECC 6.0 / Business Suite 7", "date": "2027-12-31"}]
    kept, why = dl.verify(props, reports, T, existing)
    assert [r["item"] for r in kept] == ["API retired"] and kept[0]["source"] == "https://news.sap.com/a"
    assert any("past" in w for w in why) and any("not a verified claim" in w for w in why)


def test_upcoming_labels_and_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "deadlines.yaml").write_text("# header kept\nrows:\n  - item: A\n    product: P\n    date: '2027-12-31'\n"
                                             "  - item: Old\n    product: Q\n    date: '2025-01-01'\n")
    assert [r["item"] for r in dl.upcoming(dl.load(), T)] == ["A"]
    assert dl.label("2027-12-31") == "31 Dec 2027" and dl.label("2033-12") == "Dec 2033"
    assert dl.merge([{"item": "B", "product": "R", "date": "2027-06-30", "status": "new"},
                     {"item": "dup", "product": "P", "date": "2027-12-31"}]) == 1
    text = (tmp_path / "deadlines.yaml").read_text()
    assert text.startswith("# header kept") and [r["item"] for r in dl.upcoming(dl.load(), T)] == ["B", "A"]


def test_the_seed_radar_is_valid_and_sourced():
    rows = dl.load(config.PROJECT_DIR / "deadlines.yaml")
    assert rows and all(r.get("source", "").startswith("https://") and dl._as_date(r["date"]) for r in rows)


class _Resp:
    def __init__(self, data=None, content=b"", ok=True):
        self._d, self.content, self.ok, self.status_code, self.text = data, content, ok, 200, ""

    def json(self):
        return self._d


def test_collect_saves_only_my_take_messages_and_voice_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    updates = {"ok": True, "result": [
        {"update_id": 10, "message": {"chat": {"id": 42}, "date": 1, "text": "/take Inventory Neo apps first"}},
        {"update_id": 11, "message": {"chat": {"id": 42}, "date": 2, "text": "hello bot"}},
        {"update_id": 12, "message": {"chat": {"id": 99}, "date": 3, "text": "/take spam from a stranger"}},
        {"update_id": 13, "message": {"chat": {"id": 42}, "date": 4, "voice": {"file_id": "F"}}}]}
    calls = []

    def get(url, params=None, **k):
        calls.append(url)
        if url.endswith("/getUpdates"):
            return _Resp(updates if not params or params.get("offset") in (None,) else {"ok": True, "result": []})
        if url.endswith("/getFile"):
            return _Resp({"result": {"file_path": "voice/f.oga"}})
        return _Resp(content=b"audio")
    monkeypatch.setattr(notes.requests, "get", get)
    monkeypatch.setattr(notes.requests, "post", lambda *a, **k: _Resp({"text": "Waiting costs more than moving."}))
    monkeypatch.setattr("sapsignal.notify.channels.send_telegram", lambda *a, **k: "ack")
    log = notes.collect_telegram()
    saved = sorted(p.name for p in (tmp_path / "notes").glob("*.md"))
    assert saved == ["tg-10.md", "tg-13.md"]
    text = notes.read_notes()
    assert "Inventory Neo apps first" in text and "Waiting costs more" in text and "stranger" not in text
    assert (tmp_path / "data" / "telegram_offset.txt").read_text() == "13"
    assert notes.archive_notes(tmp_path / "out") == 2 and notes.read_notes() == ""
    assert any("2 new" in line for line in log)


def test_control_panel_sends_long_lived_signed_run_and_notes_buttons(monkeypatch):
    import hashlib, hmac, time
    from urllib.parse import parse_qs, urlparse
    from sapsignal.notify import messages
    monkeypatch.setenv("APPROVAL_SECRET", "s" * 40)
    monkeypatch.setitem(config.get_config()["approval"], "worker_url", "https://w.example.workers.dev")
    sent = []
    monkeypatch.setattr(messages, "send_telegram", lambda text, rows=None, **k: sent.append((text, rows)) or "ok")
    messages.send_control_panel()
    (text, rows), = sent
    links = [u for row in rows for _, u in row]
    for u, act in zip(links, ("run", "notes")):
        q = {k: v[0] for k, v in parse_qs(urlparse(u).query).items()}
        assert q["action"] == act and int(q["exp"]) > time.time() + 300 * 86400
        want = hmac.new(b"s" * 40, f"{act}:{q['date']}:{q['exp']}".encode(), hashlib.sha256).hexdigest()
        assert q["sig"] == want                          # what the Worker verifies


def test_a_mail_failure_never_stops_telegram(monkeypatch):
    import smtplib
    from sapsignal.notify import channels
    for k, v in {"SMTP_USER": '"me@gmail.com"', "SMTP_PASSWORD": "'abcd efgh ijkl mnop'\n", "EMAIL_TO": "me@gmail.com"}.items():
        monkeypatch.setenv(k, v)
    seen = {}

    class Boom:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, user, pw):
            seen["login"] = (user, pw)
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    monkeypatch.setattr(channels.smtplib, "SMTP_SSL", Boom)
    out = channels.send_email("s", "<p>h</p>", "t")
    assert out.startswith("email FAILED") and seen["login"] == ("me@gmail.com", "abcdefghijklmnop")
