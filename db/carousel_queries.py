"""
Supabase persistence for the `carousels` table (Blueprint §7).

The `carousels` table does not exist yet. The Supabase anon key cannot run
DDL (DESIGN_LESSONS.md §6 — "Supabase anon key limitations") — run
CAROUSELS_TABLE_SQL in the Supabase SQL editor before these functions will
work. Implemented as if the table already exists, per instruction.
"""

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from db.client import supabase_client

from carousel.models import Carousel, CarouselStatus

CAROUSELS_TABLE_SQL = """
create table if not exists carousels (
  id uuid primary key default gen_random_uuid(),
  card_id text not null,
  card_version text not null,
  spec jsonb not null,
  slide_paths text[] not null default '{}',
  final_caption text not null,
  final_hashtags text[] not null default '{}',
  pinned_comment text not null,
  status text not null default 'draft',
  created_at timestamptz not null default now(),
  approved_at timestamptz,
  exported_at timestamptz,
  published_at timestamptz
);

create index if not exists idx_carousels_card_id on carousels(card_id);
create index if not exists idx_carousels_status on carousels(status);
"""


def upsert_carousel(carousel: Carousel) -> None:
    """Insert or update a carousel record."""
    data = {
        "id": str(carousel.id),
        "card_id": carousel.card_id,
        "card_version": carousel.card_version,
        "spec": json.loads(carousel.spec.model_dump_json()),
        "slide_paths": carousel.slide_paths,
        "final_caption": carousel.final_caption,
        "final_hashtags": carousel.final_hashtags,
        "pinned_comment": carousel.pinned_comment,
        "status": carousel.status.value,
        "created_at": carousel.created_at.isoformat(),
        "approved_at": carousel.approved_at.isoformat() if carousel.approved_at else None,
        "exported_at": carousel.exported_at.isoformat() if carousel.exported_at else None,
        "published_at": carousel.published_at.isoformat() if carousel.published_at else None,
    }
    supabase_client.table("carousels").upsert(data, on_conflict="id").execute()


def _carousel_from_row(row: dict) -> Carousel:
    return Carousel(
        id=row["id"],
        card_id=row["card_id"],
        card_version=row["card_version"],
        spec=row["spec"],
        slide_paths=row["slide_paths"],
        final_caption=row["final_caption"],
        final_hashtags=row["final_hashtags"],
        pinned_comment=row["pinned_comment"],
        status=CarouselStatus(row["status"]),
        created_at=row["created_at"],
        approved_at=row.get("approved_at"),
        exported_at=row.get("exported_at"),
        published_at=row.get("published_at"),
    )


def get_carousel(carousel_id: UUID) -> Optional[Carousel]:
    """Retrieve a carousel record by ID."""
    response = (
        supabase_client.table("carousels").select("*").eq("id", str(carousel_id)).execute()
    )
    if not response.data:
        return None

    return _carousel_from_row(response.data[0])


def get_carousel_by_card_id(card_id: str) -> Optional[Carousel]:
    """
    Retrieve the most recent carousel record for a given card, or None if
    the card has never had one generated. Uses the existing
    idx_carousels_card_id index. Lookup only — never triggers generation.
    """
    response = (
        supabase_client.table("carousels")
        .select("*")
        .eq("card_id", card_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None

    return _carousel_from_row(response.data[0])


def get_carousels_by_card_ids(card_ids: list) -> dict:
    """
    Batched version of get_carousel_by_card_id() — one query for every
    card_id in card_ids instead of one query per card (used by
    render_domain_tab() / the Archive expander in ui/app.py to look up an
    entire tab's worth of cards at once). Returns {card_id: Carousel} for
    the most recent carousel per card; card_ids with no carousel are
    simply absent from the returned dict.
    """
    if not card_ids:
        return {}

    response = (
        supabase_client.table("carousels")
        .select("*")
        .in_("card_id", card_ids)
        .order("created_at", desc=True)
        .execute()
    )

    result = {}
    for row in response.data:
        card_id = row["card_id"]
        if card_id not in result:
            # Rows arrive already sorted created_at DESC, so the first
            # row seen per card_id is its most recent carousel.
            result[card_id] = _carousel_from_row(row)
    return result


def update_carousel_status(carousel_id: UUID, status: CarouselStatus, timestamp_field: str) -> None:
    """Update status and corresponding timestamp."""
    update_data = {
        "status": status.value,
        timestamp_field: datetime.now(timezone.utc).isoformat(),
    }
    supabase_client.table("carousels").update(update_data).eq("id", str(carousel_id)).execute()


if __name__ == "__main__":
    print(CAROUSELS_TABLE_SQL)
