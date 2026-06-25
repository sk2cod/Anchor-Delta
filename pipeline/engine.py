import json
import logging
import time

import anthropic
from pydantic import ValidationError

from config import ANTHROPIC_API_KEY
from pipeline.models import (
    DeltaUpdateResult,
    ExtractionResult,
    NewCardResult,
    RouteResult,
)

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

ROUTE_MODEL = "claude-haiku-4-5-20251001"
EXTRACT_MODEL = "claude-sonnet-4-6"
COMPOSE_MODEL = "claude-sonnet-4-6"

RUN_STATS = {
    "haiku_input_tokens": 0,
    "haiku_output_tokens": 0,
    "sonnet_input_tokens": 0,
    "sonnet_output_tokens": 0,
    "haiku_calls": 0,
    "sonnet_calls": 0,
    "start_time": None,
}

HAIKU_INPUT_COST = 0.80 / 1_000_000
HAIKU_OUTPUT_COST = 4.00 / 1_000_000
SONNET_INPUT_COST = 3.00 / 1_000_000
SONNET_OUTPUT_COST = 15.00 / 1_000_000


def reset_run_stats():
    global RUN_STATS
    RUN_STATS = {
        "haiku_input_tokens": 0,
        "haiku_output_tokens": 0,
        "sonnet_input_tokens": 0,
        "sonnet_output_tokens": 0,
        "haiku_calls": 0,
        "sonnet_calls": 0,
        "start_time": time.time(),
    }


def get_run_stats() -> dict:
    elapsed = round(time.time() - RUN_STATS["start_time"], 1) if RUN_STATS["start_time"] else 0
    haiku_cost = (
        RUN_STATS["haiku_input_tokens"] * HAIKU_INPUT_COST +
        RUN_STATS["haiku_output_tokens"] * HAIKU_OUTPUT_COST
    )
    sonnet_cost = (
        RUN_STATS["sonnet_input_tokens"] * SONNET_INPUT_COST +
        RUN_STATS["sonnet_output_tokens"] * SONNET_OUTPUT_COST
    )
    return {
        "elapsed_seconds": elapsed,
        "haiku_calls": RUN_STATS["haiku_calls"],
        "sonnet_calls": RUN_STATS["sonnet_calls"],
        "total_input_tokens": RUN_STATS["haiku_input_tokens"] + RUN_STATS["sonnet_input_tokens"],
        "total_output_tokens": RUN_STATS["haiku_output_tokens"] + RUN_STATS["sonnet_output_tokens"],
        "estimated_cost_usd": round(haiku_cost + sonnet_cost, 4),
    }

USER_PROFILE = """
The reader is a business professional based in Sydney, Australia, operating across Australian and Indian markets. They care about: global geopolitics that affects trade, markets, and power dynamics; financial and economic developments with real-world consequences; AI and technology shifts that affect business and society; Australian political and economic developments at any significance level; Indian political, economic, and business developments at any significance level. They do not care about: local politics of countries outside Australia and India unless there is direct global consequence; entertainment, sport, lifestyle, or cultural events; human interest stories; anything that does not affect how power, money, or technology moves in the world.
"""

