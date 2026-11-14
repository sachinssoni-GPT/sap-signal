"""Shared drawing helpers: brand colours, bundled fonts (OFL, in assets/fonts, so images look identical on
your machine and in GitHub Actions), glyph-safe text and word wrapping."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import PROJECT_DIR

# A calm, enterprise palette: deep teal accent on warm paper.
PAPER, INK, MUTED, ACCENT, RULE = "#fbfaf6", "#17202a", "#5f6b75", "#0b6e69", "#dfe3e1"
FONTS = PROJECT_DIR / "assets" / "fonts"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


_SWAP = {"→": "›", "←": "‹", "⇒": "›", "➜": "›", "•": "·", "\u00a0": " "}


@lru_cache(maxsize=1)
def _covered() -> frozenset:
    from fontTools.ttLib import TTFont
    sets = [set(TTFont(str(FONTS / f)).getBestCmap()) for f in ("SourceSerif4-Bold.ttf", "Inter-Regular.ttf")]
    return frozenset(sets[0] & sets[1])


def safe_text(text: str) -> str:
    """Never draw a missing-glyph box: swap common symbols, drop anything the bundled fonts can't render."""
    text = "".join(_SWAP.get(ch, ch) for ch in text or "")
    ok = _covered()
    return "".join(ch for ch in text if ord(ch) in ok or ch in "\n")


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


