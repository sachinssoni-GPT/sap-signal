"""Every agent returns one of these models. No free-text hand-offs between steps."""
from enum import Enum
from typing import Literal, Optional

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The six beats the briefing is organised around (config `sections:` uses the same keys).
BEATS = ("ecc_exit", "clean_core", "integration", "data_ai", "commercials", "ecosystem")
Beat = Literal["ecc_exit", "clean_core", "integration", "data_ai", "commercials", "ecosystem"]


class SourceTier(str, Enum):
    PRIMARY = "primary"            # SAP itself, user groups (DSAG, ASUG, UKISUG), regulators
    TIER1_PRESS = "tier1_press"    # wires and financial press
    TRADE_PRESS = "trade_press"    # The Register, diginomica, ERP Today, SAPinsider ...
    RESEARCH_INSTITUTION = "research_institution"   # analyst firms (public notes only)
    REGIONAL_PRESS = "regional_press"
    VENDOR = "vendor"              # interested parties: third-party support, SI marketing, community blogs
    AGGREGATOR = "aggregator"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"


# ---------- discovery ----------
class Candidate(BaseModel):
    id: str = Field(description="Short stable id such as E1, E2")
    title: str
    url: str
    published: Optional[str] = None
    source_name: str = ""
    topic: str = ""
    relevance: int = Field(0, ge=0, le=100, description="Buyer impact for SAP leaders (0-100)")
    summary: str = ""
    india_focus: bool = False                 # unused here; kept so shared helpers stay compatible
    related_urls: list[str] = Field(default_factory=list, description="Set by code: other outlets' coverage")
    section: str = Field("ecosystem", description="One of the six beats")
    outlets: int = Field(0, description="Set by code: distinct outlets carrying the story")
    outlet_names: list[str] = Field(default_factory=list, description="Set by code: those outlets' domains")


class TriagePick(BaseModel):
    """What the triage model returns per kept event. Code maps it back onto the event's URLs."""
    event_id: str = Field(description="The E# id from the table, copied exactly")
    title: str = Field(description="Neutral, specific headline for the event")
    section: Beat
    significance: int = Field(ge=0, le=100, description="Buyer impact: money, deadline, risk or effort for SAP customers")
    why: str = Field("", description="One short line: what it changes for an SAP leader")


class TriageResult(BaseModel):
    picks: list[TriagePick]


# ---------- verification ----------
class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(description="C1, C2, ...")
    text: str
    central: bool = Field(True, description="True if the story collapses without this claim")
    claim_type: Literal["official_statement", "conflict_or_casualty", "market_or_impact",
                        "intelligence_or_attribution", "general"] = "general"


class Evidence(BaseModel):
    claim_id: str
    url: str
    quote: str = Field(description="Exact text copied from the fetched page, under 40 words")
    origin: str = Field("", description="Who originally said/reported it (e.g. 'SAP press release')")
    stance: Literal["supports", "contradicts", "neutral"] = "supports"
    # Set by code, never trusted from the model:
    source_tier: SourceTier = SourceTier.UNKNOWN
    source_perspective: str = "unclassified"
    resolved_url: str = ""
    retrieved_at: str = ""
    quote_verified: Optional[bool] = None


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Literal["supported", "contradicted", "unverifiable"]
    notes: str = ""


class NarrativeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_perspectives: list[str] = Field(default_factory=list)
    official_positions: list[str] = Field(default_factory=list)
    competing_interpretations: list[str] = Field(default_factory=list)
    independently_verified_facts: list[str] = Field(default_factory=list)
    disputed_claims: list[str] = Field(default_factory=list)
    propaganda_or_messaging_indicators: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    claims: list[Claim]
    evidence: list[Evidence]
    verdicts: list[ClaimVerdict] = []
    summary: str = ""
    narrative_assessment: NarrativeAssessment = Field(default_factory=NarrativeAssessment)


# ---------- quality ----------
class CheckResult(BaseModel):
    name: str
    passed: bool
    severity: Literal["block", "revise", "info"] = "revise"
    detail: str = ""


class QualityReport(BaseModel):
    verdict: Literal["pass", "revise", "reject"]
    checks: list[CheckResult] = []
    issues: list[str] = []
    feedback: str = ""


# ---------- per-story brief written from the article it was read from ----------
class QuotedClaim(BaseModel):
    id: str = Field(description="C1, C2, ... in order")
    text: str = Field(description="The fact, in your own words")
    quote: str = Field(description="Supporting text copied EXACTLY from the article, 8-40 words")
    central: bool = True


class StoryBrief(BaseModel):
    """One call per story: claims (each with a verbatim quote) + the reader-facing item built only on them."""
    claims: list[QuotedClaim]
    headline: str = Field(description="Specific, accurate, max 14 words")
    summary: str = Field(description="2-3 sentences, 40-80 words, citing claims as [C1]")
    why_it_matters: str = Field(description="One sentence: what it changes for an SAP landscape or budget")
    section: Beat = "ecosystem"