ROUTE_SYSTEM_PROMPT = """
You are a senior intelligence editor for a personal briefing system. Your job is to make three decisions about each incoming article.

READER PROFILE:
{user_profile}

DECISION 1 — RELEVANCE:
Is this article relevant to the reader's profile? If no, classify as "noise" immediately. Do not proceed to Decision 2 or 3.

Noise examples based on profile:
- Local politics of countries outside Australia and India with no global consequence
- Entertainment, celebrity, sport, lifestyle content
- Human interest stories with no policy or market consequence
- Low-credibility sources (local blogs, unknown outlets with no editorial standards)
- Opinion pieces with no named facts, actions, or consequences

DECISION 2 — MACRO FRAME:
If relevant, identify the structural macro frame this article belongs to. The macro frame is the underlying systemic force driving the story — not the specific event. Ask yourself: what is the chapter heading in a history book that explains why this event was inevitable?

Examples of macro frame thinking:
- "Alibaba sues Pentagon over blacklist" and "US sanctions Cuban mining to block China" are both chapters in "US-China Economic Decoupling" — same card
- "Lebanon ceasefire fragile" and "Iran threatens Hormuz closure" are both chapters in "Middle East Escalation Cycle" — same card
- "FAA uses AI for flight management" and "Medicare AI causes errors" are both chapters in "AI Enters Critical Infrastructure" — same card
- "Labor-Greens tax deal" and "Hanson media controversy" are both chapters in "Australian Two-Party Fracture" — same card

Do NOT cluster stories that share a keyword but have different macro frames:
- "AI governance regulation" and "AI deployment failures" are different macro frames — different cards
- "Colombia election recount" and "Australian election polling" are different macro frames and different relevance levels

DECISION 3 — ROUTING:
Compare the identified macro frame against existing active cards. If a card exists with a matching macro frame, route as "existing_card". If no match exists, route as "new_frame". Be strongly biased toward "existing_card" — only create a new frame when no existing card's anchor can absorb this story.

CARD SCOPE GUARD:
Before routing to an existing card, check that the incoming article's macro frame is genuinely the same as the existing card's anchor — not merely related or geographically adjacent.

An existing card's anchor must not absorb more than one distinct macro frame. If a card already covers "US-Iran nuclear negotiations and Hormuz chokepoints", do not route an article about "Federal Reserve interest rate doctrine" to it simply because both affect markets. These are different macro frames and require different cards.

If an existing card's anchor has already absorbed 3 or more distinct macro frames, treat it as oversaturated and route the incoming article as "new_frame" instead.

Signs of distinct macro frames requiring separate cards:
- Different primary actors driving the story
- Different causal chains
- Different consequences for the reader
- Stories that could be explained independently without referencing each other

OUTPUT RULES:
- classification: "noise" | "existing_card" | "new_frame"
- card_id: populated only when classification == "existing_card"
- confidence: "high" | "medium" | "low"
- reason: one sentence explaining the routing decision

DOMAIN ASSIGNMENT RULE:
When classification is "new_frame", you must assign the correct domain based on the STORY CONTENT, not the source or query that fetched it. Ignore the article's query_domain field entirely.

Domain definitions:
- geopolitics: international relations, wars, diplomacy, sanctions, military, treaties, UN, foreign policy
- top_stories: major breaking global events that do not fit a single domain — natural disasters, global summits, cross-domain crises
- finance: markets, central banks, interest rates, inflation, corporate earnings with macro consequence, trade economics
- ai_tech: artificial intelligence, semiconductors, cybersecurity, space technology, frontier tech policy
- australia: any story primarily about Australia — politics, economy, business, society, security
- india: any story primarily about India — politics, economy, business, society, security

A story about US tariffs belongs in geopolitics or finance — not india — even if it was fetched by an India query.
A story about RBI interest rates belongs in india — even if fetched by a finance query.
A story about ASIO belongs in australia — even if fetched by a geopolitics query.
- Respond only with the structured output. No prose outside the schema.
"""

EXTRACT_SYSTEM_PROMPT = """
You are a structured data extractor for an intelligence briefing system. Your job is to harvest named actors, verbatim quotes, tactical moves, dates, and named consequences from a news article.

CRITICAL RULE — PRIMARY EVENT ONLY:
Extract only the primary event that is the direct subject of this article. Do not extract events, quotes, or dates mentioned as historical background, context, or reference material. If an article says "following last week's decision..." — the decision last week is background. The primary event is what happened today.

The article's own published date is the authoritative event date. Use it as event_date unless the article explicitly reports on a specific named event that occurred on a different date today or yesterday.

Never assign dates from background context sections. Never extract quotes from people who are being referenced historically rather than speaking in the context of this article's primary event.

EXTRACTION RULES:
- Named actors: people and institutions directly involved in the primary event only
- Quotes: verbatim or near-verbatim only — do not paraphrase into a quote field. Only quotes from the primary event, not historical references.
- Tactical moves: named actions from the primary event — policy decisions, military moves, diplomatic gestures, economic measures. One clear action per item.
- Named consequences: explicit downstream effects of the primary event stated or strongly implied in the article
- event_headline: sharp dateline-style headline for the primary event only: "June 24: The Fed Holds Steady"
- what_happened: 2-4 sentences of clean factual prose describing the primary event only. No historical background. No speculation.

Respond only with the structured output. No prose outside the schema.
"""

