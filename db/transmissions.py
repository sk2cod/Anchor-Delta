from db.client import supabase_client


def upsert_transmission(card_id, chain_latex, nodes_markdown):
    response = (
        supabase_client.table("transmissions")
        .upsert(
            {
                "card_id": card_id,
                "chain_latex": chain_latex,
                "nodes_markdown": nodes_markdown,
            },
            on_conflict="card_id",
        )
        .execute()
    )
    return response.data[0]


def get_transmission_for_card(card_id):
    response = (
        supabase_client.table("transmissions")
        .select("*")
        .eq("card_id", card_id)
        .execute()
    )
    return response.data[0] if response.data else None
