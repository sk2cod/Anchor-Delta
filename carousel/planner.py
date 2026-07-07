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

# Drop order when the hard cap is exceeded — reverse priority. `quote` is
# dropped last — protected above all other optional slots — once it's
# present it is the strongest single piece of content in the carousel
# (Decision #55).
DROP_PRIORITY = (
    SlotRole.proof,
    SlotRole.concept,
    SlotRole.mechanism,
    SlotRole.contrast,
    SlotRole.quote,
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

MAX_SLOTS = 8  # 7 content + 1 CTA (Decision #14) — 9 when the quote slot
# fires (Decision #55); resolved as a local variable in plan_carousel(),
# this constant documents the no-quote-slot baseline only.


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

    # Quote is its own slot, distinct from proof — it only fires when BOTH a
    # dominant number AND a strong sourced quote exist simultaneously. Either
    # alone is handled by proof (or nothing); this is deliberately narrower
    # than proof's own condition (Decision #55).
    if len(context.dominant_numbers) > 0 and len(context.available_quotes) > 0:
        candidates.append(SlotRole.quote)

    if _any_node_contains(nodes, CONTRAST_KEYWORDS):
        candidates.append(SlotRole.contrast)

    if context.domain in ("world", "ai_tech") and _any_node_contains(nodes, MECHANISM_KEYWORDS):
        candidates.append(SlotRole.mechanism)

    if context.domain in ("finance", "ai_tech") and _any_node_contains(nodes, CONCEPT_KEYWORDS):
        candidates.append(SlotRole.concept)

    # Cap resolves to 9 for this carousel when the quote slot fired, 8
    # otherwise — a local variable, not a change to the MAX_SLOTS constant
    # (Decision #55).
    max_slots = 9 if SlotRole.quote in candidates else MAX_SLOTS

    total = len(FIXED_SLOT_ROLES) + len(candidates)
    if total > max_slots:
        excess = total - max_slots
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