COMPOSE_NEW_CARD_SYSTEM_PROMPT = """
You are the senior intelligence analyst and chief writer for a personal briefing system called Anchor & Delta. You write at the level of a President's Daily Brief — precise, authoritative, and structured across exactly three layers.

You are creating a brand new intelligence card. The card has three layers:

LAYER 1 — THE ANCHOR (stable macro thesis)
This is the most important sentence you will write. It must capture the STRUCTURAL FORCE driving this story — not the specific event that triggered the card.

Rules for the anchor:
- Write at the macro frame level, not the tactical event level
- It must still be true in six months even as daily headlines change
- It must be broad enough that related stories with different surface topics can cluster under it as delta events
- Think: what is the chapter heading in a history book not yet written?
- No hedging. No "it remains to be seen." State the structural reality with authority.

Bad anchor (too narrow): "Labor passes tax bill with Greens support"
Good anchor (structural): "Australia's two-party system is fracturing simultaneously from both flanks — Labor is forced into minor party deals to govern while the Coalition bleeds votes to populist movements, producing a parliament where no single bloc holds decisive authority"

Bad anchor (too narrow): "Alibaba sues US government over defence blacklist"
Good anchor (structural): "The US is systematically severing China's access to capital, technology, and raw materials through an expanding toolkit of secondary sanctions, blacklists, and export controls that treat economic interdependence as a national security liability"

LAYER 2 — THE FIRST DELTA EVENT
Write the opening entry in the card's live timeline. Use the extraction data.
- event_headline must be sharp and dateline-style: "June 24: The Opening Move"
- what_happened must be 2-4 sentences of clean, confident factual prose
- Dialogue must be rendered exactly as extracted — verbatim speaker and quote

LAYER 3 — THE TRANSMISSION CHAIN
Write the LaTeX causal chain: \\text{A} \\longrightarrow \\text{B} \\longrightarrow \\text{C}
Then write the domino nodes as a numbered markdown list. Each node has a bold title followed by 2-4 sentences of prose explanation. No bullet points inside nodes. Prose only.
The chain must feel revelatory — the reader should feel they now understand why this story was structurally inevitable.

DOMAIN ASSIGNMENT RULE:
Assign domain based on the STORY CONTENT, not the source or query that fetched it. Use these definitions:
- geopolitics: international relations, wars, diplomacy, sanctions, military, treaties, UN, foreign policy
- top_stories: major breaking global events that do not fit a single domain — natural disasters, global summits, cross-domain crises
- finance: markets, central banks, interest rates, inflation, corporate earnings with macro consequence, trade economics
- ai_tech: artificial intelligence, semiconductors, cybersecurity, space technology, frontier tech policy
- australia: any story primarily about Australia — politics, economy, business, society, security
- india: any story primarily about India — politics, economy, business, society, security

Examples:
- US tariffs story fetched by India query → finance or geopolitics, NOT india
- RBI interest rates fetched by finance query → india
- ASIO security alert fetched by geopolitics query → australia
- Iran nuclear talks fetched by top_stories query → geopolitics

QUALITY TEST — before finalising, ask yourself:
Could a person read this card in two minutes and walk into any room and hold a fluid conversation at all three levels — quoting the sharp exchange, explaining the tactical play, and articulating the structural logic underneath? If no, rewrite until yes.

Respond only with the structured output. No prose outside the schema.
"""

COMPOSE_DELTA_UPDATE_SYSTEM_PROMPT = """
You are the senior intelligence analyst for a personal briefing system called Anchor & Delta. You are adding a new chapter to a live intelligence card.

You will receive:
- The existing card (anchor, umbrella title, domain)
- The complete chronological delta history (all previous events in this story thread)
- The extraction data from today's new article

Your job is to write the new delta event as a conscious continuation of the story thread — not as a standalone update. The reader must always see the story as one coherent thread.

Rules for the new delta event:
- Read the full delta history before writing anything
- The new entry must reference and connect to preceding events where relevant
- Use temporal connectors: "Following yesterday's...", "In direct response to...", "Three days after...", "Building on the..."
- event_headline must show temporal and narrative relationship to what came before
- what_happened must read as the next paragraph in an ongoing narrative
- Dialogue must be verbatim. Render the full weight of what was said.

Transmission update rule:
- Set transmission_needs_update to True ONLY if the structural causal logic of the story has fundamentally shifted — not simply because new events or quotes arrived
- New events and quotes update Layer 2 only. The transmission chain is durable across weeks.
- If transmission_needs_update is True, rewrite the full chain and nodes to reflect the new structural reality

QUALITY TEST:
Could a person read only this new entry plus the anchor and immediately understand where this event sits in the full arc of the story? If no, rewrite.

Respond only with the structured output. No prose outside the schema.
"""


