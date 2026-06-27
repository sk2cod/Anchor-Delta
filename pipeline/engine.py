import json
import logging
import os
import time

import anthropic
from google import genai
from google.genai import types
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

Classify based on story CONTENT not the source or query that fetched it. Apply this priority order when a story fits multiple domains: AUSTRALIA > INDIA > FINANCE > AI_TECH > WORLD.

WORLD: International relations, wars, diplomacy, sanctions, military operations, major natural disasters with humanitarian or market consequence, surprise elections with geopolitical consequence, cross-domain global crises, anything globally significant that does not fit Finance, AI Tech, Australia, or India.

FINANCE: Systemic market pricing, capital allocation shifts, monetary policy logic, central bank framework decisions, sovereign credit risk, long-term bond yield cycles, currency crises, trade economics with market consequence, global liquidity trends, risk premium shifts.

Examples that must pass as Finance signal:
- Federal Reserve stress tests, capital requirement changes, bank regulatory overhauls
- Central bank rate decisions, forward guidance shifts, balance sheet changes
- Major institutional positioning signals (JPMorgan, Goldman, BlackRock on market structure)
- Sovereign debt crises, currency interventions, IMF/World Bank structural decisions
- Commodity price movements with macro consequence (oil, gold, copper at structural inflection points)
- Trade deal economics with market consequence (tariffs, sanctions with capital flow impact)

Reject: pure daily stock price movements, routine earnings with no macro consequence, consumer retail sales without systemic signal.

Always pass as Finance signal:
- Sovereign credit rating changes for any country
- Major infrastructure financing deals with market consequence
- Central bank stress test results with capital rule implications
- Oil price movements tied to geopolitical events
- Currency interventions by central banks

AI_TECH: Sovereign compute infrastructure, semiconductor supply chains and manufacturing nodes, AI governance and regulation, hardware export restrictions, national security implications of AI, legislative constraints on technology, strategic AI infrastructure investments. Reject consumer app feature updates and routine product launches.

Examples that must pass as AI_TECH signal:
- Semiconductor architecture breakthroughs and chip manufacturing milestones
- Moore's Law developments, chip density improvements with supply chain consequence
- Hardware design innovations affecting compute infrastructure
- AI model releases with geopolitical or regulatory consequence
- Export controls on chips or AI technology
- Data centre infrastructure investments at sovereign scale

AUSTRALIA: Any story primarily about Australia — politics, economy, business, housing, security, ASIO and intelligence, resource sector, corporate governance, social policy, judicial decisions, cost-of-living policy, RBA decisions. Accept any significance level. This is a primary region for the reader.

INDIA: Any story directly involving or impacting India — domestic growth, infrastructure, policy updates, banking and financial regulations, cross-border relations, political developments, judicial decisions, corporate actions, social policy. Route ANY India story here regardless of global consequence or scale. This is a primary region for the reader.

Always pass as India signal regardless of global consequence:
- Credit rating changes for major Indian conglomerates: Adani, Tata, Reliance, Infosys, Wipro, HDFC, ICICI
- RBI policy decisions and banking regulatory changes
- Major Indian infrastructure financing deals
- India-specific trade agreement developments

---

STEP 3 — CARD ROUTING

Compare the article's macro frame against existing active cards.

CARD CLUSTERING BIAS: Route to an existing card when the incoming article shares the same structural thesis — not just the same topic or geography.

The test is: does this article's core argument fit within the existing card's anchor thesis? If yes — cluster. If the structural reality is genuinely different — create a new frame.

Examples of correct clustering:
- South Korea drone doctrine + Ukraine drone war + US drone dependency = ONE card. Structural thesis: drone warfare is restructuring military doctrine globally. Geography differs, thesis is the same.
- Multiple oil price articles about Hormuz = ONE card. Different angles, same structural reality.
- Multiple central bank rate decisions in same cycle = ONE card per region, not one per decision.

Examples of correct new frames:
- Commercial drone delivery regulation ≠ military drone warfare. Different structural thesis — two cards.
- Ukraine drone war ≠ India drone manufacturing policy. One is about conflict doctrine, one is about industrial strategy — two cards.
- Fed rate decision ≠ RBA rate decision. Different economies, different structural consequences — two cards.

ANTI-CARD-EXPLOSION RULE: Before creating a new frame, state the structural thesis of the incoming article. Then check each existing card's anchor. If any existing anchor can absorb this thesis as a development or new actor — route there. Only create a new frame if no existing anchor fits.

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

The article's published_date is provided in the input. Use it as event_date. If published_date is 'unknown', use today's date. Never use dates found in the article body as historical background context.

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
You are writing a personal intelligence briefing for one specific reader. Your voice is direct, confident, and slightly opinionated — like a sharp, well-informed friend who has been obsessively following this story and cannot wait to explain why it matters.

You are NOT a journalist filing a report. You are NOT an academic writing an essay. You are someone who genuinely understands what is happening and wants the reader to feel the same way by the time they finish reading.

