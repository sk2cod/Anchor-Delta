"""
CarouselWriter — the single LLM creative call (Blueprint §5.4).

Given StoryContext and SlotPlan, produces all slide text, caption, pinned
comment, and hashtag themes in one Sonnet call with structured JSON output.
Voice consistency requires the model to see the full slide arc in one pass
(Decision #02) — splitting into per-slide calls produces drift and wastes
tokens re-establishing context.

Uses CAROUSEL_ANTHROPIC_API_KEY, not ANTHROPIC_API_KEY — a separate billing
account from the Intelligence Engine pipeline (Decision #40).
"""

import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from carousel.models import (
    CarouselSpec,
    GenerationMetadata,
    Slide,
    SlotPlan,
    SlotRole,
    SourcedQuote,
    StoryContext,
)

load_dotenv()

SONNET_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4000
PROMPT_PATH = Path(__file__).parent / "prompts" / "writer_v1_5.md"
REGEN_PROMPT_PATH = Path(__file__).parent / "prompts" / "regenerate_v1_1.md"

# Sonnet pricing per Blueprint-specified formula (per token, not per 1M).
INPUT_COST_PER_TOKEN = 0.000003
OUTPUT_COST_PER_TOKEN = 0.000015


class CarouselWriteError(Exception):
    pass


