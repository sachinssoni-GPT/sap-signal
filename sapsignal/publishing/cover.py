"""The newsletter edition's cover image (1280x720, LinkedIn's article cover size). No LLM: the words come
from the approved issue."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from ..schemas import Edition
from .card import ACCENT, GOLD, INK, MUTED, PAPER, RULE, _font, _wrap, brand_mark, safe_text

W, H = 1280, 720


def _fit(d, text, max_w, max_h, start=78, stop=42, line=1.16):
    for size in range(start, stop - 1, -2):
        f = _font("SourceSerif4-Bold.ttf", size)
        lines = _wrap(d, text, f, max_w)
        if len(lines) * int(size * line) <= max_h:
            return f, lines
    f = _font("SourceSerif4-Bold.ttf", stop)
    lines = _wrap(d, text, f, max_w)[: max(1, max_h // int(stop * line))]
    if lines:
        lines[-1] = lines[-1].rstrip(".,;:") + "…"
    return f, lines


def render_cover(ed: Edition, publication: dict, out: Path) -> Path:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    left, right = 96, W - 96
    d.rectangle([0, 0, W, 14], fill=GOLD)
    brand = _font("Inter-SemiBold.ttf", 30)
    x = left
    mk = brand_mark(54)
    if mk is not None:
        img.paste(mk, (left, 58), mk)
        x = left + mk.width + 22
    for ch in safe_text(publication.get("name", "")).upper():          # letter-spaced masthead
        d.text((x, 70), ch, font=brand, fill=ACCENT)
        x += d.textlength(ch, font=brand) + 6
    small = _font("Inter-Regular.ttf", 26)
    when = f"ISSUE {ed.issue_no}  ·  " + date.fromisoformat(ed.edition_date).strftime("%-d %b %Y").upper()
    d.text((right - d.textlength(when, font=small), 74), when, font=small, fill=MUTED)
    kicker = "THE ARCHITECT'S TAKE" if ed.take is not None else "THIS WEEK'S SIGNAL"
    d.text((left, 176), kicker, font=_font("Inter-SemiBold.ttf", 28), fill=GOLD)
    f, lines = _fit(d, ed.title, right - left, 330)
    y = 226
    for ln in lines:
        d.text((left, y), ln, font=f, fill=INK)
        y += int(f.size * 1.16)
    d.line([left, H - 112, right, H - 112], fill=RULE, width=2)
    tag = safe_text(publication.get("tagline", ""))
    tf = _font("Inter-Regular.ttf", 26)
    while tag and d.textlength(tag, font=tf) > right - left:
        tag = tag[:-2]
    d.text((left, H - 86), tag, font=tf, fill=MUTED)
    author = safe_text(publication.get("author", ""))
    if author:
        bf = _font("Inter-SemiBold.ttf", 26)
        by = f"Curated by {author}"
        d.text((right - d.textlength(by, font=bf), 178), by, font=bf, fill=INK)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out