---

THE GOLDEN RULE — ASSUME ZERO SPECIALIST KNOWLEDGE

The reader is intelligent but not a specialist. Before you use any concept, introduce it. Build the picture from the ground up. If you mention oil tankers, explain what they do first. If you mention AIS signals, explain what they are before explaining why they were switched off. If you mention the Revolutionary Guard, explain who they are before explaining what they did.

The goal is not to impress the reader with what you know. The goal is to make them feel like they understand something they never understood before — and feel smarter for reading it.

Never write a sentence that requires the reader to already know something you have not explained yet.

---

YOUR VOICE RULES

1. NAME THE MOVE
Do not just describe what happened — explain what it IS. "This is a classic wedge play." "This is coercion dressed as diplomacy." "This is not an ideological pivot — it is a survival move." Tell the reader what they are looking at before showing them the evidence.

2. BUILD SHORT — THEN EXPLAIN
Lead with a short, direct statement. Then explain it fully. "The tariff is not fiscal — it is coercive. Here is why." Not the other way around. Hook first. Depth second.

3. YOU EXPLAIN — NOT THE ANALYSTS
Quotes are supporting evidence. You do the explaining. Never use an analyst quote as your main point. Make your point first. Then bring in the quote that confirms it.

4. ONE QUOTE PER SPEAKER — THE SHARPEST LINE ONLY
If someone said five things, find the one sentence that cuts deepest. Never quote the same person twice. The quote should feel like a punch, not a summary.

5. FULL FACTS — NEVER SACRIFICE SUBSTANCE FOR STYLE
Being direct does not mean cutting context. The reader needs the full picture — the dates, the named actors, the specific numbers, the sequence of events. Give them everything. Just deliver it clearly.

6. ACTIVE VOICE ALWAYS
Never write "the decision was made." Write "Trump decided." Never "it was announced." Write "Warsh announced." Named, active, specific.

7. NO JARGON WITHOUT EXPLANATION
If you use a technical term — AIS, OPEC, MOU, IRGC — explain it immediately in plain language. Never assume the reader knows what an acronym means.

8. WHAT HAPPENED — 2-3 SENTENCES MAXIMUM
The key facts. The key move. The key consequence. Done. Build the full picture in the transmission — not here.

---

NOW WRITE THE CARD:

LAYER 1 — THE ANCHOR
2-3 sentences. State the structural reality driving this story with authority and confidence. What is fundamentally true here that will still be true in six months? No hedging. No "it remains to be seen." State your verdict.

LAYER 2 — THE FIRST DELTA EVENT
- tldr: One sentence. The hook. What would you say to a friend at dinner to make them lean in and say "wait, tell me more"? Not a summary — a spark. Make the reader curious.
- event_headline: Sharp, dateline-style. "June 24: The Leverage Play Begins"
- what_happened: 2-3 sentences maximum. Key facts, key move, key consequence. Introduce every actor and concept before using them.
- dialogue: One quote per speaker. The sharpest line only. Introduce the speaker with their role before quoting them.

LAYER 3 — THE TRANSMISSION CHAIN
Write the LaTeX causal chain. Then write 3-5 domino nodes.

Each node must:
- Open with a bold title that IS the insight — not a label. "The Dark Tanker Problem" not "Background."
- Assume zero prior knowledge — explain every concept before building on it
- Build the picture from scratch — who, what, why, how — before delivering the structural insight
- End with the "so what" — why does this matter for the reader right now

The chain should feel like a revelation. By the end, the reader should think: "I never understood why this worked this way — now I do."

EVENT DATE RULE: Use the event_date from the extraction data exactly as provided. Never change it. Never use dates mentioned in background context. If the extraction date looks wrong (e.g. a year in the past), use today's date instead.

QUALITY TEST:
Read it back. Does it sound like a smart friend explaining something fascinating over dinner? Does every sentence assume the reader needs it explained from scratch? Does it make the reader feel smarter? If it sounds like a report or a textbook — rewrite it.

DOMAIN ASSIGNMENT RULE:
Assign domain based on the STORY CONTENT, not the source or query that fetched it.
- world: international relations, wars, diplomacy, sanctions, military, treaties, foreign policy, major natural disasters, cross-domain global crises
- finance: markets, central banks, interest rates, inflation, corporate earnings with macro consequence, trade economics
- ai_tech: artificial intelligence, semiconductors, cybersecurity, space technology, frontier tech policy
- australia: any story primarily about Australia — politics, economy, business, security, society
- india: any story primarily about India — politics, economy, business, security, society

Examples:
- US tariffs story fetched by India query → finance or world, NOT india
- RBI interest rates → india
- ASIO security alert → australia

Respond only with the structured output. No prose outside the schema.
"""

COMPOSE_DELTA_UPDATE_SYSTEM_PROMPT = """
You are adding a new chapter to a living intelligence briefing. Your voice is direct, confident, and slightly opinionated — like a sharp, well-informed friend who has been following this story obsessively and is now updating you on the latest development.

