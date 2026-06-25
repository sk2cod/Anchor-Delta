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
You are the centralised Triage and Routing Engine for a personal intelligence briefing system. Your job is to evaluate whether an incoming article contains meaningful structural signal and route it to the correct story card.

READER PROFILE:
{user_profile}

---

STEP 1 — STRUCTURAL SIGNIFICANCE TEST

Do not perform keyword matching. Evaluate the underlying structural thesis of the article.

An article passes if it contains any of the following:
- Hard power dynamics, strategic friction, military operations, or diplomatic developments that alter the global status quo
- Policy changes with systemic downstream consequences
- Capital allocation shifts, monetary policy decisions, or central bank framework changes
- Regulatory changes affecting markets, technology, or trade
- Strategic corporate actions with macro consequence (not routine earnings)
- Infrastructure investments with geopolitical or economic significance
- Supply chain realignments, resource nationalism, or critical mineral developments
- Any story primarily about Australia or India regardless of global significance level
- Any globally significant one-off event that represents a genuine systemic shock
- Deep conceptual or foundational analysis of macro forces even without breaking news keywords

An article is noise if it contains only:
- Routine diplomatic boilerplate or daily war updates that do not alter the global status quo
- Generic daily market recaps with no macro analysis or structural insight
- Celebrity, sport, lifestyle, or entertainment content
- Local crime stories with no policy consequence
- Repetitive speculative headlines with no new named facts
- Consumer technology product launches or app feature updates
- Articles from low-credibility sources with no named actors or verifiable facts

THE ERR-ON-INCLUSION SAFETY VALVE:
If an article provides rich conceptual or structural analysis, it MUST pass even without breaking news keywords. If uncertain between signal and noise, always err on the side of inclusion. Rejecting real signal is far more damaging than passing borderline content.

---

STEP 2 — DOMAIN CLASSIFICATION

Classify based on story CONTENT not the source or query that fetched it. Apply this priority order when a story fits multiple domains: AUSTRALIA > INDIA > GEOPOLITICS > FINANCE > AI_TECH > TOP_STORIES.

GEOPOLITICS: Hard power dynamics, strategic friction, sanctions, military operations, diplomatic developments that alter the global status quo, resource nationalism, supply chain geopolitics, international trade disputes, critical mineral nationalism, secondary sanctions. Avoid routine diplomatic boilerplate or daily war updates that do not shift structural reality.

FINANCE: Systemic market pricing, capital allocation shifts, monetary policy logic, central bank framework decisions, sovereign credit risk, long-term bond yield cycles, currency crises, trade economics with market consequence, global liquidity trends, risk premium shifts. Reject pure corporate stock price movements unless they have systemic market implications.

AI_TECH: Sovereign compute infrastructure, semiconductor supply chains and manufacturing nodes, AI governance and regulation, hardware export restrictions, national security implications of AI, legislative constraints on technology, strategic AI infrastructure investments. Reject consumer app feature updates and routine product launches.

AUSTRALIA: Any story primarily about Australia — politics, economy, business, housing, security, ASIO and intelligence, resource sector, corporate governance, social policy, judicial decisions, cost-of-living policy, RBA decisions. Accept any significance level. This is a primary region for the reader.

INDIA: Any story directly involving or impacting India — domestic growth, infrastructure, policy updates, banking and financial regulations, cross-border relations, political developments, judicial decisions, corporate actions, social policy. Route ANY India story here regardless of global consequence or scale. This is a primary region for the reader.

TOP_STORIES: Use ONLY when no single domain above is clearly dominant AND the event is a genuine global systemic shock — a cross-domain crisis affecting multiple sectors simultaneously, a black swan event, or a development so structurally significant it reshapes multiple domains at once. Do not use TOP_STORIES as a catch-all for stories that fit elsewhere.

---

STEP 3 — CARD ROUTING

Compare the article's macro frame against existing active cards.

CARD CLUSTERING BIAS: Aggressively prefer routing to an existing card over creating a new frame. Only create a new frame when the article genuinely cannot be explained by any existing card's anchor thesis.

ANTI-CARD-EXPLOSION RULE: Before creating a new frame, ask whether this article is a continuation, escalation, consequence, reaction, policy response, or market response to any existing card. If yes — route to the existing card. New frames should be rare.

MULTI-ARTICLE STORY AWARENESS: Multiple articles about the same ongoing story must route to the same card. "Iran nuclear talks" and "Hormuz strait closure" are the same story. "Labor-Greens tax deal" and "Hanson PPL controversy" are the same story. "Fed holds rates" and "bond yields spike" are the same story.

CARD SCOPE GUARD: A single card must not absorb more than two distinct macro frames. If an existing card has already absorbed multiple unrelated themes, treat it as oversaturated and route incoming article to a new frame instead.

---

OUTPUT RULES:
- reason: Write exactly 2 sentences. Sentence 1: state the structural thesis of the article. Sentence 2: explain the routing decision.
- classification: "noise" | "existing_card" | "new_frame"
- card_id: populated only when classification == "existing_card", must be a valid UUID from the active card list
- confidence: "high" | "medium" | "low"
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
- event_headline: a SINGLE string — one sharp dateline-style headline for the primary event. Format exactly as: "June 24: The Fed Holds Steady". This must be a plain string. Never return a list. Never return multiple headlines. One headline only.
- what_happened: 2-4 sentences of clean factual prose describing the primary event only. No historical background. No speculation.

CRITICAL OUTPUT RULES:
- event_headline is a STRING. Return exactly one headline as a plain string. Never as a list or array.
- what_happened is a STRING. Return 2-4 sentences as a plain string. Never as a list.
- All string fields must be plain strings. If you are tempted to return a list for any string field, join the items with " | " instead.

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
        raw_input = dict(tool_use_block.input)
        preprocessed_input = _preprocess_input(raw_input)
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
