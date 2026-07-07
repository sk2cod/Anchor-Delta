"""
Pydantic contracts for the Instagram Carousel Engine.

This module is the spine of the carousel engine (Blueprint §6). Every
stage — ContextBuilder, CarouselPlanner, CarouselWriter, LayoutPicker,
SlideRenderer, PostAssembler — reads from or writes to these models.
Pure data contracts only; no business logic lives here (Decision #3).

Boundary rule (Decision #41): carousel/ reads from pipeline/ and db/,
never modifies them. See the StoryCard note below for the one
deviation this file takes from that rule.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# StoryCard — read-side input to CardLoader / ContextBuilder
# ---------------------------------------------------------------------------
#
# DEVIATION FROM BOUNDARY RULE (Decision #41): the rule permits importing
# StoryCard and its dependent models from pipeline/models.py. pipeline/models.py
# has no such model — it only contains LLM extraction/routing DTOs
# (RouteResult, ExtractionResult, NewCardResult, DeltaUpdateResult), not a
# persisted-card contract. There is nothing to import. A minimal StoryCard is
# defined here instead, mirroring the `cards`, `delta_events`, and
# `transmissions` tables in db/schema.sql exactly (field names match
# db/cards.py, db/delta_events.py, db/transmissions.py). This model is
# carousel-only, read-only, and never written back to pipeline/ or db/.


class DeltaEvent(BaseModel):
    """One append-only row from delta_events, scoped to a single card."""

    id: str
    event_date: date
    headline: str
    what_happened: str
    dialogue: list[dict] = Field(default_factory=list)  # raw jsonb passthrough
    tldr: Optional[str] = None
    created_at: datetime


class Transmission(BaseModel):
    """The single transmissions row for a card (one per card, upsert-only)."""

    chain_latex: str
    nodes_markdown: str
    updated_at: datetime


class StoryCard(BaseModel):
    """A fully-loaded card: cards + its delta_events + its transmission."""

    id: str
    domain: str
    umbrella_title: str
    anchor_text: str
    is_archived: bool
    created_at: datetime
    last_delta_at: datetime
    delta_events: list[DeltaEvent] = Field(default_factory=list)
    transmission: Optional[Transmission] = None


# ---------------------------------------------------------------------------
# 1. Supporting value objects
# ---------------------------------------------------------------------------


class DeltaSummary(BaseModel):
    """A single delta event, compressed for writer input."""

    headline: str
    tldr: str
    event_date: date


class TransmissionSummary(BaseModel):
    """The card's causal chain, compressed to bullets for writer input."""

    nodes: list[str] = Field(min_length=4, max_length=6)


class SourcedQuote(BaseModel):
    """A quote available to the writer, with attribution."""

    text: str
    attribution: str
    role: str  # e.g. "Russian President"


class Entity(BaseModel):
    """A named entity extracted from the card (Decision #7)."""

    name: str
    type: Literal["person", "company", "agency", "model", "product", "place"]
    importance: Literal["primary", "secondary"]


class DominantNumber(BaseModel):
    """A figure worth surfacing on a Number-template slide."""

    value: str  # rendered string e.g. "$2.3T", "1,430"
    label: str  # e.g. "dead"
    context: str  # one-line explanation


class GenerationMetadata(BaseModel):
    """Cost and provenance for a single CarouselSpec generation."""

    model: str
    created_at: datetime
    input_tokens: int
    output_tokens: int
    cost_usd: float


# ---------------------------------------------------------------------------
# 2. StoryContext — input to CarouselWriter
# ---------------------------------------------------------------------------


class StoryContext(BaseModel):
    """Everything the writer needs, trimmed and shaped by ContextBuilder."""

    umbrella_title: str
    anchor_text: str
    latest_delta: DeltaSummary
    previous_deltas: list[DeltaSummary] = Field(default_factory=list, max_length=2)
    transmission_summary: TransmissionSummary
    domain: Literal["world", "finance", "ai_tech"]
    card_age_days: int
    available_quotes: list[SourcedQuote] = Field(default_factory=list)
    key_entities: list[Entity] = Field(default_factory=list)
    dominant_numbers: list[DominantNumber] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3. SlotPlan — input to CarouselWriter
# ---------------------------------------------------------------------------


class SlotRole(str, Enum):
    """Structural role a slide plays within the carousel (Decision #13)."""

    hook = "hook"
    setup = "setup"
    event = "event"
    pivot = "pivot"
    mechanism = "mechanism"
    concept = "concept"
    proof = "proof"
    quote = "quote"  # dedicated quote slot — Decision #55
    contrast = "contrast"
    payoff = "payoff"
    cta = "cta"


class Slot(BaseModel):
    """One planned slide position, assigned deterministically by CarouselPlanner."""

    slot_id: str  # stable role-based id, e.g. "hook", "timeline_1"
    role: SlotRole
    is_optional: bool