# ---------- the Architect's Take ----------
TAKE_FORMATS = ("landscape_impact", "decision_guide", "contrarian", "by_the_numbers", "winners_losers",
                "long_view", "connecting_dots")
TakeFormat = Literal["landscape_impact", "decision_guide", "contrarian", "by_the_numbers", "winners_losers",
                     "long_view", "connecting_dots"]


class TakePlan(BaseModel):
    story_id: str = Field(description="candidate id of the story the Take is about (the week's Signal)")
    format: TakeFormat
    related_ids: list[str] = Field(default_factory=list, description="Other briefing stories to weave in (connecting_dots)")
    angle: str = Field(description="The specific question or argument the Take answers, one sentence")
    intro: str = Field("", description="One line, max 30 words, that opens the issue: the week's thread")


class TakeSection(BaseModel):
    heading: str = Field(description="Short, specific heading written for THIS story (not a stock label)")
    body: str


class Take(BaseModel):
    format: str
    title: str = Field(description="Max 12 words")
    dek: str = Field(description="One-sentence standfirst, max 30 words")
    sections: list[TakeSection]
    watch: list[str] = Field(default_factory=list, description="0-3 concrete things to watch; no odds")
    social_post: str = ""
    seo_description: str = ""
    slug: str = ""


# ---------- Deadline Radar ----------
DeadlineKind = Literal["end_of_mainstream_maintenance", "end_of_extended_maintenance", "retirement",
                       "deprecation", "licensing_window", "release", "price_change", "event", "other"]


class DeadlineProposal(BaseModel):
    item: str = Field(description="What ends, changes or ships, in plain words (max 12 words)")
    product: str = Field(description="SAP product or area, e.g. 'SAP ECC 6.0 (EHP 6-8)'")
    date: str = Field(description="YYYY-MM-DD, or YYYY-MM when only the month is stated")
    kind: DeadlineKind = "other"
    claim_id: str = Field(description="The claim id (C#) whose quote states this date")
    quote: str = Field(description="The words from that claim's quote that state the date, copied exactly")


class DeadlineProposals(BaseModel):
    rows: list[DeadlineProposal] = Field(default_factory=list)


# ---------- LinkedIn pack ----------
class LinkedInPack(BaseModel):
    """Everything posted on LinkedIn for the week, written for the author to paste by hand."""
    share_post: str = Field(description="Tuesday: the text that accompanies the newsletter edition, 80-160 words")
    story_post: str = Field(description="Thursday: a reflective personal post tied to the week's theme, 150-250 words")
    story_needs_input: bool = Field(False, description="True when the story post has [YOUR STORY: ...] gaps to fill")
    carousel_caption: str = Field(description="Saturday: 40-90 words introducing the carousel")
    carousel_title: str = Field("", description="Max 8 words: the cover line of the Saturday carousel")


class SourceRef(BaseModel):
    origin: str
    url: str
    tier: str
    perspective: str = "unclassified"


class EditionStory(BaseModel):
    rank: int
    candidate_id: str
    headline: str
    summary: str
    why_it_matters: str
    confidence: str = Field(description="high / developing (from the evidence gate, never the model)")
    score: float = 0.0
    sources: list[SourceRef] = Field(default_factory=list)
    section: str = ""
    vendor_only: bool = Field(False, description="Only interested parties (vendors) carry it: labelled for readers")
    also_reported: list[SourceRef] = Field(default_factory=list)


class Brief(BaseModel):
    candidate_id: str
    headline: str
    summary: str
    why_it_matters: str


class Edition(BaseModel):
    edition_date: str                      # the run date (drives date checks)
    edition_id: str = ""                   # folder / approval id: "2026-11-16"
    issue_no: int = 1
    run_id: str
    title: str
    description: str
    lead_id: str
    stories: list[EditionStory]
    take: Optional[Take] = None
    take_ids: list[str] = Field(default_factory=list)
    take_from_notes: bool = Field(False, description="True when the Take was written from the author's own notes")
    intro: str = ""
    linkedin: Optional[LinkedInPack] = None
    deadlines_new: list[dict] = Field(default_factory=list, description="Radar rows proposed this week (verified dates)")
    quality: QualityReport
    warnings: list[str] = Field(default_factory=list)
    status: Literal["draft", "published", "rejected"] = "draft"

    @model_validator(mode="after")
    def _default_id(self):
        if not self.edition_id:
            self.edition_id = self.edition_date
        return self

    @property
    def edition_no(self) -> int:
        m = re.fullmatch(r"\d{4}-\d{2}-\d{2}-(\d+)", self.edition_id)
        return int(m.group(1)) if m else 1
