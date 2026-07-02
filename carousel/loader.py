"""
CardLoader — retrieves a single Story Card from Supabase (Blueprint §5.1).

Pure database read. Decouples the carousel engine from the database layer:
everything downstream of load_card() receives a typed StoryCard, never a
raw dict. Reuses the existing db/ layer for all Supabase access rather than
querying the client directly (Decision #41 — carousel/ reads from db/, never
duplicates its access logic).

No cache in this implementation — the cache layer comes in Phase 3.
"""

from db.cards import get_card_by_id
from db.delta_events import get_delta_events_for_card
from db.transmissions import get_transmission_for_card

from carousel.models import DeltaEvent, StoryCard, Transmission


class CardNotFoundError(Exception):
    pass


class CardLoadError(Exception):
    pass


def load_card(card_id: str) -> StoryCard:
    """
    Retrieve a single Story Card from Supabase.
    Raises CardNotFoundError if card_id does not exist.
    Raises CardLoadError if database call fails.
    """
    try:
        card_row = get_card_by_id(card_id)
    except Exception as e:
        raise CardLoadError(f"Failed to fetch cards row for {card_id!r}") from e

    if card_row is None:
        raise CardNotFoundError(f"No card found with id={card_id!r}")

    try:
        delta_rows = get_delta_events_for_card(card_id)
        transmission_row = get_transmission_for_card(card_id)

        delta_events = [
            DeltaEvent(
                id=row["id"],
                event_date=row["event_date"],
                headline=row["headline"],
                what_happened=row["what_happened"],
                dialogue=row.get("dialogue") or [],
                tldr=row.get("tldr"),
                created_at=row["created_at"],
            )
            for row in delta_rows
        ]

        transmission = (
            Transmission(
                chain_latex=transmission_row["chain_latex"],
                nodes_markdown=transmission_row["nodes_markdown"],
                updated_at=transmission_row["updated_at"],
            )
            if transmission_row is not None
            else None
        )

        return StoryCard(
            id=card_row["id"],
            domain=card_row["domain"],
            umbrella_title=card_row["umbrella_title"],
            anchor_text=card_row["anchor_text"],
            is_archived=card_row["is_archived"],
            created_at=card_row["created_at"],
            last_delta_at=card_row["last_delta_at"],
            delta_events=delta_events,
            transmission=transmission,
        )
    except Exception as e:
        raise CardLoadError(f"Failed to load card {card_id!r}") from e
