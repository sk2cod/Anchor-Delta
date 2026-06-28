import logging
from datetime import datetime, timedelta, timezone

from db.client import supabase_client

logger = logging.getLogger(__name__)


def create_card(domain, umbrella_title, anchor_text, source='pipeline'):
    response = (
        supabase_client.table("cards")
        .insert(
            {
                "domain": domain,
                "umbrella_title": umbrella_title,
                "anchor_text": anchor_text,
                "source": source,
            }
        )
        .execute()
    )
    return response.data[0]


def get_active_cards(domain=None):
    query = supabase_client.table("cards").select("*").eq("is_archived", False)
    if domain is not None:
        query = query.eq("domain", domain)
    response = query.order("last_delta_at", desc=True).execute()
    return response.data


def get_archived_cards(domain=None):
    query = supabase_client.table("cards").select("*").eq("is_archived", True)
    if domain is not None:
        query = query.eq("domain", domain)
    response = query.order("last_delta_at", desc=True).execute()
    return response.data


def get_card_by_id(card_id):
    response = supabase_client.table("cards").select("*").eq("id", card_id).execute()
    return response.data[0] if response.data else None


def get_active_card_count():
    response = (
        supabase_client.table("cards")
        .select("id", count="exact")
        .eq("is_archived", False)
        .execute()
    )
    return response.count


def update_last_delta_at(card_id):
    supabase_client.table("cards").update(
        {"last_delta_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", card_id).execute()


def archive_card(card_id):
    supabase_client.table("cards").update({"is_archived": True}).eq(
        "id", card_id
    ).execute()


def get_cards_due_for_archive(days=14):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    response = (
        supabase_client.table("cards")
        .select("*")
        .eq("is_archived", False)
        .lt("last_delta_at", cutoff)
        .execute()
    )
    return response.data


def delete_card(card_id: str):
    supabase_client.table('delta_events').delete().eq('card_id', card_id).execute()
    supabase_client.table('transmissions').delete().eq('card_id', card_id).execute()
    supabase_client.table('cards').delete().eq('id', card_id).execute()


def archive_stale_cards(days: int = 7) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = supabase_client.table("cards")\
        .select("id, umbrella_title, last_delta_at")\
        .eq("is_archived", False)\
        .lt("last_delta_at", cutoff)\
        .execute()
    archived_count = 0
    for card in result.data:
        supabase_client.table("cards")\
            .update({"is_archived": True})\
            .eq("id", card["id"])\
            .execute()
        archived_count += 1
        logger.info(f"Auto-archived stale card: {card['umbrella_title']}")
    return archived_count


def hard_delete_all_cards() -> dict:
    from db.client import supabase_client
    d1 = supabase_client.table('delta_events').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
    d2 = supabase_client.table('transmissions').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
    d3 = supabase_client.table('cards').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
    d4 = supabase_client.table('noise_log').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
    d5 = supabase_client.table('processed_articles').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
    return {
        "delta_events": len(d1.data),
        "transmissions": len(d2.data),
        "cards": len(d3.data),
        "noise_log": len(d4.data),
        "processed_articles": len(d5.data),
    }
