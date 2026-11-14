"""Markdown for the Architect's Take. Sources are built from the evidence ledger, never from model text,
so a hallucinated link cannot reach the issue."""
import json
from pathlib import Path

from ..editorial.quality_gate import cited_ids
from ..schemas import VerificationReport
from .text import footnotes, human_dates

FORMAT_LABELS = {"landscape_impact": "What it means for your landscape", "decision_guide": "How I'd decide",
                 "contrarian": "The contrarian take", "by_the_numbers": "By the numbers",
                 "winners_losers": "Winners and losers", "long_view": "The long view",
                 "connecting_dots": "Connecting the dots"}


def take_sources(text: str, report: VerificationReport) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """[(claim id, claim text, [(outlet, url), ...])] for every claim the text cites, in order."""
    from ..research.source_registry import outlet_name
    out = []
    for cid in sorted(cited_ids(text), key=lambda c: int(c[1:])):
        claim = next((c for c in report.claims if c.id == cid), None)
        if not claim:
            continue
        seen, links = set(), []
        for e in report.evidence:
            url = e.resolved_url or e.url
            if e.claim_id == cid and e.quote_verified and e.stance == "supports" and url not in seen:
                seen.add(url)
                links.append((outlet_name(url), url))
        out.append((cid, claim.text, links))
    return out


def _take_text(take) -> str:
    return "\n".join([*(sec.body for sec in take.sections), *take.watch])


def render_take_body(take, report: VerificationReport, heading: str = "###") -> str:
    """The Take's sections, its watch list and sources. [C#] become superscript links."""
    r = lambda t: footnotes(human_dates(t or "")).strip()
    parts = [f"{heading} {human_dates(sec.heading).strip()}\n{r(sec.body)}" for sec in take.sections if sec.body.strip()]
    if take.watch:
        parts.append(f"{heading} What to watch\n" + "\n".join(f"- {r(w)}" for w in take.watch if w.strip()))
    src = take_sources(_take_text(take), report)
    if src:
        lines = []
        for cid, text, links in src:
            lines.append(f'<span id="src-{cid.lower()}"></span>**[{cid[1:]}]** {text}')
            lines += [f"- {o}: <{u}>" for o, u in links]
            lines.append("")
        parts.append(f"{heading} Sources\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
