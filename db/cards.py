from datetime import datetime, timedelta, timezone

from db.client import supabase_client


def create_card(domain, umbrella_title, anchor_text):
    response = (
        supabase_client.table("cards")
        .insert(
            {
                "domain": domain,
                "umbrella_title": umbrella_title,
                "anchor_text": anchor_text,
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
