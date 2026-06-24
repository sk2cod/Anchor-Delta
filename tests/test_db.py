import sys

from db.cards import create_card, get_active_cards, get_card_by_id
from db.client import supabase_client
from db.delta_events import append_delta_event, get_delta_events_for_card
from db.noise_log import get_noise_log_since, log_noise
from db.processed_articles import (
    is_headline_seen,
    is_url_seen,
    mark_article_processed,
)
from db.transmissions import get_transmission_for_card, upsert_transmission

TEST_DOMAIN = "australia"
TEST_UMBRELLA_TITLE = "Phase 2 Verification Card"
TEST_ANCHOR_TEXT = "This is a sample anchor text for the phase 2 verification card."
TEST_URL_HASH = "phase2-test-url-hash"
TEST_HEADLINE_HASH = "phase2-test-headline-hash"
TEST_SOURCE_URL = "https://example.com/phase2-test-article"


def fail(step, message):
    print(f"FAIL [{step}]: {message}")
    sys.exit(1)


def main():
    card_id = None

    # 1. Insert one test card
    card = create_card(TEST_DOMAIN, TEST_UMBRELLA_TITLE, TEST_ANCHOR_TEXT)
    if not card or not card.get("id"):
        fail("create_card", "No card returned from create_card()")
    card_id = card["id"]
    print(f"PASS [create_card]: created card {card_id}")

    # 2. Retrieve via get_active_cards and confirm it appears
    active_cards = get_active_cards(domain=TEST_DOMAIN)
    if not any(c["id"] == card_id for c in active_cards):
        fail("get_active_cards", "Test card not found in active cards for domain")
    print("PASS [get_active_cards]: test card found")

    # 3. Append one delta event with a two-item dialogue array
    dialogue = [
        {"speaker": "Anchor", "line": "What happened today?"},
        {"speaker": "Delta", "line": "Here is the update."},
    ]
    event = append_delta_event(
        card_id=card_id,
        event_date="2026-06-24",
        headline="Test Delta Event Headline",
        what_happened="A sample event occurred for verification purposes.",
        dialogue=dialogue,
    )
    if not event or not event.get("id"):
        fail("append_delta_event", "No delta event returned")
    print(f"PASS [append_delta_event]: created event {event['id']}")

    # 4. Retrieve delta events and confirm dialogue JSONB round-trips
    events = get_delta_events_for_card(card_id)
    if not events:
        fail("get_delta_events_for_card", "No delta events returned for card")
    retrieved_dialogue = events[0]["dialogue"]
    if retrieved_dialogue != dialogue:
        fail(
            "get_delta_events_for_card",
            f"Dialogue round-trip mismatch: {retrieved_dialogue} != {dialogue}",
        )
    print("PASS [get_delta_events_for_card]: dialogue JSONB round-tripped correctly")

    # 5. Upsert a transmission
    chain_latex = r"\\(A \\rightarrow B \\rightarrow C\\)"
    nodes_markdown = "- Node A\n- Node B\n- Node C"
    transmission = upsert_transmission(card_id, chain_latex, nodes_markdown)
    if not transmission or not transmission.get("id"):
        fail("upsert_transmission", "No transmission returned")
    print(f"PASS [upsert_transmission]: upserted transmission {transmission['id']}")

    # 6. Retrieve transmission and confirm both fields intact
    fetched_transmission = get_transmission_for_card(card_id)
    if not fetched_transmission:
        fail("get_transmission_for_card", "No transmission found for card")
    if (
        fetched_transmission["chain_latex"] != chain_latex
        or fetched_transmission["nodes_markdown"] != nodes_markdown
    ):
        fail("get_transmission_for_card", "Transmission fields do not match")
    print("PASS [get_transmission_for_card]: chain_latex and nodes_markdown intact")

    # 7. Mark a test article as processed
    mark_article_processed(TEST_URL_HASH, TEST_HEADLINE_HASH, TEST_SOURCE_URL)
    print("PASS [mark_article_processed]: article marked as processed")

    # 8. Confirm is_url_seen returns True
    if not is_url_seen(TEST_URL_HASH):
        fail("is_url_seen", "Expected True for known url_hash, got False")
    print("PASS [is_url_seen]: returned True for known url_hash")

    # 9. Confirm is_headline_seen returns True
    if not is_headline_seen(TEST_HEADLINE_HASH):
        fail("is_headline_seen", "Expected True for known headline_hash, got False")
    print("PASS [is_headline_seen]: returned True for known headline_hash")

    # 10. Log one noise entry
    log_noise(
        headline="Test Noise Headline",
        source_url="https://example.com/phase2-noise-article",
        gate_failed="gate_3",
        reason="Sample reason for verification purposes.",
    )
    print("PASS [log_noise]: noise entry logged")

    # 11. Retrieve via get_noise_log_since and confirm it appears
    noise_entries = get_noise_log_since(hours=1)
    if not any(n["headline"] == "Test Noise Headline" for n in noise_entries):
        fail("get_noise_log_since", "Test noise entry not found in recent log")
    print("PASS [get_noise_log_since]: test noise entry found")

    # 12. Delete the test card (cascade cleans up delta_events and transmissions)
    supabase_client.table("cards").delete().eq("id", card_id).execute()
    if get_card_by_id(card_id) is not None:
        fail("delete_card", "Test card still exists after delete")
    print("PASS [delete_card]: test card and cascaded rows removed")

    print("Phase 2 database layer: ALL TESTS PASSED")


if __name__ == "__main__":
    main()
