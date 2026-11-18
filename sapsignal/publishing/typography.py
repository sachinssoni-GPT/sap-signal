"""One normaliser for every word the pipeline writes, so text and images can never disagree.

Models like to emit typographic look-alikes: non-breaking hyphens (maximum‑severity), no-break and thin
spaces, zero-width joiners, soft hyphens. Browsers draw them; our image fonts may not, and a dropped
character glues two words together. Everything is mapped to its plain equivalent at the source."""
from __future__ import annotations

import re
import unicodedata

_MAP = {
    # hyphens and minus signs -> ASCII hyphen
    "‐": "-", "‑": "-", "‒": "-", "⁃": "-", "−": "-", "﹣": "-", "－": "-",
    # every flavour of space -> a normal space
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", "　": " ",
    # invisible characters -> nothing
    "­": "", "​": "", "‌": "", "‍": "", "⁠": "", "﻿": "",
    # line/paragraph separators -> newline
    " ": "\n", " ": "\n",
}
_TRANS = str.maketrans(_MAP)


def normalize(text: str) -> str:
    if not text:
        return text or ""
    text = unicodedata.normalize("NFC", text).translate(_TRANS)
    return re.sub(r"(?<=\S) {2,}(?=\S)", " ", text)


def odd_characters(text: str) -> list[str]:
    """Characters that should never survive normalisation (for the QA report)."""
    return sorted({f"U+{ord(c):04X}" for c in text or "" if c in _MAP})
