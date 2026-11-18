"""Quality assurance on every draft, before it reaches you.

  proofread(ed)   copy-editor pass (LLM) over every reader-facing string. Small, exact fixes are applied
                  automatically (missing spaces, typos, doubled words); anything else is reported.
  check_text()    deterministic checks: odd unicode, doubled words, words joined across punctuation.
  check_images()  every cover/slide is read back with OCR and compared with the words it should show:
                  two words read as one ("maximumseverity") or missing words are reported.

Blocking findings start with "BLOCKING" and stop Approve (config qa.block_approval_on_errors)."""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import get_config
from .publishing.typography import normalize, odd_characters
from .schemas import Edition

AUTO_FIX = {"missing_space", "typo", "doubled_word", "grammar"}


def _cfg() -> dict:
    return get_config().get("qa", {}) or {}


# ------------------------------------------------------------------ the fields a reader sees
def _fields(ed: Edition) -> dict[str, tuple[object, str]]:
    """field id -> (owner object, attribute) for every reader-facing string."""
    f: dict[str, tuple[object, str]] = {"issue.title": (ed, "title"), "issue.description": (ed, "description"),
                                        "issue.intro": (ed, "intro")}
    for s in ed.stories:
        for a in ("headline", "summary", "why_it_matters"):
            f[f"story.{s.candidate_id}.{a}"] = (s, a)
    if ed.take is not None:
        f["take.title"], f["take.dek"] = (ed.take, "title"), (ed.take, "dek")
        for i, sec in enumerate(ed.take.sections):
            f[f"take.section{i + 1}.heading"], f[f"take.section{i + 1}.body"] = (sec, "heading"), (sec, "body")
    if ed.linkedin is not None:
        for a in ("share_post", "story_post", "carousel_caption", "carousel_title"):
            f[f"linkedin.{a}"] = (ed.linkedin, a)
    return f


def _small_edit(a: str, b: str) -> bool:
    return 0 < len(a) <= 120 and difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.6


def proofread(ed: Edition) -> tuple[Edition, list[str]]:
    """Normalise every field, then let the copy-editor find mechanical errors. Returns (edition, notes)."""
    fields = _fields(ed)
    for owner, attr in fields.values():
        setattr(owner, attr, normalize(getattr(owner, attr) or ""))
    if ed.take is not None:
        ed.take.watch = [normalize(w) for w in ed.take.watch]
    notes: list[str] = []
    if not _cfg().get("proofread", True) or not os.environ.get("OPENAI_API_KEY"):
        return ed, notes
    from .agents import crews
    try:
        report = crews.run_proofread({k: getattr(o, a) for k, (o, a) in fields.items()})
    except Exception as exc:
        notes.append(f"QA: proofreading skipped ({type(exc).__name__})")
        return ed, notes
    for it in report.issues:
        target = fields.get(it.field)
        if target is None:
            continue
        owner, attr = target
        text = getattr(owner, attr) or ""
        if it.quote and text.count(it.quote) == 1 and it.kind in AUTO_FIX and _small_edit(it.quote, it.fix):
            setattr(owner, attr, text.replace(it.quote, normalize(it.fix)))
            notes.append(f"QA fixed ({it.kind}) in {it.field}: '{it.quote}' -> '{it.fix}'")
        elif it.quote and it.quote in text:
            notes.append(f"QA check ({it.kind}) in {it.field}: '{it.quote}' -> suggested '{it.fix}'"
                         + (f" ({it.note})" if it.note else ""))
    return ed, notes


# ------------------------------------------------------------------ deterministic text checks
_URL = re.compile(r"https?://\S+|<[^>]+>|\]\([^)]*\)")
_JOINED = re.compile(r"\b[a-z]{2,}[.,;:!?][A-Z][a-z]{2,}\b")
_DOUBLE = re.compile(r"\b([A-Za-z]{2,})\s+\1\b", re.I)
_ALLOWED_DOUBLE = {"that", "had", "is"}


def check_text(name: str, text: str) -> list[str]:
    out = []
    odd = odd_characters(text)
    if odd:
        out.append(f"BLOCKING: {name} contains invisible/look-alike characters {odd}")
    body = _URL.sub(" ", text or "")
    for m in _JOINED.finditer(body):
        out.append(f"BLOCKING: {name}: missing space in '{m.group(0)}'")
    for m in _DOUBLE.finditer(body):
        if m.group(1).lower() not in _ALLOWED_DOUBLE:
            out.append(f"BLOCKING: {name}: doubled word '{m.group(0)}'")
    return out


