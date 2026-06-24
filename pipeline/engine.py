import json
import logging

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

ROUTE_SYSTEM_PROMPT = """You are the routing gate for the Anchor & Delta pipeline. Every article reaching you has already survived upstream filtering for relevance, freshness, and signal density (verbatim quotes, named actions, or named consequences) — genuine "noise" at this stage is rare. Classify the article into exactly one of three categories: "noise", "existing_card", or "new_frame".

- "noise": despite surviving upstream filters, the article still carries no substantive development worth tracking as a story thread (for example, a content-free press release or filler dressed up as relevant). Use this rarely.
- "existing_card": the article is the next chapter in one of the active cards provided. Set card_id to that card's id.
- "new_frame": the article reports a real, substantive development — economic, political, or geopolitical — that does not fit any existing card's anchor thesis. This includes the case where there are no active cards to match against at all, or where every active card covers an unrelated topic.

Treat a real news event as worth tracking by default: a policy decision, a statement from a named official, an economic data release, a diplomatic or military action all qualify. Do not classify an article as "noise" just because the news is routine, periodic, or expected — a scheduled central bank decision, a quarterly report, or a regular vote is still a legitimate new frame if nothing existing covers it. Reserve "noise" for articles that, on inspection, carry no real development at all.

Between "existing_card" and "new_frame" you are strongly biased toward "existing_card": a new frame is only justified when the article truly cannot be folded into any existing card's anchor thesis, even with a generous reading. Never choose "noise" merely because there is no matching existing card.

Return no prose outside the schema. Populate card_id only when classification is "existing_card"; otherwise leave it null. Set confidence to "high", "medium", or "low", and give a one-sentence reason for your decision."""

EXTRACT_SYSTEM_PROMPT = """You are the extraction stage of the Anchor & Delta pipeline. Given the full text of a news article, extract structured facts with no embellishment.

- named_actors: every named person, organisation, or government body that takes an action or is quoted in the article.
- dialogue: verbatim or near-verbatim quotes only, each attributed to a named speaker. Never paraphrase a quote into the quote field — if no exact quote exists for a speaker, omit them.
- tactical_moves: named actions taken by an actor, one concrete action per item, written as short action phrases.
- named_consequences: explicit downstream effects stated or directly implied by the article, one per item.
- event_date: the date the event described actually occurred, if stated or clearly inferable; otherwise null.
- event_headline: a sharp, dateline-style headline capturing the core event in a single line.
- what_happened: 2 to 4 sentences of clean factual prose summarising what happened, with no speculation or filler.

Return no prose outside the schema."""

COMPOSE_NEW_CARD_SYSTEM_PROMPT = """You are the composer for the Anchor & Delta pipeline, writing a brand-new story card at the level of a President's Daily Brief. You are given the full article content and a structured extraction of its facts. Produce exactly three layers:

Layer 1 — Anchor: a 2 to 3 sentence durable macro thesis for this story. It must state the structural logic in a way that will still be true in six months. No hedging, no "remains to be seen," no qualifiers that dodge a real claim.

Layer 2 — First delta event: a sharp, dateline-style event_headline, 2 to 4 sentences of clean factual prose in what_happened, and the verbatim dialogue extracted from the article.

Layer 3 — Transmission: a LaTeX causal chain in chain_latex using the format \\text{A} \\longrightarrow \\text{B} \\longrightarrow \\text{C} connecting the key causal steps, followed by nodes_markdown containing numbered domino nodes. Each node has a bold title and 2 to 4 sentences of prose explaining that step. No bullet points inside nodes.

Before finalising, apply the Conversation Asset Test: could a person read this card in two minutes and hold a fluid conversation at all three levels — quoting the sharp exchange, explaining the tactical play, and articulating the structural logic? If the answer is no, rewrite until it is.

Return no prose outside the schema."""

COMPOSE_DELTA_UPDATE_SYSTEM_PROMPT = """You are the composer for the Anchor & Delta pipeline, writing the next delta event for an existing story card. You are given the existing card, the complete chronological delta history (oldest first — never truncated), and a structured extraction of the new article's facts.

Write the new delta event as a conscious continuation of the story thread, not a standalone update. Explicitly reference preceding events using phrases like "Following yesterday's...", "In direct response to...", or "Three days after...", anchored to the actual dates in the delta history.

Set transmission_needs_update to true only if the structural causal logic of the story has fundamentally shifted — a new actor entering, a reversal of the prior trajectory, or a structural escalation that the existing transmission chain no longer explains. Do not set it to true merely because a new event arrived; routine new events update Layer 2 (the delta event) only, and chain_latex and nodes_markdown should be left null in that case.

Apply this quality test before finalising: could a person read only this new entry plus the card's anchor and immediately understand where this event sits in the full arc of the story? If not, rewrite until it is.

Return no prose outside the schema."""


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
        return response_model.model_validate(tool_use_block.input)
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

    result = _call_structured(ROUTE_MODEL, ROUTE_SYSTEM_PROMPT, user_content, RouteResult)

    if result.classification == "existing_card":
        valid_ids = {card["id"] for card in compressed_cards}
        if not result.card_id or result.card_id not in valid_ids:
            raise ValueError("Router returned existing_card with invalid card_id")

    return result


def extract_article(article):
    user_content = json.dumps({"content": article.get("content", "")})
    return _call_structured(EXTRACT_MODEL, EXTRACT_SYSTEM_PROMPT, user_content, ExtractionResult)


def compose_new_card(article, extraction, domain):
    user_content = json.dumps(
        {
            "domain": domain,
            "content": article.get("content", ""),
            "extraction": extraction.model_dump(mode="json"),
        }
    )
    return _call_structured(
        COMPOSE_MODEL, COMPOSE_NEW_CARD_SYSTEM_PROMPT, user_content, NewCardResult
    )


def compose_delta_update(article, extraction, existing_card, delta_history):
    user_content = json.dumps(
        {
            "content": article.get("content", ""),
            "existing_card": existing_card,
            "delta_history": delta_history,
            "extraction": extraction.model_dump(mode="json"),
        }
    )
    return _call_structured(
        COMPOSE_MODEL, COMPOSE_DELTA_UPDATE_SYSTEM_PROMPT, user_content, DeltaUpdateResult
    )
