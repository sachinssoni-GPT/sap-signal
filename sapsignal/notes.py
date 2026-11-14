"""Your own points for the Architect's Take.

During the week, message the bot:
  /take <your point>        a typed note
  (a voice note)            transcribed to text when notes.transcribe_voice is on
or drop a .md/.txt file into notes/. The weekly run writes the Take FROM these points, in your voice.
Once the issue is published, the notes move into that issue's folder (notes_used/), so next week
starts clean.

Telegram only keeps unread bot messages for about 24 hours, so `python main.py collect-notes` runs
every few hours (GitHub Actions) and saves them to notes/ in the repo.
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config
from .config import get_config

API = "https://api.telegram.org"


def notes_dir() -> Path:
    p = config.ROOT / (get_config().get("paths", {}) or {}).get("notes", "notes")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _offset_file() -> Path:
    p = config.ROOT / "data" / "telegram_offset.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def read_notes() -> str:
    """All current notes, oldest first, as one block of text ('' when there are none)."""
    parts = []
    for f in sorted(notes_dir().glob("*")):
        if f.suffix.lower() in (".md", ".txt") and f.name.lower() != "readme.md":
            text = f.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def archive_notes(dest: Path) -> int:
    """Move the notes used by a published issue into its folder. Returns how many moved."""
    files = [f for f in notes_dir().glob("*") if f.suffix.lower() in (".md", ".txt") and f.name.lower() != "readme.md"]
    if not files:
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.move(str(f), str(dest / f.name))
    return len(files)


def _transcribe(audio: bytes, filename: str) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return ""
    model = (get_config().get("notes", {}) or {}).get("transcribe_model", "gpt-4o-mini-transcribe")
    r = requests.post("https://api.openai.com/v1/audio/transcriptions",
                      headers={"Authorization": f"Bearer {key}"},
                      files={"file": (filename, audio, "audio/ogg")}, data={"model": model}, timeout=120)
    if not r.ok:
        return ""
    return (r.json() or {}).get("text", "").strip()


def collect_telegram(send_ack: bool = True) -> list[str]:
    """Save new /take messages and voice notes from YOUR chat to notes/. Returns a log."""
    cfg = get_config().get("notes", {}) or {}
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not cfg.get("telegram", True):
        return ["notes: telegram collection is off (notes.telegram: false)"]
    if not (token and chat):
        return ["notes: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set"]
    off = _offset_file()
    offset = int(off.read_text().strip() or 0) if off.exists() else 0
    r = requests.get(f"{API}/bot{token}/getUpdates", params={"offset": offset + 1 if offset else None,
                                                              "timeout": 0, "allowed_updates": '["message"]'},
                     timeout=30)
    if not r.ok:
        return [f"notes: getUpdates failed: HTTP {r.status_code} {r.text[:200]}"]
    log, saved, last = [], 0, offset
    for u in (r.json() or {}).get("result", []):
        last = max(last, int(u.get("update_id", 0)))
        m = u.get("message") or {}
        if str((m.get("chat") or {}).get("id")) != str(chat):
            continue                          # only YOUR chat counts; anyone else is ignored
        when = datetime.fromtimestamp(m.get("date", 0), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        text = (m.get("text") or "").strip()
        body = ""
        if re.match(r"^[/#]take\b", text, re.I):
            body = re.sub(r"^[/#]take(@\w+)?\s*", "", text, flags=re.I).strip()
        elif m.get("voice") and cfg.get("transcribe_voice", True):
            fid = m["voice"].get("file_id")
            f = requests.get(f"{API}/bot{token}/getFile", params={"file_id": fid}, timeout=30)
            fpath = ((f.json() or {}).get("result") or {}).get("file_path") if f.ok else None
            if fpath:
                audio = requests.get(f"{API}/file/bot{token}/{fpath}", timeout=60)
                body = _transcribe(audio.content, Path(fpath).name) if audio.ok else ""
            if not body:
                log.append(f"notes: voice note at {when} could not be transcribed")
        if not body:
            continue
        (notes_dir() / f"tg-{u['update_id']}.md").write_text(f"<!-- {when} UTC -->\n{body}\n", encoding="utf-8")
        saved += 1
    if last != offset:
        off.write_text(str(last))
        requests.get(f"{API}/bot{token}/getUpdates", params={"offset": last + 1, "timeout": 0}, timeout=30)
    total = len([f for f in notes_dir().glob("*") if f.suffix.lower() in (".md", ".txt")
                 and f.name.lower() != "readme.md"])
    if saved and send_ack:
        from .notify.channels import send_telegram
        log.append(send_telegram(f"Noted for this week's Take ({total} note{'s' if total != 1 else ''} so far).",
                                 html=False))
    log.append(f"notes: {saved} new, {total} waiting for the next issue")
    return log
