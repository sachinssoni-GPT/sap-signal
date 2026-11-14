"""Delivery channels: email (SMTP, e.g. Gmail with an App Password) and Telegram (Bot API).

Configuration is environment-only (GitHub Actions secrets):
  SMTP_HOST (default smtp.gmail.com), SMTP_PORT (default 465), SMTP_USER, SMTP_PASSWORD, EMAIL_TO
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
A channel that is not configured is skipped with a message; it never crashes the pipeline.
"""
import os
import smtplib
import ssl
from pathlib import Path
from email.message import EmailMessage

import requests


def email_configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"))


def send_email(subject: str, html: str, text: str, attachments: list | None = None) -> str:
    if not email_configured():
        return "email skipped: SMTP_USER / SMTP_PASSWORD / EMAIL_TO not set"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("EMAIL_FROM") or os.environ["SMTP_USER"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    types = {".png": ("image", "png"), ".pdf": ("application", "pdf"), ".html": ("text", "html")}
    for path in attachments or []:
        path = Path(path)
        if path.exists():
            main, sub = types.get(path.suffix.lower(), ("application", "octet-stream"))
            msg.add_attachment(path.read_bytes(), maintype=main, subtype=sub, filename=path.name)
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    return f"email sent to {os.environ['EMAIL_TO']}"


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram(text: str, buttons: list[list[tuple[str, str]]] | None = None, html: bool = True) -> str:
    """buttons: rows of (label, url). URL buttons open the signed approval page in the browser."""
    if not telegram_configured():
        return "telegram skipped: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set"
    body = {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text[:4000],
            "disable_web_page_preview": True}
    if html:
        body["parse_mode"] = "HTML"
    if buttons:
        body["reply_markup"] = {"inline_keyboard": [[{"text": t, "url": u} for t, u in row] for row in buttons]}
    r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                      json=body, timeout=30)
    if not r.ok:
        return f"telegram failed: HTTP {r.status_code} {r.text[:200]}"
    return "telegram sent"


def send_telegram_photo(path, caption: str = "") -> str:
    """Send the social card so you can save it from your phone and post it."""
    if not telegram_configured():
        return "telegram skipped: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set"
    path = Path(path)
    if not path.exists():
        return f"telegram photo skipped: {path.name} not found"
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendPhoto",
                          data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": caption[:1000]},
                          files={"photo": (path.name, f, "image/png")}, timeout=60)
    return "telegram photo sent" if r.ok else f"telegram photo failed: HTTP {r.status_code} {r.text[:200]}"


def send_telegram_album(paths, caption: str = "", numbered: bool = False) -> str:
    """Up to 10 images as one swipeable album (the Instagram carousel), so you can save them all at once."""
    import json as _json
    if not telegram_configured():
        return "telegram skipped: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set"
    paths = [Path(p) for p in paths if Path(p).exists()][:10]
    if not paths:
        return "telegram album skipped: no images"
    media, files = [], {}
    for i, p in enumerate(paths):
        item = {"type": "photo", "media": f"attach://f{i}"}
        text = f"Slide {i + 1} of {len(paths)}" if numbered else ""
        if i == 0 and caption:
            text = (caption + ("\n" + text if text else ""))[:1000]
        if text:
            item["caption"] = text
        media.append(item)
        files[f"f{i}"] = (p.name, p.read_bytes(), "image/png")
    r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMediaGroup",
                      data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "media": _json.dumps(media)},
                      files=files, timeout=120)
    return "telegram album sent" if r.ok else f"telegram album failed: HTTP {r.status_code} {r.text[:200]}"


def send_telegram_document(path, caption: str = "") -> str:
    """Send a file (the LinkedIn carousel PDF, the article page) so you can open or forward it from your phone."""
    if not telegram_configured():
        return "telegram skipped: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set"
    path = Path(path)
    if not path.exists():
        return f"telegram document skipped: {path.name} not found"
    mime = {".pdf": "application/pdf", ".html": "text/html", ".png": "image/png"}.get(path.suffix.lower(),
                                                                                       "application/octet-stream")
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendDocument",
                          data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": caption[:1000]},
                          files={"document": (path.name, f, mime)}, timeout=120)
    return "telegram document sent" if r.ok else f"telegram document failed: HTTP {r.status_code} {r.text[:200]}"
