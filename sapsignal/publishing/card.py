"""Shared drawing helpers: brand colours, bundled fonts (OFL, in assets/fonts, so images look identical on
your machine and in GitHub Actions), glyph-safe text and word wrapping."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import PROJECT_DIR

# Brand palette (matches assets/brand): white type on deep navy, electric cyan accents, gold highlights.
PAPER, INK, MUTED, ACCENT, RULE = "#08183a", "#ffffff", "#a9b8d0", "#00d4ff", "#22396b"
GOLD, BLUE = "#ffb800", "#0a6cff"
FONTS = PROJECT_DIR / "assets" / "fonts"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


_SWAP = {"→": "›", "←": "‹", "⇒": "›", "➜": "›", "•": "·", "\u00a0": " "}


@lru_cache(maxsize=1)
def _covered() -> frozenset:
    from fontTools.ttLib import TTFont
    sets = [set(TTFont(str(FONTS / f)).getBestCmap()) for f in ("SourceSerif4-Bold.ttf", "Inter-Regular.ttf")]
    return frozenset(sets[0] & sets[1])


UNDRAWABLE: list[str] = []      # characters replaced while rendering (reported by the QA check)


def safe_text(text: str) -> str:
    """Never draw a missing-glyph box and never glue words: normalise look-alikes, swap common symbols,
    and replace anything the bundled fonts can't draw with its plain-letter form (or a space)."""
    import unicodedata
    from .typography import normalize
    text = "".join(_SWAP.get(ch, ch) for ch in normalize(text or ""))
    ok = _covered()
    out = []
    for ch in text:
        if ord(ch) in ok or ch == "\n":
            out.append(ch)
            continue
        plain = "".join(c for c in unicodedata.normalize("NFKD", ch) if ord(c) in ok and not unicodedata.combining(c))
        UNDRAWABLE.append(f"U+{ord(ch):04X}")
        out.append(plain or " ")
    return " ".join("".join(out).split(" ")) if out else ""


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    text = safe_text(text)
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines




def brand_mark(height: int):
    """The logo mark (assets/brand/mark.png) scaled to `height` px, or None if it's missing."""
    from PIL import Image
    p = PROJECT_DIR / "assets" / "brand" / "mark.png"
    if not p.exists():
        return None
    m = Image.open(p).convert("RGBA")
    return m.resize((max(1, round(m.width * height / m.height)), height), Image.LANCZOS)
