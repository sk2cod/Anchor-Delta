import logging

from db.client import supabase_client

logger = logging.getLogger(__name__)


def log_routing_decision(
    headline, source_url, classification, reason, card_id=None, confidence=None, run_id=None
):
    """
    Record every route_article() classification (noise, existing_card,
    new_frame) with its reason — not just noise, which noise_log already
    covers. Never raises: a missing/misconfigured table must never break
    card creation, so failures are logged and swallowed here rather than
    propagating into process_article()'s outer try/except, which would
    otherwise misclassify a real created/updated result as an error.
    """
    try:
        supabase_client.table("routing_log").insert(
            {
                "headline": headline,
                "source_url": source_url,
                "classification": classification,
                "card_id": card_id,
                "confidence": confidence,
                "reason": reason,
                "run_id": run_id,
            }
        ).execute()
    except Exception as e:
        logger.warning("Failed to write routing_log row: %s", e)


def get_routing_log_by_run_id(run_id: str):
    response = (
        supabase_client.table("routing_log")
        .select("*")
        .eq("run_id", run_id)
        .order("logged_at", desc=True)
        .execute()
    )
    return response.data


def get_routing_log_for_card(card_id: str):
    response = (
        supabase_client.table("routing_log")
        .select("*")
        .eq("card_id", card_id)
        .order("logged_at", desc=True)
        .execute()
    )
    return response.data
