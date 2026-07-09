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
"""

from carousel.models import CarouselSpec, SlotRole

MIN_SLIDES = 5  # user-stated minimum — no padding below this
MAX_SLIDES = 10  # Instagram's actual platform limit on carousel items,
# not an arbitrary number — matches the old system's own ceiling case
# (8 base + 1 proof + 1 quote = 10).
MAX_QUOTE_SLIDES = 2  # a quote only earns its own beat when it's strong
# enough to stand alone; more than a couple in one carousel means quotes
# are being used as filler, not as the sharpest possible line.


class PlannerValidationError(Exception):
    pass


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
