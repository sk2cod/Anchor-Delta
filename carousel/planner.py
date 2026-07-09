"""
CarouselPlanner — validates carousel shape after writing (Decision #67).

Before Decision #67: this module decided slide count and role
deterministically in Python *before* the writer ran (Decision #03, #13 —
"the LLM never decides slide count or structure"), via keyword-matching
against the transmission's nodes. The writer was then instructed to fill
exactly that pre-built structure.

That guarantee is deliberately relaxed as of Decision #67: viewer feedback
was that carousels built from a fixed slot structure read as disconnected
facts, not a story. The writer now reads the full StoryContext itself and
decides the story's own natural shape — how many beats it needs, where
quotes and numbers land — rather than a Python keyword-hint proxy trying
to notice that for it.

This module's job inverts to match: instead of deciding structure before
writing, it validates the writer's chosen structure after writing. Same
"deterministic Python judgment, not LLM self-verification" philosophy as
the existing quote-fabrication guard in writer.py — just applied to shape
instead of content. Called from writer.py's _build_spec_from_response(),
feeding the existing one-retry mechanism on failure.

Word-budget enforcement added (Decision #68): writer_v2_0.md always
stated per-role word budgets, but nothing in code ever checked them —
a real generation (the "crypto goes mainstream" world card) ran every
beat body at 48-56 words against a stated ≤40 cap, and nothing caught
it. The budgets below are the same "stated in the prompt, enforced in
code" pattern as the shape checks already in this file.

Tolerance added (Decision #69): a real generation (the "Claude's
Hidden Mind" ai_tech card) hit a beat body at 33-34 words against the
30-word target on both the first attempt and the retry — a 10-13%
miss, not a broken response. WORD_BUDGET_TOLERANCE lets every word
check accept a small overshoot rather than hard-failing (and burning
the one retry) on a near-miss; the numbers below stay the target the
prompt aims for, the tolerance is applied only at check time.
"""

import math

from carousel.models import CarouselSpec, SlotRole

WORD_BUDGET_TOLERANCE = 1.10  # Decision #69 — 10% overshoot allowed
# before a word-count check actually rejects. Applied via _max_words().

MIN_SLIDES = 5  # user-stated minimum — no padding below this
MAX_SLIDES = 10  # Instagram's actual platform limit on carousel items,
# not an arbitrary number — matches the old system's own ceiling case
# (8 base + 1 proof + 1 quote = 10).
MAX_QUOTE_SLIDES = 2  # a quote only earns its own beat when it's strong
# enough to stand alone; more than a couple in one carousel means quotes
# are being used as filler, not as the sharpest possible line.

# Decision #68 — word budgets, matching writer_v2_0.md's Hard Constraints
# table exactly. MAX_BEAT_BODY_WORDS tightened from an earlier 40 (see
# module docstring) to actually hit a scannable line count once rendered.
MAX_HOOK_HEADLINE_WORDS = 8
MAX_HOOK_BODY_WORDS = 15
MAX_BEAT_HEADLINE_WORDS = 14
MAX_BEAT_BODY_WORDS = 30


class PlannerValidationError(Exception):
    pass


class WordBudgetExceededError(PlannerValidationError):
    """
    A slide's headline or body is over its word budget, even with
    tolerance (Decision #69). Distinct from PlannerValidationError so
    writer.py's retry can give a targeted hint — split the beat instead
    of cutting content (Decision #70) — rather than a generic "fix it"
    message, which real generations showed doesn't reliably work (a
    retried beat went 34 -> 35 words, getting worse, not better).
    """

    def __init__(self, message: str, slot_id: str):
        super().__init__(message)
        self.slot_id = slot_id


def _word_count(text: str) -> int:
    return len(text.split())


def _max_words(target: int) -> int:
    """Target word budget with Decision #69's tolerance applied."""
    return math.ceil(target * WORD_BUDGET_TOLERANCE)


def validate_carousel_shape(spec: CarouselSpec) -> None:
    """
    Deterministic post-write shape check. Raises PlannerValidationError on
    any violation; never mutates spec. Pure Python. No LLM. No I/O.
    Cost: $0. Latency: <1ms.
    """
    slides = spec.slides

    if not slides:
        raise PlannerValidationError("Carousel has no slides.")

    if slides[0].role != SlotRole.hook:
        raise PlannerValidationError(
            f"First slide must have role 'hook', got {slides[0].role.value!r}."
        )

    if slides[-1].role != SlotRole.cta:
        raise PlannerValidationError(
            f"Last slide must have role 'cta', got {slides[-1].role.value!r}."
        )

    if not (MIN_SLIDES <= len(slides) <= MAX_SLIDES):
        raise PlannerValidationError(
            f"Carousel has {len(slides)} slides; must be between "
            f"{MIN_SLIDES} and {MAX_SLIDES}."
        )

    quote_count = sum(1 for s in slides if s.role == SlotRole.quote)
    if quote_count > MAX_QUOTE_SLIDES:
        raise PlannerValidationError(
            f"Carousel has {quote_count} dedicated quote slides; at most "
            f"{MAX_QUOTE_SLIDES} allowed. Weave weaker quotes inline into "
            "beat prose instead of giving them their own slide."
        )

    numbers_slides = [s.slot_id for s in slides if s.dominant_numbers]
    if numbers_slides:
        raise PlannerValidationError(
            "No dedicated numbers/fact-sheet slides allowed — found "
            f"dominant_numbers populated on: {numbers_slides}. Weave "
            "numbers into the beat's own prose instead."
        )

    for slide in slides:
        if slide.role == SlotRole.hook:
            headline_words = _word_count(slide.headline)
            if headline_words > _max_words(MAX_HOOK_HEADLINE_WORDS):
                raise WordBudgetExceededError(
                    f"Hook headline is {headline_words} words; target is "
                    f"≤{MAX_HOOK_HEADLINE_WORDS} (allowing up to "
                    f"{_max_words(MAX_HOOK_HEADLINE_WORDS)} with tolerance).",
                    slot_id=slide.slot_id,
                )
            body_words = _word_count(slide.body)
            if body_words > _max_words(MAX_HOOK_BODY_WORDS):
                raise WordBudgetExceededError(
                    f"Hook sub-heading is {body_words} words; target is "
                    f"≤{MAX_HOOK_BODY_WORDS} (allowing up to "
                    f"{_max_words(MAX_HOOK_BODY_WORDS)} with tolerance).",
                    slot_id=slide.slot_id,
                )
        elif slide.role == SlotRole.beat:
            headline_words = _word_count(slide.headline)
            if headline_words > _max_words(MAX_BEAT_HEADLINE_WORDS):
                raise WordBudgetExceededError(
                    f"Beat {slide.slot_id!r} headline is {headline_words} "
                    f"words; target is ≤{MAX_BEAT_HEADLINE_WORDS} (allowing "
                    f"up to {_max_words(MAX_BEAT_HEADLINE_WORDS)} with "
                    "tolerance).",
                    slot_id=slide.slot_id,
                )
            body_words = _word_count(slide.body)
            if body_words > _max_words(MAX_BEAT_BODY_WORDS):
                raise WordBudgetExceededError(
                    f"Beat {slide.slot_id!r} body is {body_words} words; "
                    f"target is ≤{MAX_BEAT_BODY_WORDS} (allowing up to "
                    f"{_max_words(MAX_BEAT_BODY_WORDS)} with tolerance). "
                    "Split into two beats instead of cutting content — "
                    "there is slide-count headroom for this.",
                    slot_id=slide.slot_id,
                )
