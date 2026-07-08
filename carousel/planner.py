"""
CarouselPlanner — decides slot structure and order for a card (Blueprint §5.3).

Deterministic Python only — the LLM never decides slide count or structure
(Decision #03, #13). Eliminates roughly 80% of "carousel is the wrong shape"
failures by keeping structure fully deterministic; only slide content is
creative.
"""

from carousel.models import Slot, SlotPlan, SlotRole, StoryContext

# Keyword lists — simple, fast, no LLM. Tune here.
CONTRAST_KEYWORDS = ["while", "meanwhile", "however", "but", "whereas"]
MECHANISM_KEYWORDS = ["because", "which means", "this is why", "the reason", "how this works"]
CONCEPT_KEYWORDS = ["framework", "model", "structure", "system", "principle", "pattern"]

FIXED_SLOT_ROLES = (SlotRole.hook, SlotRole.setup, SlotRole.payoff, SlotRole.cta)

# Roles that are never marked optional, even though `pivot` is only added by
# a rule rather than being a fixed slot (Decision #13 — pivot is the reframe
# slide and is always added when conditions allow).
NON_OPTIONAL_ROLES = set(FIXED_SLOT_ROLES) | {SlotRole.pivot}

# Drop order when the cap is exceeded — reverse priority. `proof` and
# `quote` are NOT in this tuple at all — they are evidence slots that
# exist only because the card has genuine data, and the cap grows to
# accommodate them (Decision #60) rather than the reverse. Only
# structural/optional slots are ever droppable.
DROP_PRIORITY = (
    SlotRole.mechanism,
    SlotRole.contrast,
    SlotRole.concept,
)

# Final slide order (Blueprint §5.3). `quote` sits immediately after `proof`
# and before `contrast`/`payoff` when present (Decision #55).
SLOT_ORDER = (
    SlotRole.hook,
    SlotRole.event,
    SlotRole.setup,
    SlotRole.pivot,
    SlotRole.mechanism,
    SlotRole.concept,
    SlotRole.proof,
    SlotRole.quote,
    SlotRole.contrast,
    SlotRole.payoff,
    SlotRole.cta,
)

MAX_SLOTS = 8  # 7 content + 1 CTA (Decision #14) — the base cap when
# neither proof nor quote fires. Each adds 1 on top of this, additively,
# up to 10 when both fire (Decision #60); resolved dynamically in
# plan_carousel(), this constant documents the neither-fires baseline only.


def _any_node_contains(nodes: list[str], keywords: list[str]) -> bool:
    """True if any keyword appears as a substring of any transmission node."""
    lowered_nodes = [node.lower() for node in nodes]
    return any(keyword in node for node in lowered_nodes for keyword in keywords)


def plan_carousel(context: StoryContext) -> SlotPlan:
    """
    Decide slot structure for this card.
    Pure Python. No LLM. No I/O. No side effects.
    Cost: $0. Latency: <10ms.
    """
    nodes = context.transmission_summary.nodes

    candidates: list[SlotRole] = []

    if context.latest_delta is not None:
        candidates.append(SlotRole.event)

    candidates.append(SlotRole.pivot)  # always — the reframe slide

    if len(context.dominant_numbers) > 0:
        candidates.append(SlotRole.proof)

    # Quote is its own slot, independent of proof — a strong sourced quote
    # is standalone evidence on its own merits, not something that needs a
    # number alongside it to justify a slide. The anti-fabrication guard
    # (Decision #56) already keeps weak/unsourced quotes out of
    # available_quotes, so this condition doesn't need to double-guard
    # against it (Decision #61).
    if len(context.available_quotes) > 0:
        candidates.append(SlotRole.quote)

    if _any_node_contains(nodes, CONTRAST_KEYWORDS):
        candidates.append(SlotRole.contrast)

    if context.domain in ("world", "ai_tech") and _any_node_contains(nodes, MECHANISM_KEYWORDS):
        candidates.append(SlotRole.mechanism)

    if context.domain in ("finance", "ai_tech") and _any_node_contains(nodes, CONCEPT_KEYWORDS):
        candidates.append(SlotRole.concept)

    # Proof and quote are purely additive (Decision #60) — each raises the
    # cap by 1 rather than competing with structural slots for a fixed
    # budget. Base 8, +1 if proof fired, +1 if quote fired: 8/9/9/10.
    effective_cap = MAX_SLOTS
    if SlotRole.proof in candidates:
        effective_cap += 1
    if SlotRole.quote in candidates:
        effective_cap += 1

    total = len(FIXED_SLOT_ROLES) + len(candidates)
    if total > effective_cap:
        excess = total - effective_cap
        for role in DROP_PRIORITY:
            if excess <= 0:
                break
            if role in candidates:
                candidates.remove(role)
                excess -= 1

    present_roles = set(FIXED_SLOT_ROLES) | set(candidates)

    slots = [
        Slot(slot_id=role.value, role=role, is_optional=role not in NON_OPTIONAL_ROLES)
        for role in SLOT_ORDER
        if role in present_roles
    ]

    return SlotPlan(slots=slots)
