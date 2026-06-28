from datetime import date

from db.client import supabase_client


def append_delta_event(card_id, event_date, headline, what_happened, dialogue, tldr=None):
    if isinstance(event_date, date):
        event_date = event_date.isoformat()

    response = (
        supabase_client.table("delta_events")
        .insert(
            {
                "card_id": card_id,
                "event_date": event_date,
                "headline": headline,
                "what_happened": what_happened,
                "dialogue": dialogue,
                "tldr": tldr,
            }
        )
        .execute()
    )
    return response.data[0]


def get_delta_events_for_card(card_id):
    response = (
        supabase_client.table("delta_events")
        .select("*")
        .eq("card_id", card_id)
        .order("event_date", desc=True)
        .execute()
    )
    return response.data


def get_last_run_per_domain() -> dict:
    """Returns dict of domain -> most recent delta_event created_at timestamp."""
    domains = ['world', 'finance', 'ai_tech', 'australia', 'india']
    result = {}
    for domain in domains:
        cards = supabase_client.table('cards').select('id').eq('domain', domain).execute()
        card_ids = [c['id'] for c in cards.data]
        if not card_ids:
            result[domain] = None
            continue
        delta = (
            supabase_client.table('delta_events')
            .select('created_at')
            .in_('card_id', card_ids)
            .order('created_at', desc=True)
            .limit(1)
            .execute()
        )
        result[domain] = delta.data[0]['created_at'] if delta.data else None
    return result