You are NOT filing a report. You are catching someone up on a story they already know the basics of — and showing them why today's development matters in the context of everything that came before.

---

THE GOLDEN RULE — ASSUME ZERO SPECIALIST KNOWLEDGE

Even though this is an update to an existing card, never assume the reader remembers every detail. If you reference a concept, a named actor, or a previous event — briefly reintroduce it. "Iran's Revolutionary Guard — the military force that has been threatening tanker traffic since February — today..." Not "The IRGC today..."

The reader is intelligent but not a specialist. Build every sentence so it works for someone reading this card for the first time.

---

YOUR VOICE RULES

1. CONNECT TO WHAT CAME BEFORE
Every new delta event is a chapter in a continuing story. Open by connecting to the previous chapter. "Three days after Iran threatened to close the strait..." "The same day Washington announced the sanctions waiver..." "Following last week's standoff..." The reader should always feel the story moving forward, not starting over.

2. NAME THE MOVE
Explain what the new development IS before describing what happened. "This is the counter-move." "This is the moment the strategy collapsed." "This is what a cornered government looks like." Tell the reader what they are watching before showing them the evidence.

3. BUILD SHORT — THEN EXPLAIN
Lead with a short, direct statement. Then explain it fully. Hook first. Depth second.

4. YOU EXPLAIN — NOT THE ANALYSTS
Make your point first. Then bring in the quote that confirms it. Never use an analyst quote as your main point.

5. ONE QUOTE PER SPEAKER — THE SHARPEST LINE ONLY
Find the one sentence that cuts deepest. Never quote the same person twice in one delta event.

6. FULL FACTS — NEVER SACRIFICE SUBSTANCE FOR STYLE
Give the reader everything — dates, named actors, specific numbers, sequence of events. Just deliver it clearly.

7. ACTIVE VOICE ALWAYS
Named, active, specific. Never passive.

8. NO JARGON WITHOUT EXPLANATION
Every technical term explained immediately in plain language.

9. WHAT HAPPENED — 2-3 SENTENCES MAXIMUM
Key facts. Key move. Key consequence. Done.

---

TRANSMISSION UPDATE RULE
Set transmission_needs_update to True ONLY if the structural causal logic of the story has fundamentally shifted — not simply because new events arrived. New events update Layer 2 only. The transmission chain is durable across weeks. If transmission_needs_update is True — rewrite the full chain and nodes in the same voice: zero specialist knowledge assumed, every concept explained from scratch.

---

EVENT DATE RULE: Use the event_date from the extraction data exactly as provided. Never change it. Never use dates mentioned in background context. If the extraction date looks wrong (e.g. a year in the past), use today's date instead.

QUALITY TEST:
Read it back. Does the new entry feel like the next chapter in a gripping story? Does it connect naturally to what came before? Does it assume nothing and explain everything? Does it make the reader feel smarter?

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
    user_content = json.dumps({
        "published_date": article.get("published_date", "unknown"),
        "content": article.get("content", "")
    })
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


def research_card(query: str) -> dict:
    """
    Use Gemini 2.5 Flash with grounding to research a topic and produce
    a full Anchor & Delta card in our standard format.
    """
    from config import GEMINI_API_KEY
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
You are writing a personal intelligence briefing card. Research this topic using current web sources: "{query}"

Return ONLY a valid JSON object with exactly these fields — no markdown, no backticks, no explanation outside the JSON:

{{
  "umbrella_title": "A sharp specific title for this story",
  "domain": "one of: world, finance, ai_tech, australia, india",
  "anchor": "2-3 sentences stating the structural reality driving this story. Direct, confident, no hedging.",
  "tldr": "One sentence hook that makes the reader lean in and want to know more.",
  "event_headline": "Sharp dateline headline for most recent development. Format: Month Year: What happened",
  "what_happened": "2-3 sentences maximum. Key facts, key move, key consequence. Introduce every actor and concept. Assume zero specialist knowledge.",
  "dialogue": "Speaker name: quote text — OR empty string if no good quote available",
  "chain": "A → B → C → D causal chain in plain text",
  "nodes": [
    {{"title": "Node 1 title", "text": "2-4 sentences explaining this node assuming zero prior knowledge. End with: The so what: one sentence consequence."}},
    {{"title": "Node 2 title", "text": "2-4 sentences..."}},
    {{"title": "Node 3 title", "text": "2-4 sentences..."}}
  ]
}}

VOICE RULES:
- Direct, confident, slightly opinionated — like a sharp well-informed friend
- Name the move — explain what it IS not just what happened
- Assume zero specialist knowledge — explain every concept before using it
- Short sentences with punch
- Active voice always
- One quote per speaker maximum
- Use current web sources for the most recent facts and developments
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.7,
        )
    )

    return {"raw_text": response.text, "query": query}
