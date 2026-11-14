"""The Saturday carousel: a LinkedIn document post (PDF of 1080x1350 slides) built from the approved issue.
No LLM on the slides: every word comes from the issue (Radar rows, headlines, why-it-matters), so a slide
can never say something the issue doesn't.

  1     cover        masthead, the carousel title, issue and date, "swipe"
  2     the Radar    upcoming dated SAP changes (NEW ones marked)
  3..   the week     one slide per story: beat, headline, what it changes
  last  follow       where the full Take is + follow / free checklist
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from .. import deadlines as dl
from ..schemas import Edition
from .card import ACCENT, INK, MUTED, PAPER, RULE, _font, _wrap, safe_text

W, H = 1080, 1350
L, R = 96, W - 96


def _fit(d, text, font_name, max_w, max_h, start, stop, line=1.2):
    for size in range(start, stop - 1, -2):
        f = _font(font_name, size)
        lines = _wrap(d, text, f, max_w)
        if len(lines) * int(size * line) <= max_h:
            return f, lines
    f = _font(font_name, stop)
    lines = _wrap(d, text, f, max_w)[: max(1, max_h // int(stop * line))]
    if lines:
        lines[-1] = lines[-1].rstrip(".,;:") + "…"
    return f, lines


def _block(d, lines, font, x, y, fill, line=1.2):
    for ln in lines:
        d.text((x, y), ln, font=font, fill=fill)
        y += int(font.size * line)
    return y


def _frame(ed: Edition, publication: dict, page: int, total: int):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=ACCENT)
    brand = _font("Inter-SemiBold.ttf", 30)
    x = L
    for ch in safe_text(publication.get("name", "")).upper():
        d.text((x, 84), ch, font=brand, fill=ACCENT)
        x += d.textlength(ch, font=brand) + 6
    small = _font("Inter-Regular.ttf", 28)
    when = date.fromisoformat(ed.edition_date).strftime("%-d %b %Y").upper()
    d.text((R - d.textlength(when, font=small), 88), when, font=small, fill=MUTED)
    d.line([L, H - 128, R, H - 128], fill=RULE, width=2)
    author = safe_text(publication.get("author", ""))
    d.text((L, H - 100), f"Curated by {author}" if author else "", font=small, fill=INK)
    pg = f"{page}/{total}"
    d.text((R - d.textlength(pg, font=small), H - 100), pg, font=small, fill=MUTED)
    return img, d


def render_carousel(ed: Edition, publication: dict, title: str, radar: list[dict], pdf: Path,
                    slides_dir: Path) -> list[Path]:
    from ..research.events import SECTION_LABELS
    slides_dir.mkdir(parents=True, exist_ok=True)
    for old in slides_dir.glob("*.png"):
        old.unlink()
    stories = ed.stories[:6]
    total = 2 + (1 if radar else 0) + len(stories)
    imgs: list[Image.Image] = []
    kicker = _font("Inter-SemiBold.ttf", 34)
    page = 0

    def nxt():
        nonlocal page
        page += 1
        return _frame(ed, publication, page, total)

    # cover
    img, d = nxt()
    d.text((L, 300), f"ISSUE {ed.issue_no}", font=kicker, fill=ACCENT)
    f, lines = _fit(d, title, "SourceSerif4-Bold.ttf", R - L, 560, 104, 60, 1.12)
    _block(d, lines, f, L, 370, INK, 1.12)
    d.text((L, 1060), ("The Deadline Radar + " if radar else "") + f"this week's {len(stories)} stories   ›   swipe",
           font=_font("Inter-SemiBold.ttf", 34), fill=ACCENT)
    imgs.append(img)

    # the Radar
    if radar:
        img, d = nxt()
        d.text((L, 200), "DEADLINE RADAR", font=kicker, fill=ACCENT)
        d.text((L, 250), "Dated SAP changes to plan around", font=_font("Inter-Regular.ttf", 32), fill=MUTED)
        y = 330
        today = date.fromisoformat(ed.edition_date)
        datef, itemf, prodf = _font("Inter-SemiBold.ttf", 38), _font("Inter-Regular.ttf", 33), _font("Inter-Regular.ttf", 27)
        for r in radar[:7]:
            if y > H - 260:
                break
            when = dl.label(r["date"])
            d.text((L, y), when, font=datef, fill=INK)
            if r.get("status") == "new":
                bx = L + d.textlength(when, font=datef) + 18
                d.rounded_rectangle([bx, y + 4, bx + 86, y + 40], radius=8, fill=ACCENT)
                d.text((bx + 14, y + 7), "NEW", font=_font("Inter-SemiBold.ttf", 24), fill="#ffffff")
            days = dl.days_until(r["date"], today)
            if days is not None:
                from .edition import countdown
                left = countdown(days).replace("in ", "")
                lf = _font("Inter-Regular.ttf", 26)
                d.text((R - d.textlength(left, font=lf), y + 6), left, font=lf, fill=MUTED)
            lines = _wrap(d, r["item"], itemf, R - L)[:2]
            y = _block(d, lines, itemf, L, y + 54, INK, 1.25)
            prod = _wrap(d, r.get("product", ""), prodf, R - L)[:1]
            y = _block(d, prod, prodf, L, y + 2, MUTED, 1.2)
            d.line([L, y + 16, R, y + 16], fill=RULE, width=2)
            y += 36
        imgs.append(img)

    # one slide per story
    for s in stories:
        img, d = nxt()
        label = SECTION_LABELS.get(s.section, s.section).upper()
        f, lines = _fit(d, s.headline, "SourceSerif4-Bold.ttf", R - L, 420, 78, 48, 1.15)
        body = safe_text(s.why_it_matters or s.summary)
        fb, bl = _fit(d, body, "Inter-Regular.ttf", R - L, 440, 42, 30, 1.4) if body else (None, [])
        content_h = 80 + len(lines) * int(f.size * 1.15) + ((70 + len(bl) * int(fb.size * 1.4)) if bl else 0)
        y = max(220, (H - content_h) // 2 - 30)
        d.text((L, y), label, font=_font("Inter-SemiBold.ttf", 36), fill=ACCENT)
        y = _block(d, lines, f, L, y + 76, INK, 1.15)
        if bl:
            d.line([L, y + 30, L + 120, y + 30], fill=ACCENT, width=4)
            _block(d, bl, fb, L, y + 70, MUTED, 1.4)
        imgs.append(img)

    # follow
    img, d = nxt()
    msg = "The full Architect's Take, every source and the complete Radar are in this week's newsletter."
    f, lines = _fit(d, msg, "SourceSerif4-Bold.ttf", R - L, 480, 72, 46, 1.15)
    y = _block(d, lines, f, L, 340, INK, 1.15)
    author = safe_text(publication.get("author", ""))
    d.text((L, y + 70), f"Follow {author} for next week's Signal" if author else "Subscribe for next week's Signal",
           font=_font("Inter-SemiBold.ttf", 44), fill=ACCENT)
    d.text((L, y + 140), "Save this post for your planning.", font=_font("Inter-Regular.ttf", 36), fill=MUTED)
    imgs.append(img)

    paths = []
    for i, im in enumerate(imgs, start=1):
        p = slides_dir / f"{i:02d}.png"
        im.save(p, "PNG", optimize=True)
        paths.append(p)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    imgs[0].save(pdf, "PDF", save_all=True, append_images=imgs[1:], resolution=150)
    return paths