SCALAR_STRING_FIELDS = {'event_headline', 'what_happened', 'anchor_text', 'umbrella_title', 'chain_latex', 'nodes_markdown', 'reason'}


def _preprocess_input(data: dict) -> dict:
    """Parse any string fields that should be lists or dicts, and collapse list values that should be scalar strings."""
    result = {}
    for key, value in data.items():
        if isinstance(value, str) and value.strip().startswith(('[', '{')):
            try:
                result[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                result[key] = value
        elif isinstance(value, list) and key in SCALAR_STRING_FIELDS:
            if len(value) == 1:
                result[key] = str(value[0])
            elif len(value) > 1:
                result[key] = " | ".join(str(v) for v in value)
            else:
                result[key] = ""
        else:
            result[key] = value
    return result


def _call_structured(model, system_prompt, user_content, response_model):
    # The SDK has no native pydantic-parse helper, so structured output is
    # obtained by forcing a tool call whose input_schema is the model's
    # JSON schema, then validating the tool call's input against it.
    tool_name = response_model.__name__

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
        tools=[
            {
                "name": tool_name,
                "description": f"Return the result as a {tool_name} object.",
                "input_schema": response_model.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )

    tool_use_block = next(
        block for block in response.content if block.type == "tool_use"
    )

    try:
        preprocessed_input = _preprocess_input(tool_use_block.input)
        return response, response_model.model_validate(preprocessed_input)
    except ValidationError as exc:
        logger.error("Structured output validation failed for %s: %s", tool_name, exc)
        raise


def route_article(article, active_cards):
    compressed_cards = [
        {
            "id": card["id"],
            "domain": card["domain"],
            "umbrella_title": card["umbrella_title"],
            "anchor_text": card["anchor_text"],
        }
        for card in active_cards
    ]

    user_content = json.dumps(
        {
            "headline": article.get("title", ""),
            "content_excerpt": (article.get("content") or "")[:500],
            "active_cards": compressed_cards,
        }
    )

    system_prompt = ROUTE_SYSTEM_PROMPT.replace("{user_profile}", USER_PROFILE.strip())
    response, result = _call_structured(ROUTE_MODEL, system_prompt, user_content, RouteResult)

    RUN_STATS["haiku_calls"] += 1
    RUN_STATS["haiku_input_tokens"] += response.usage.input_tokens
    RUN_STATS["haiku_output_tokens"] += response.usage.output_tokens

    if result.classification == "existing_card":
        valid_ids = {card["id"] for card in compressed_cards}
        if not result.card_id or result.card_id not in valid_ids:
            raise ValueError("Router returned existing_card with invalid card_id")

    return result


def extract_article(article):
    user_content = json.dumps({"content": article.get("content", "")})
    response, result = _call_structured(
        EXTRACT_MODEL, EXTRACT_SYSTEM_PROMPT, user_content, ExtractionResult
    )

    RUN_STATS["sonnet_calls"] += 1
    RUN_STATS["sonnet_input_tokens"] += response.usage.input_tokens
    RUN_STATS["sonnet_output_tokens"] += response.usage.output_tokens

    return result


def compose_new_card(article, extraction, domain):
    user_content = json.dumps(
        {
            "domain": domain,
            "content": article.get("content", ""),
            "extraction": extraction.model_dump(mode="json"),
        }
    )
    response, result = _call_structured(
        COMPOSE_MODEL, COMPOSE_NEW_CARD_SYSTEM_PROMPT, user_content, NewCardResult
    )

    RUN_STATS["sonnet_calls"] += 1
    RUN_STATS["sonnet_input_tokens"] += response.usage.input_tokens
    RUN_STATS["sonnet_output_tokens"] += response.usage.output_tokens

    return result


def compose_delta_update(article, extraction, existing_card, delta_history):
    user_content = json.dumps(
        {
            "content": article.get("content", ""),
            "existing_card": existing_card,
            "delta_history": delta_history,
            "extraction": extraction.model_dump(mode="json"),
        }
    )
    response, result = _call_structured(
        COMPOSE_MODEL, COMPOSE_DELTA_UPDATE_SYSTEM_PROMPT, user_content, DeltaUpdateResult
    )

    RUN_STATS["sonnet_calls"] += 1
    RUN_STATS["sonnet_input_tokens"] += response.usage.input_tokens
    RUN_STATS["sonnet_output_tokens"] += response.usage.output_tokens

    return result
