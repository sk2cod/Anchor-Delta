"""
CarouselWriter — the single LLM creative call (Blueprint §5.4).

Given StoryContext alone, produces all slide text, caption, pinned
comment, and hashtag themes in one Sonnet call with structured JSON output.
The writer decides the carousel's own narrative shape — slide count, beat
boundaries, where a quote earns its own slide — rather than filling a
pre-built slot plan (Decision #67); carousel/planner.py validates that
shape after the fact instead of dictating it beforehand. Voice consistency
requires the model to see the full slide arc in one pass (Decision #02) —
splitting into per-slide calls produces drift and wastes tokens
re-establishing context.

Uses CAROUSEL_ANTHROPIC_API_KEY, not ANTHROPIC_API_KEY — a separate billing
account from the Intelligence Engine pipeline (Decision #40).

write_carousel() also generates the cover slide's AI image (Decision #64)
after the Sonnet call succeeds, via carousel/image_generator.py — a second
provider (OPENAI_API_KEY, gpt-image-1), kept inside this function so the
call site in ui/app.py needs no changes. Image-generation failure never
fails the overall call; the cover slide just renders typography-only.
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from carousel import image_generator, planner
from carousel.models import (
    CarouselSpec,
    GenerationMetadata,
    Slide,
    SlotRole,
    SourcedQuote,
    StoryContext,
)

load_dotenv()

logger = logging.getLogger(__name__)

SONNET_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4000
PROMPT_PATH = Path(__file__).parent / "prompts" / "writer_v2_0.md"
REGEN_PROMPT_PATH = Path(__file__).parent / "prompts" / "regenerate_v1_4.md"

# Sonnet pricing per Blueprint-specified formula (per token, not per 1M).
INPUT_COST_PER_TOKEN = 0.000003
OUTPUT_COST_PER_TOKEN = 0.000015


class CarouselWriteError(Exception):
    pass


class QuoteFabricationError(CarouselWriteError):
    """
    A quote slide's attribution doesn't match a real card speaker
    (Decision #56). Distinct from CarouselWriteError so write_carousel()
    can recognise this specific, recoverable failure and, on the final
    retry, drop the offending slide instead of failing the whole
    carousel (Decision #69) — a quote beat is optional narrative garnish
    (Decision #67), never a show-stopper.
    """

    def __init__(self, message: str, slot_id: str):
        super().__init__(message)
        self.slot_id = slot_id


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


def _build_user_message(context: StoryContext) -> str:
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

    # Decision #64 — the Hook Rules' "name the specific subject" guidance
    # was validated (tests/carousel/test_new_cover.py) against a
    # primary_entity signal. Rather than a fourth LLM call, this is
    # derived from data already in context: the first primary-importance
    # entity from the existing extraction, falling back to the title.
    primary_entity = next(
        (e.name for e in context.key_entities if e.importance == "primary"),
        context.umbrella_title,
    )

    return f"""DOMAIN: {context.domain}

CARD TITLE: {context.umbrella_title}

PRIMARY SUBJECT: {primary_entity}

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
    strict_quotes: bool = True,
) -> CarouselSpec:
    """
    Parse + validate a writer response into a CarouselSpec. Raises on any
    failure — except a fabricated quote attribution when strict_quotes is
    False, in which case that one slide is dropped instead (Decision #69),
    so a bad quote never fails an otherwise-good carousel. strict_quotes
    should be True on the first attempt (so a fabricated quote still
    triggers the normal one-retry path) and False on the retry (so a
    second failure degrades gracefully instead of raising).
    """
    data = json.loads(_strip_json_fences(response_text))

    slides = []
    for slide_data in data["slides"]:
        slide = Slide(**slide_data)
        slide.text_hash = hashlib.md5(
            (slide.headline + slide.body).encode("utf-8")
        ).hexdigest()
        slides.append(slide)

    kept_slides = []
    for slide in slides:
        if slide.quote is not None and not _quote_attribution_matches_card(
            slide.quote.attribution, available_quotes
        ):
            # Decision #56 — code enforces what the prompt already asked for
            # (writer_v1_2.md's ## quote guardrail): never render a quote
            # whose attribution isn't a real, named card speaker. This is
            # deterministic Python judgment, not LLM self-verification —
            # same philosophy as the kicker-None guard in regenerate_slide().
            if strict_quotes:
                raise QuoteFabricationError(
                    f"Slide {slide.slot_id!r} has a quote attributed to "
                    f"{slide.quote.attribution!r}, which does not match any "
                    "real speaker in this card's sourced quotes — refusing "
                    "to render a fabricated quote.",
                    slot_id=slide.slot_id,
                )
            logger.warning(
                "Dropping slide %r — quote attributed to %r still doesn't "
                "match any real card speaker after retry (Decision #69).",
                slide.slot_id, slide.quote.attribution,
            )
            continue
        kept_slides.append(slide)
    slides = kept_slides

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

    spec = CarouselSpec(
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

    # Decision #67 — the writer now decides the carousel's own shape;
    # this is the deterministic Python check that replaces the old
    # pre-write slot plan, feeding the same one-retry mechanism as the
    # quote-fabrication guard above.
    planner.validate_carousel_shape(spec)

    return spec


def _attach_cover_image(spec: CarouselSpec, context: StoryContext) -> None:
    """
    Decision #64 — generate the cover slide's AI image and attach it to
    the hook slide, mutating spec in place. Never raises: image
    generation failure just leaves image_asset=None, and the Cover
    template degrades to typography-only (carousel/image_generator.py's
    own contract — see its docstring).
    """
    hook_slide = next((s for s in spec.slides if s.role == SlotRole.hook), None)
    if hook_slide is None:
        return
    hook_slide.image_asset = image_generator.generate_cover_image(
        visual_subject=context.visual_subject,
        is_person=context.visual_subject_is_person,
        domain=context.domain,
    )


def write_carousel(
    context: StoryContext,
    card_id: str,
    prompt_version: str = "writer-v2.0",
) -> CarouselSpec:
    """
    Single Sonnet call producing all slide text, caption, pinned comment,
    and hashtag themes — then one gpt-image-1 call (Decision #64,
    carousel/image_generator.py) generating the cover slide's AI image.
    The writer decides the carousel's own shape (Decision #67) — no
    pre-built slot plan is passed in; carousel/planner.py validates the
    result afterward.
    Cost: ~$0.025-0.035 (Sonnet) + ~$0.01-0.02 (gpt-image-1, "high"
    quality). Latency: 4-7 seconds (Sonnet) + up to ~45s bounded (image).
    Uses CAROUSEL_ANTHROPIC_API_KEY for text, OPENAI_API_KEY for the image.
    """
    api_key = os.environ.get("CAROUSEL_ANTHROPIC_API_KEY")
    if not api_key:
        raise CarouselWriteError(
            "CAROUSEL_ANTHROPIC_API_KEY is not set. This is a separate "
            "billing account from ANTHROPIC_API_KEY (Intelligence Engine "
            "pipeline) — set it in .env before running CarouselWriter."
        )

    system_prompt = _load_system_prompt()
    user_message = _build_user_message(context)
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
        spec = _build_spec_from_response(
            response_text, card_id, card_version, prompt_version, message.usage,
            context.available_quotes, strict_quotes=True,
        )
    except Exception as first_error:
        # One automatic retry, with the validation error appended to the prompt.
        retry_note = str(first_error)
        if isinstance(first_error, QuoteFabricationError):
            # Decision #69 — a generic "fix it" message let the model try a
            # second, still-wrong attribution instead of the right recovery
            # (drop the quote beat). Be explicit about the actual fix.
            retry_note += (
                "\n\nDo not attempt another attribution for this quote. "
                "Remove the dedicated quote-role beat entirely. If the "
                "finding still matters, fold it into a regular beat's own "
                "prose as plain narrative language instead of the "
                "structured quote field — that never needs to match "
                "AVAILABLE QUOTES verbatim."
            )
        elif isinstance(first_error, planner.WordBudgetExceededError):
            # Decision #70 — a generic "fix it" message let a retried beat
            # get LONGER, not shorter (34 -> 35 words on a real generation).
            # Trimming words in place isn't reliably how the model recovers
            # from this; splitting the overloaded beat into two is.
            retry_note += (
                "\n\nDo not try to trim this beat further — that has "
                "already failed once. Split it into two beats instead: "
                "keep each piece of content (the quote, the statistic, the "
                "second idea — whatever is making this beat too long) but "
                "give it its own beat with its own headline, rather than "
                "compressing everything into one. There is slide-count "
                "headroom for this (maximum 10 total)."
            )
        retry_message = (
            user_message
            + "\n\nYour previous response failed validation with this error:\n"
            + retry_note + "\n\n"
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
            spec = _build_spec_from_response(
                retry_response.content[0].text,
                card_id,
                card_version,
                prompt_version,
                retry_response.usage,
                context.available_quotes,
                strict_quotes=False,
            )
        except Exception as second_error:
            raise CarouselWriteError(
                f"Writer output failed validation twice. First error: {first_error}. "
                f"Second error: {second_error}."
            ) from second_error

    _attach_cover_image(spec, context)
    return spec


def regenerate_slide(
    spec: CarouselSpec,
    slot_id: str,
    domain: str,
    card_id: str,
    instruction: Optional[str] = None,
    prompt_version: str = "regenerate-v1.4",
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
    if target.role == SlotRole.quote:
        # Decision #63 — same pattern as the kicker fix above. This is
        # also the only real, already-validated quote available here:
        # regenerate_slide() has no access to the full StoryContext (only
        # spec, at the UI call site), so target.quote — which already
        # passed the Decision #56 anti-fabrication guard when the
        # carousel was first generated — is the anti-fabrication ground
        # truth for this regenerate, not a fresh available_quotes list.
        if target.quote is not None:
            user_message += (
                f'current quote: "{target.quote.text}" '
                f"— {target.quote.attribution} ({target.quote.role})\n"
            )
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
            # Decision #64 — a text-only regenerate must not silently
            # drop the cover slide's AI-generated image; preserve it
            # unchanged (Model B has no image-generation capability at
            # all, by design — regenerating the image is out of scope).
            image_asset=target.image_asset,
            text_hash=hashlib.md5(
                (data["headline"] + data.get("body", "")).encode()
            ).hexdigest(),
        )
        if target.role == SlotRole.hook and not new_slide.body:
            # Decision #64 — replaces the old kicker-None guard (Decision
            # #54; the Cover template no longer renders a kicker at all).
            # The sub-heading (body) is now load-bearing narrative
            # content, not decoration — a blank one is a stronger content
            # failure than a blank kicker ever was, since it's half of
            # the "one continuous thought" the headline sets up.
            raise CarouselWriteError(
                "Regenerated cover/hook slide is missing a sub-heading "
                "(cover slides must not have body: empty)"
            )
        if target.role == SlotRole.quote:
            # Decision #63 — same pattern as the kicker-None guard above,
            # plus the Decision #56 anti-fabrication check. A quote-role
            # slide with quote=None is a validation failure (it would
            # render with no quote at all). The attribution check reuses
            # target.quote — the only real, already-validated quote this
            # function has access to (see the context-building comment
            # above) — as the anti-fabrication ground truth, exactly the
            # same deterministic-Python-judgment philosophy as
            # _build_spec_from_response()'s check on the full writer path.
            if new_slide.quote is None:
                raise CarouselWriteError(
                    "Regenerated quote slide is missing a quote "
                    "(quote slides must not have quote: null)"
                )
            known_quotes = [target.quote] if target.quote is not None else []
            if not _quote_attribution_matches_card(new_slide.quote.attribution, known_quotes):
                raise CarouselWriteError(
                    f"Regenerated quote is attributed to "
                    f"{new_slide.quote.attribution!r}, which does not match "
                    "the real speaker already on this card — refusing to "
                    "render a fabricated quote."
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
