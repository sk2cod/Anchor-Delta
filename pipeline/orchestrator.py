import logging

from config import MAX_ACTIVE_CARDS, VALID_DOMAINS
from db import (
    append_delta_event,
    create_card,
    get_active_card_count,
    get_active_cards,
    get_card_by_id,
    get_delta_events_for_card,
    log_noise,
    update_last_delta_at,
    upsert_transmission,
)
from pipeline.engine import (
    compose_delta_update,
    compose_new_card,
    extract_article,
    route_article,
)

logger = logging.getLogger(__name__)


def process_article(article):
    try:
        active_cards = get_active_cards()
        route_result = route_article(article, active_cards)

        if route_result.classification == "noise":
            log_noise(
                headline=article["title"],
                source_url=article["url"],
                gate_failed="llm_route",
                reason=route_result.reason,
            )
            return {"status": "noise", "article_title": article["title"]}

        if route_result.classification == "existing_card":
            existing_card = get_card_by_id(route_result.card_id)
            delta_history = get_delta_events_for_card(route_result.card_id)
            extraction = extract_article(article)
            result = compose_delta_update(article, extraction, existing_card, delta_history)

            append_delta_event(
                card_id=route_result.card_id,
                event_date=result.event_date,
                headline=result.event_headline,
                what_happened=result.what_happened,
                dialogue=[t.dict() for t in result.dialogue],
            )
            update_last_delta_at(route_result.card_id)

            if result.transmission_needs_update is True:
                upsert_transmission(
                    card_id=route_result.card_id,
                    chain_latex=result.chain_latex,
                    nodes_markdown=result.nodes_markdown,
                )

            return {"status": "updated", "card_id": route_result.card_id}

        if route_result.classification == "new_frame":
            if get_active_card_count() >= MAX_ACTIVE_CARDS:
                log_noise(
                    headline=article["title"],
                    source_url=article["url"],
                    gate_failed="llm_route",
                    reason="max active cards reached",
                )
                return {"status": "capped", "article_title": article["title"]}

            extraction = extract_article(article)
            result = compose_new_card(article, extraction, domain=article["query_domain"])

            if result.domain not in VALID_DOMAINS:
                raise ValueError(f"LLM returned invalid domain: {result.domain}")

            new_card = create_card(
                domain=result.domain,
                umbrella_title=result.umbrella_title,
                anchor_text=result.anchor_text,
            )
            append_delta_event(
                card_id=new_card["id"],
                event_date=result.event_date,
                headline=result.event_headline,
                what_happened=result.what_happened,
                dialogue=[t.dict() for t in result.dialogue],
            )
            upsert_transmission(
                card_id=new_card["id"],
                chain_latex=result.chain_latex,
                nodes_markdown=result.nodes_markdown,
            )

            return {"status": "created", "card_id": new_card["id"]}

    except Exception as e:
        logger.error("process_article failed: %s", e, exc_info=True)
        return {"status": "error", "reason": str(e), "article_title": article.get("title", "unknown")}
