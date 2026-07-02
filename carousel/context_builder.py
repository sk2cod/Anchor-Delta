"""
ContextBuilder — transforms a StoryCard into a prompt-optimised StoryContext
(Blueprint §5.2). The highest-leverage piece of Python in the engine: what
goes into StoryContext directly determines the quality of every downstream
LLM call.

Two responsibilities:
1. Python: trim and structure StoryCard fields into StoryContext
2. LLM: one Haiku call to extract entities, numbers, and quotes
   (Decision #07 — Haiku catches ~95% of entities vs ~70% for regex)

Uses CAROUSEL_ANTHROPIC_API_KEY, not ANTHROPIC_API_KEY — a separate billing
account from the Intelligence Engine pipeline (Decision #40).
"""

import json
import logging
import os
from datetime import date

import anthropic
from dotenv import load_dotenv

from carousel.models import (
    DeltaSummary,
    DominantNumber,
    Entity,
    SourcedQuote,
    StoryCard,
    StoryContext,
    TransmissionSummary,
)

load_dotenv()

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_EXTRACTION_INPUT_CHARS = 2000

EXTRACTION_SYSTEM_PROMPT = """You are a precise information extractor. Extract structured data \
from the provided news intelligence card. Return only valid JSON. \
No preamble, no explanation, no markdown code fences.

Extract:
- quotes: direct quotes with attribution and role of speaker
- entities: named people, companies, agencies, AI models, \
products, and places — mark each as primary or secondary
- numbers: significant figures with label and one-line context

Return this exact JSON structure:
{
  "quotes": [
    {"text": "...", "attribution": "...", "role": "..."}
  ],
  "entities": [
    {"name": "...", "type": "person|company|agency|model|product|place", \
"importance": "primary|secondary"}
  ],
  "numbers": [
    {"value": "...", "label": "...", "context": "..."}
  ]
}

Return empty arrays if nothing found. Never hallucinate."""


class ContextBuildError(Exception):
    pass


def _strip_json_fences(text: str) -> str:
    """Haiku sometimes wraps JSON in ```json ... ``` despite instructions not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _build_transmission_summary(card: StoryCard) -> TransmissionSummary:
    """Compress the transmission's node markdown into 4-6 bullets. Python only."""
    if card.transmission is None:
        return TransmissionSummary(nodes=["No transmission available"] * 4)

    lines = [
        line.strip()
        for line in card.transmission.nodes_markdown.splitlines()
        if line.strip()
    ][:6]

    if len(lines) < 4:
        lines = (lines + ["No transmission available"] * 4)[:4]

    return TransmissionSummary(nodes=lines)


def _extraction_input_text(
    card: StoryCard, latest_delta: DeltaSummary, transmission_summary: TransmissionSummary
) -> str:
    parts = [
        card.umbrella_title,
        card.anchor_text,
        latest_delta.headline,
        latest_delta.tldr,
        "\n".join(transmission_summary.nodes),
    ]
    text = "\n\n".join(p for p in parts if p)
    return text[:MAX_EXTRACTION_INPUT_CHARS]


def _extract_entities_quotes_numbers(
    client: anthropic.Anthropic, text: str
) -> tuple[list[SourcedQuote], list[Entity], list[DominantNumber]]:
    """One Haiku call for extraction. Never raises — falls back to empty lists."""
    try:
        message = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            system=EXTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
    except Exception as e:
        logger.warning("Haiku extraction call failed: %s", e)
        return [], [], []

    usage = getattr(message, "usage", None)
    if usage is not None:
        logger.info(
            "Haiku extraction usage: input_tokens=%s output_tokens=%s",
            usage.input_tokens,
            usage.output_tokens,
        )

    try:
        response_text = _strip_json_fences(message.content[0].text)
        data = json.loads(response_text)
        quotes = [SourcedQuote(**q) for q in data.get("quotes", [])]
        entities = [Entity(**e) for e in data.get("entities", [])]
        numbers = [DominantNumber(**n) for n in data.get("numbers", [])]
        return quotes, entities, numbers
    except Exception as e:
        logger.warning("Failed to parse Haiku extraction response: %s", e)
        return [], [], []


def build_context(card: StoryCard) -> StoryContext:
    """
    Transform a StoryCard into a prompt-optimised StoryContext.
    Makes one Haiku call for entity/number/quote extraction.
    Cost: ~$0.005. Latency: ~1.5s.
    """
    api_key = os.environ.get("CAROUSEL_ANTHROPIC_API_KEY")
    if not api_key:
        raise ContextBuildError(
            "CAROUSEL_ANTHROPIC_API_KEY is not set. This is a separate "
            "billing account from ANTHROPIC_API_KEY (Intelligence Engine "
            "pipeline) — set it in .env before running ContextBuilder."
        )

    if not card.delta_events:
        raise ContextBuildError(f"Card {card.id!r} has no delta_events; cannot build context.")

    if card.domain not in ("world", "finance", "ai_tech"):
        raise ContextBuildError(
            f"Card {card.id!r} has domain={card.domain!r}, which is not one "
            "of 'world', 'finance', 'ai_tech' — StoryContext cannot represent it."
        )

    latest_row = card.delta_events[0]
    latest_delta = DeltaSummary(
        headline=latest_row.headline,
        tldr=latest_row.tldr or latest_row.headline,
        event_date=latest_row.event_date,
    )
    previous_deltas = [
        DeltaSummary(
            headline=row.headline,
            tldr=row.tldr or row.headline,
            event_date=row.event_date,
        )
        for row in card.delta_events[1:3]
    ]

    transmission_summary = _build_transmission_summary(card)
    card_age_days = (date.today() - card.created_at.date()).days

    client = anthropic.Anthropic(api_key=api_key)
    extraction_text = _extraction_input_text(card, latest_delta, transmission_summary)
    quotes, entities, numbers = _extract_entities_quotes_numbers(client, extraction_text)

    return StoryContext(
        umbrella_title=card.umbrella_title,
        anchor_text=card.anchor_text,
        latest_delta=latest_delta,
        previous_deltas=previous_deltas,
        transmission_summary=transmission_summary,
        domain=card.domain,
        card_age_days=card_age_days,
        available_quotes=quotes,
        key_entities=entities,
        dominant_numbers=numbers,
    )