def _load_system_prompt() -> str:
    if not PROMPT_PATH.exists():
        raise CarouselWriteError(f"Writer prompt not found at {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def _strip_json_fences(text: str) -> str:
    """The writer sometimes wraps JSON in ```json ... ``` despite instructions not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _build_user_message(context: StoryContext, slot_plan: SlotPlan) -> str:
    previous_developments = "\n".join(
        f"- {d.headline} — {d.tldr}" for d in context.previous_deltas
    ) or "(none)"

    transmission = "\n".join(f"- {node}" for node in context.transmission_summary.nodes)

    quotes = "\n".join(
        f'- "{q.text}" — {q.attribution} ({q.role})' for q in context.available_quotes
    ) or "(none)"

    entities = "\n".join(
        f"- {e.name} ({e.type}, {e.importance})" for e in context.key_entities
    ) or "(none)"

    numbers = "\n".join(
        f"- {n.value} — {n.label}: {n.context}" for n in context.dominant_numbers
    ) or "(none)"

    slots = "\n".join(f"- {s.slot_id} ({s.role.value})" for s in slot_plan.slots)

    return f"""DOMAIN: {context.domain}

CARD TITLE: {context.umbrella_title}

ANCHOR:
{context.anchor_text}

LATEST DEVELOPMENT ({context.latest_delta.event_date}):
{context.latest_delta.headline}
{context.latest_delta.tldr}

PREVIOUS DEVELOPMENTS:
{previous_developments}

TRANSMISSION (causal chain):
{transmission}

AVAILABLE QUOTES:
{quotes}

KEY ENTITIES:
{entities}

KEY NUMBERS:
{numbers}

SLOT PLAN (write exactly these slides in this order):
{slots}

CARD AGE: {context.card_age_days} days"""


def _quote_attribution_matches_card(attribution: str, available_quotes: list[SourcedQuote]) -> bool:
    """
    Deterministic check (Decision #03/#56) — a quote's attribution must
    correspond to a real speaker from the card's own sourced quotes.
    Matched on name, leniently (case-insensitive substring both ways) so
    a shortened or fuller form of a real name still matches, but a
    placeholder like "Article text" or "Editorial conclusion" never
    accidentally does.
    """
    candidate = (attribution or "").strip().lower()
    if not candidate:
        return False
    for q in available_quotes:
        real = (q.attribution or "").strip().lower()
        if real and (candidate == real or candidate in real or real in candidate):
            return True
    return False


def _build_spec_from_response(
    response_text: str,
    card_id: str,
    card_version: str,
    prompt_version: str,
    usage,
    available_quotes: list[SourcedQuote],
) -> CarouselSpec:
    """Parse + validate a writer response into a CarouselSpec. Raises on any failure."""
    data = json.loads(_strip_json_fences(response_text))

    slides = []
    for slide_data in data["slides"]:
        slide = Slide(**slide_data)
        slide.text_hash = hashlib.md5(
            (slide.headline + slide.body).encode("utf-8")
        ).hexdigest()
        slides.append(slide)

    for slide in slides:
        if slide.quote is not None and not _quote_attribution_matches_card(
            slide.quote.attribution, available_quotes
        ):
            # Decision #56 — code enforces what the prompt already asked for
            # (writer_v1_2.md's ## quote guardrail): never render a quote
            # whose attribution isn't a real, named card speaker. This is
            # deterministic Python judgment, not LLM self-verification —
            # same philosophy as the kicker-None guard in regenerate_slide().
            raise CarouselWriteError(
                f"Slide {slide.slot_id!r} has a quote attributed to "
                f"{slide.quote.attribution!r}, which does not match any real "
                "speaker in this card's sourced quotes — refusing to render "
                "a fabricated quote."
            )

    cost_usd = (
        usage.input_tokens * INPUT_COST_PER_TOKEN
        + usage.output_tokens * OUTPUT_COST_PER_TOKEN
    )

    generation_metadata = GenerationMetadata(
        model=SONNET_MODEL,
        created_at=datetime.utcnow(),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost_usd,
    )

    return CarouselSpec(
        script_id=uuid.uuid4(),
        card_id=card_id,
        card_version=card_version,
        prompt_version=prompt_version,
        slides=slides,
        caption=data["caption"],
        pinned_comment=data["pinned_comment"],
        hashtag_themes=data["hashtag_themes"],
        generation_metadata=generation_metadata,
    )


def write_carousel(
    context: StoryContext,
    slot_plan: SlotPlan,
    card_id: str,
    prompt_version: str = "writer-v1.5",
) -> CarouselSpec:
    """
    Single Sonnet call producing all slide text, caption,
    pinned comment, and hashtag themes.
    Cost: ~$0.025-0.035. Latency: 4-7 seconds.
    Uses CAROUSEL_ANTHROPIC_API_KEY.
    """
    api_key = os.environ.get("CAROUSEL_ANTHROPIC_API_KEY")
    if not api_key:
        raise CarouselWriteError(
            "CAROUSEL_ANTHROPIC_API_KEY is not set. This is a separate "
            "billing account from ANTHROPIC_API_KEY (Intelligence Engine "
            "pipeline) — set it in .env before running CarouselWriter."
        )

    system_prompt = _load_system_prompt()
    user_message = _build_user_message(context, slot_plan)
    card_version = hashlib.md5(
        (context.anchor_text + context.latest_delta.headline).encode("utf-8")
    ).hexdigest()

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        raise CarouselWriteError("Sonnet writer call failed") from e

    response_text = message.content[0].text

    try:
        return _build_spec_from_response(
            response_text, card_id, card_version, prompt_version, message.usage,
            context.available_quotes,
        )
    except Exception as first_error:
        # One automatic retry, with the validation error appended to the prompt.
        retry_message = (
            user_message
            + "\n\nYour previous response failed validation with this error:\n"
            + f"{first_error}\n\n"
            + "Return corrected JSON only, matching the required structure exactly."
        )
        try:
            retry_response = client.messages.create(
                model=SONNET_MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": retry_message}],
            )
        except Exception as e:
            raise CarouselWriteError("Sonnet writer retry call failed") from e

        try:
            return _build_spec_from_response(
                retry_response.content[0].text,
                card_id,
                card_version,
                prompt_version,
                retry_response.usage,
                context.available_quotes,
            )
        except Exception as second_error:
            raise CarouselWriteError(
                f"Writer output failed validation twice. First error: {first_error}. "
                f"Second error: {second_error}."
            ) from second_error


def regenerate_slide(
    spec: CarouselSpec,
    slot_id: str,
    domain: str,
    card_id: str,
    instruction: Optional[str] = None,
    prompt_version: str = "regenerate-v1.1",
) -> Slide:
    """
    Model B — targeted slide regenerate.
    One Sonnet call replacing a single slide.
    Locked (manually_edited=True) slides are never passed
    as the target.
    Cost: ~$0.008. Latency: 3-5 seconds.
    """
    if not REGEN_PROMPT_PATH.exists():
        raise CarouselWriteError(f"Regenerate prompt not found at {REGEN_PROMPT_PATH}")
    system_prompt = REGEN_PROMPT_PATH.read_text(encoding="utf-8")

    target = next(
        (s for s in spec.slides if s.slot_id == slot_id),
        None,
    )
    if target is None:
        raise CarouselWriteError(f"slot_id {slot_id} not found")
    if target.manually_edited:
        raise CarouselWriteError(
            f"Slide {slot_id} is locked (manually_edited=True)"
        )

    other_slides_lines = []
    for s in spec.slides:
        if s.slot_id == slot_id:
            continue
        line = f"[{s.slot_id}] {s.headline}"
        if s.body:
            line += f"\n{s.body}"
        other_slides_lines.append(line)
    other_slides = "\n".join(other_slides_lines)

    user_message = (
        f"DOMAIN: {domain}\n"
        f"CARD: {spec.card_id}\n"
        f"EXISTING CAROUSEL (do not change these slides):\n"
        f"{other_slides}\n"
        f"SLIDE TO REPLACE:\n"
        f"slot_id: {slot_id}\n"
        f"role: {target.role.value}\n"
        f"current headline: {target.headline}\n"
        f"current body: {target.body}\n"
    )
    if target.role == SlotRole.hook:
        # Decision #54 — cover/hook slide's kicker must survive a targeted
        # regenerate; pass the existing value through as context so the
        # model returns it (or a deliberate variant) instead of the field
        # going unset.
        user_message += f"current kicker: {target.kicker}\n"
    if instruction:
        user_message += f"INSTRUCTION FROM EDITOR: {instruction}\n"
    else:
        user_message += "No specific instruction — write a stronger version.\n"
    user_message += "Write one replacement slide only."

    api_key = os.environ.get("CAROUSEL_ANTHROPIC_API_KEY")
    if not api_key:
        raise CarouselWriteError(
            "CAROUSEL_ANTHROPIC_API_KEY is not set. This is a separate "
            "billing account from ANTHROPIC_API_KEY (Intelligence Engine "
            "pipeline) — set it in .env before running CarouselWriter."
        )

    client = anthropic.Anthropic(api_key=api_key)

    def _call_and_parse(msg: str) -> Slide:
        try:
            response = client.messages.create(
                model=SONNET_MODEL,
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": msg}],
            )
        except Exception as e:
            raise CarouselWriteError("Sonnet regenerate call failed") from e

        response_text = response.content[0].text
        data = json.loads(_strip_json_fences(response_text))
        new_slide = Slide(
            slot_id=slot_id,
            role=target.role,
            headline=data["headline"],
            body=data.get("body", ""),
            emphasis_word=data.get("emphasis_word"),
            kicker=data.get("kicker"),
            quote=data.get("quote"),
            dominant_numbers=data.get("dominant_numbers"),
            factsheet_title=data.get("factsheet_title"),
            notes=data.get("notes"),
            manually_edited=False,
            text_hash=hashlib.md5(
                (data["headline"] + data.get("body", "")).encode()
            ).hexdigest(),
        )
        if target.role == SlotRole.hook and not new_slide.kicker:
            # Decision #54 — a cover/hook slide with kicker=None is a
            # validation failure, not a silently-accepted result: it
            # would render with a blank kicker line.
            raise CarouselWriteError(
                "Regenerated cover/hook slide is missing a kicker "
                "(cover slides must not have kicker: null)"
            )
        cost_usd = (
            response.usage.input_tokens * INPUT_COST_PER_TOKEN
            + response.usage.output_tokens * OUTPUT_COST_PER_TOKEN
        )
        _ = cost_usd  # tracked; caller can log if needed
        return new_slide

    try:
        return _call_and_parse(user_message)
    except Exception as first_error:
        retry_message = (
            user_message
            + f"\n\nYour previous response failed with: {first_error}\n"
            + "Return valid JSON only, matching the required structure exactly."
        )
        try:
            return _call_and_parse(retry_message)
        except Exception as second_error:
            raise CarouselWriteError(
                f"Regenerate failed twice. First: {first_error}. "
                f"Second: {second_error}."
            ) from second_error
