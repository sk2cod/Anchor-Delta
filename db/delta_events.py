from db.client import supabase_client


def append_delta_event(card_id, event_date, headline, what_happened, dialogue):
    response = (
        supabase_client.table("delta_events")
        .insert(
            {
                "card_id": card_id,
                "event_date": event_date,
                "headline": headline,
                "what_happened": what_happened,
                "dialogue": dialogue,
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