class SlotPlan(BaseModel):
    """The deterministic slot structure the writer fills (Decision #13)."""

    slots: list[Slot]


# ---------------------------------------------------------------------------
# 4. ImageAsset — forward-compatibility seam for v1.5
# ---------------------------------------------------------------------------


class ImageAsset(BaseModel):
    """SEAM v1.5 — portrait template support. Inert until v1.5 ships."""

    source: Literal["wikimedia", "upload", "ai_generated"]
    url: str
    treatment: Literal["duotone", "high_contrast", "raw"]
    credit: Optional[str] = None


# ---------------------------------------------------------------------------
# 5. Slide — the most carefully designed model
# ---------------------------------------------------------------------------


class Slide(BaseModel):
    """One slide's content, independent of its visual template."""

    slot_id: str  # matches SlotPlan, e.g. "pivot"
    role: SlotRole
    headline: str  # <=8 words for hook, <=14 words otherwise
    body: str = ""  # <=25 words
    emphasis_word: Optional[str] = None  # single word for accent treatment
    kicker: Optional[str] = None  # Cover template only — umbrella_title-derived line (Decision #53)
    quote: Optional[SourcedQuote] = None  # set when slide IS a quote
    dominant_number: Optional[DominantNumber] = None  # set when slide IS a number
    text_hash: str = ""  # populated by Python after creation, for render cache
    manually_edited: bool = False  # true once user has edited inline (Decision #16)
    # SEAM v1.5 — portrait template support
    image_asset: Optional[ImageAsset] = None
    # SEAM v2 — Reels companion
    audio_clip_id: Optional[str] = None
    # SEAM v2 — motion direction
    animation_hint: Optional[str] = None
    notes: Optional[str] = None  # free-text editor notes


# ---------------------------------------------------------------------------
# 6. CarouselSpec — load-bearing output from CarouselWriter
# ---------------------------------------------------------------------------


class CarouselSpec(BaseModel):
    """
    The single most important model in the system. Every downstream
    component reads it; every future feature attaches to it here.
    Schema-versioned from day one (Decision #34).
    """

    schema_version: str = "1.0"
    script_id: UUID = Field(default_factory=uuid4)
    card_id: str
    card_version: str  # hash of card content at generation time
    prompt_version: str  # e.g. "writer-v3.2"
    slides: list[Slide]
    caption: str
    pinned_comment: str
    hashtag_themes: list[str]  # themes, NOT hashtags (Decision #31)
    generation_metadata: GenerationMetadata


# ---------------------------------------------------------------------------
# 7. LayoutChoice and EnrichedSlide — output from LayoutPicker
# ---------------------------------------------------------------------------


class TemplateID(str, Enum):
    """The eight active v1.0 template archetypes (Blueprint §10)."""

    statement = "statement"
    number = "number"
    quote = "quote"
    timeline = "timeline"
    concept = "concept"
    hook = "hook"  # superseded by `cover` for the hook role in v1.0 (Decision #53); retained, unused
    cover = "cover"  # slide-1 hook role — bottom-anchored magazine-cover treatment (Decision #53)
    cta = "cta"
    portrait = "portrait"  # SEAM v1.5 — inert in v1.0


class TextSizeClass(str, Enum):
    """Coarse text-density bucket used to pick font-size variants."""

    xl = "xl"
    l = "l"
    m = "m"
    s = "s"


class LayoutChoice(BaseModel):
    """Deterministic rendering decisions for one slide (Decision #3)."""

    template_id: TemplateID
    text_size_class: TextSizeClass
    accent_colour: str  # hex
    theme_variant: Literal["dark", "light"] = "dark"


class EnrichedSlide(BaseModel):
    """A Slide paired with the LayoutChoice LayoutPicker made for it."""

    slide: Slide
    layout: LayoutChoice


class EnrichedSpec(BaseModel):
    """Same as CarouselSpec, but every slide is wrapped with its layout."""

    spec: CarouselSpec
    slides: list[EnrichedSlide]


# ---------------------------------------------------------------------------
# 8. Carousel — persisted record
# ---------------------------------------------------------------------------


class CarouselStatus(str, Enum):
    """Lifecycle state of a persisted carousel (Blueprint §7)."""

    draft = "draft"
    approved = "approved"
    exported = "exported"
    published = "published"  # SEAM v2


class Carousel(BaseModel):
    """The record persisted to the `carousels` Supabase table."""

    id: UUID = Field(default_factory=uuid4)
    card_id: str
    card_version: str
    spec: CarouselSpec  # stored as JSONB in Supabase
    slide_paths: list[str]  # paths to rendered PNGs
    final_caption: str  # LLM caption + footer
    final_hashtags: list[str]
    pinned_comment: str
    status: CarouselStatus = CarouselStatus.draft
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved_at: Optional[datetime] = None
    exported_at: Optional[datetime] = None
    published_at: Optional[datetime] = None  # SEAM v2