# ------------------------------------------------------------------ images: read back with OCR
def _ocr_words(png: Path) -> list[str] | None:
    exe = shutil.which("tesseract")
    if not exe:
        return None
    from PIL import Image, ImageOps
    im = Image.open(png).convert("L")
    if sum(im.resize((1, 1)).getdata()) < 128:          # dark background -> invert for OCR
        im = ImageOps.invert(im)
    im = im.resize((im.width * 2, im.height * 2))
    tmp = png.with_suffix(".ocr.png")
    im.save(tmp)
    try:
        r = subprocess.run([exe, str(tmp), "-", "--psm", "11"], capture_output=True, text=True, timeout=60)
    finally:
        tmp.unlink(missing_ok=True)
    return [w.lower() for w in re.findall(r"[A-Za-z0-9]+", r.stdout)]


def _words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z0-9]+", normalize(text or ""))]


def check_image(png: Path, expected: list[str]) -> list[str]:
    seen = _ocr_words(png)
    if seen is None:
        return []
    got = set(seen)
    out = []
    for line in expected:
        words = _words(line)
        strays = [t for t in got if t not in words and len(t) >= 6]
        for a, b in zip(words, words[1:]):
            if len(a) < 3 or len(b) < 3 or (a in got and b in got):
                continue
            joined = a + b
            hit = next((t for t in strays if difflib.SequenceMatcher(None, t, joined).ratio() >= 0.85), None)
            if hit:                                   # OCR is noisy: 'maximumeseverity' still counts
                out.append(f"BLOCKING: {png.name}: '{a} {b}' reads as one word '{hit}'")
        long = [w for w in words if len(w) >= 4 and not w.isdigit()]
        if long:
            missing = [w for w in long if w not in got]
            if len(missing) / len(long) > 0.25:
                out.append(f"QA: {png.name}: text may be cut or unreadable (not found: {', '.join(missing[:6])})")
    return out


def image_expectations(ed: Edition, folder: Path) -> dict[Path, list[str]]:
    """What each rendered image must say, in render order (cover; carousel: cover, radar?, stories, follow)."""
    from .publishing.edition import LINKEDIN_DIR, linkedin_texts, radar_rows
    li = folder / LINKEDIN_DIR
    exp: dict[Path, list[str]] = {li / "1-tuesday-cover.png": [ed.title]}
    slides = sorted((li / "slides").glob("*.png"))
    if not slides:
        return exp
    seq: list[list[str]] = [[linkedin_texts(ed)["carousel_title"]]]
    rows = radar_rows(ed)
    if rows:
        seq.append([r["item"] for r in rows[:4]])
    seq += [[s.headline] for s in ed.stories[:6]]
    for p, words in zip(slides, seq):
        exp[p] = words
    return exp


def check_images(ed: Edition, folder: Path) -> list[str]:
    if not _cfg().get("ocr_images", True):
        return []
    if not shutil.which("tesseract"):
        return ["QA: image check skipped (tesseract not installed)"]
    out = []
    for png, expected in image_expectations(ed, folder).items():
        if png.exists():
            out += check_image(png, expected)
    return out


def run_checks(ed: Edition, folder: Path) -> list[str]:
    from .publishing.card import UNDRAWABLE
    from .publishing.edition import LINKEDIN_DIR
    out = []
    if UNDRAWABLE:
        out.append(f"QA: characters the image fonts can't draw were replaced: {sorted(set(UNDRAWABLE))}")
        UNDRAWABLE.clear()
    files = [folder / "issue.md", *sorted((folder / LINKEDIN_DIR).glob("*.txt"))]
    for f in files:
        if f.exists():
            out += check_text(f.name, f.read_text(encoding="utf-8"))
    out += check_images(ed, folder)
    (folder / "qa.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def blocking(folder: Path) -> list[str]:
    f = folder / "qa.json"
    if not f.exists():
        return []
    return [x for x in json.loads(f.read_text(encoding="utf-8")) if x.startswith("BLOCKING")]
