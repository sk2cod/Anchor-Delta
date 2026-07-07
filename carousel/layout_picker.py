"""
LayoutPicker — assigns a layout template and styling to each slide
(Blueprint §5.5).

Deterministic Python only — template selection is Python's job, not the
LLM's (Decision #03). One accent per carousel, derived from domain
(Decision #25, #44). Theme variant is always "dark" in v1.0 (Decision #26).
"""

from carousel.models import (
    CarouselSpec,
    EnrichedSlide,
    EnrichedSpec,
    LayoutChoice,
    Slide,
    SlotRole,
    TemplateID,
    TextSizeClass,
)

DOMAIN_ACCENTS = {
    "world": "#C8813A",  # amber gold — Decision #44
    "finance": "#A8B8C8",  # cool silver — TBD, placeholder
    "ai_tech": "#00D9FF",  # electric cyan — Decision #25
}

THEME_VARIANT = "dark"  # only variant in v1.0 — Decision #26


def _pick_template(slide: Slide) -> TemplateID:
    """
    Evaluated in order; first matching rule wins.

    Note: `portrait` (SEAM v1.5) is intentionally absent from this logic —
    it is inert until v1.5 and must never fire here.
    """
    if slide.role == SlotRole.cta:
        return TemplateID.cta
    if slide.role == SlotRole.hook:
        return TemplateID.cover  # Decision #53 — cover replaces hook for slide 1
    if slide.quote is not None:
        return TemplateID.quote
    if slide.dominant_numbers is not None and len(slide.dominant_numbers) > 0:
        return TemplateID.number  # fact sheet — up to 4 figures (Decision #57)
    if slide.role == SlotRole.event:
        return TemplateID.timeline
    if slide.role in (SlotRole.mechanism, SlotRole.concept):
        return TemplateID.concept
    return TemplateID.statement


def _pick_text_size_class(slide: Slide) -> TextSizeClass:
    total_chars = len(slide.headline) + len(slide.body)
    if total_chars <= 60:
        return TextSizeClass.xl
    if total_chars <= 120:
        return TextSizeClass.l
    if total_chars <= 200:
        return TextSizeClass.m
    return TextSizeClass.s


def pick_layouts(spec: CarouselSpec, domain: str) -> EnrichedSpec:
    """
    Assign template and styling to each slide.
    Pure Python. No LLM. No I/O. No side effects.
    Cost: $0. Latency: <10ms.
    """
    accent_colour = DOMAIN_ACCENTS[domain]

    enriched_slides = [
        EnrichedSlide(
            slide=slide,
            layout=LayoutChoice(
                template_id=_pick_template(slide),
                text_size_class=_pick_text_size_class(slide),
                accent_colour=accent_colour,
                theme_variant=THEME_VARIANT,
            ),
        )
        for slide in spec.slides
    ]

    return EnrichedSpec(spec=spec, slides=enriched_slides)
