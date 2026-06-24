import sys
from datetime import date, datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from db.cards import archive_card, get_active_card_count, get_card_by_id
from db.delta_events import get_delta_events_for_card
from db.transmissions import get_transmission_for_card
from pipeline.orchestrator import process_article

TODAY_STR = date.today().strftime("%B %d, %Y")
NOW_ISO = datetime.now(timezone.utc).isoformat()

ARTICLE_1_CONTENT = f"""Tensions between Washington and Tehran escalated again on {TODAY_STR} as the United States and Iran resumed indirect nuclear talks even as the Pentagon confirmed it was extending its naval blockade in the Persian Gulf for an additional 30 days. The announcement came hours after President Trump addressed reporters outside the White House.

"We are not going to back down. Iran knows exactly what they need to do, and the blockade stays in place until they do it," Trump said, gesturing toward a stack of briefing papers on uranium enrichment levels.

Iranian Foreign Minister Abbas Araghchi responded within hours from Tehran, calling the blockade extension an act of economic warfare disguised as diplomacy.

"This blockade is strangling our economy while they pretend to negotiate in good faith. We will not be cornered into concessions at gunpoint," Araghchi told state television.

Despite the sharp rhetoric, both sides confirmed that technical-level talks would resume in Oman later this week, mediated by Omani Foreign Minister Badr al-Busaidi. US officials said the blockade was intended to pressure Tehran into accepting stricter inspection terms on its enrichment facilities, while Iranian officials maintained the program remained for civilian energy purposes only.

The extended blockade has already rippled through global energy markets. Brent crude oil prices rose above $95 a barrel in early trading, the highest level in fourteen months, as shipping insurers warned of further premium increases if tanker traffic through the Gulf is disrupted.

Analysts say the dual-track approach of talks alongside military pressure reflects a deliberate strategy by the Trump administration to negotiate from a position of maximum leverage. Iranian officials, for their part, signaled they would attend the Oman talks but warned that continued blockade enforcement could collapse the process before it begins.

Markets and regional governments are now watching closely to see whether the Oman talks produce any breakthrough before the 30-day blockade extension lapses."""

ARTICLE_2_CONTENT = f"""The Federal Reserve voted unanimously on {TODAY_STR} to hold its benchmark interest rate steady in a range of 4.25% to 4.50%, extending a pause that has now lasted five consecutive meetings as policymakers weigh persistent inflation against signs of a cooling labor market.

"We need to see more consistent progress on inflation before we can responsibly cut rates," Federal Reserve Chair Jerome Powell said at a press conference following the announcement. "The data has been mixed, and mixed data calls for patience, not haste."

Treasury Secretary Scott Bessent struck a more urgent tone in a separate briefing, urging the central bank to move faster given the strain on households.

"Every month of delay is a month families spend paying more on their mortgages and credit cards than they should have to," Bessent said. "We need to see decisive action, not another quarter of waiting."

The decision to hold rates steady triggered an immediate reaction in housing markets. Mortgage applications fell 8% in the week following the announcement, according to data from the Mortgage Bankers Association, as the average 30-year fixed mortgage rate climbed back above 7%.

Wall Street's reaction was muted but cautious, with major indices closing slightly lower as traders recalibrated expectations for the timing of the first rate cut. Several large banks pushed back their forecasts for an initial cut from the third quarter to the fourth quarter of the year.

Powell acknowledged the political pressure but maintained that the Fed's decisions would remain data-dependent rather than calendar-dependent. "We don't set policy based on a calendar. We set it based on what the data tells us," he said.

The next policy meeting is scheduled for early next month, with markets now pricing in roughly even odds of a rate cut."""

ARTICLE_3_CONTENT = f"""Iran threatened on {TODAY_STR} to close the Strait of Hormuz entirely, escalating its standoff with Washington just days after the United States extended its naval blockade in the Persian Gulf for an additional 30 days.

Iranian Foreign Minister Abbas Araghchi delivered the warning during a televised address, framing it as a direct response to the blockade extension announced earlier this week.

"If the United States continues to strangle our economy through this blockade, we will close the Strait of Hormuz and let the world see what their pressure campaign has truly cost them," Araghchi said.

President Trump dismissed the threat hours later while speaking to reporters at the White House, reiterating that the blockade would remain in place regardless of Tehran's rhetoric.

"They have made this threat before, and we are ready for it. The blockade stays. If they want to escalate, that is their choice, not ours," Trump said.

The Strait of Hormuz, through which roughly a fifth of the world's oil supply passes daily, has long been viewed as Iran's most powerful point of leverage in any confrontation with the West. Shipping analysts say even the threat of closure, without follow-through, is already reshaping risk calculations across the industry.

Tanker insurance premiums for vessels transiting the Gulf doubled within hours of Araghchi's statement, according to two London-based maritime insurers, as underwriters priced in the rising probability of disruption.

Regional governments, including Saudi Arabia and the United Arab Emirates, urged restraint from both sides, warning that any closure of the strait would have catastrophic consequences for global energy supply. Omani officials said the upcoming talks in Muscat were now at greater risk of collapse than at any point since they were announced.

Oil traders are bracing for further volatility as both sides show no sign of backing down."""

ARTICLE_1 = {
    "url": "https://example.com/test/us-iran-blockade-talks",
    "title": "US and Iran Resume Nuclear Talks as Naval Blockade Tightens",
    "content": ARTICLE_1_CONTENT,
    "published_date": NOW_ISO,
    "source_domain": "example.com",
    "query_domain": "geopolitics",
}

ARTICLE_2 = {
    "url": "https://example.com/test/fed-holds-rates-steady",
    "title": "Federal Reserve Holds Rates Steady Amid Persistent Inflation",
    "content": ARTICLE_2_CONTENT,
    "published_date": NOW_ISO,
    "source_domain": "example.com",
    "query_domain": "finance",
}

ARTICLE_3 = {
    "url": "https://example.com/test/iran-hormuz-threat",
    "title": "Iran Threatens Hormuz Closure After US Extends Naval Blockade",
    "content": ARTICLE_3_CONTENT,
    "published_date": NOW_ISO,
    "source_domain": "example.com",
    "query_domain": "geopolitics",
}


def fail(step, message):
    print(f"FAIL [{step}]: {message}")
    sys.exit(1)


def print_card_quality_review(card_id):
    card = get_card_by_id(card_id)
    delta_events = get_delta_events_for_card(card_id)
    transmission = get_transmission_for_card(card_id)

    print("==================== CARD 1 QUALITY REVIEW ====================")
    print(f"UMBRELLA: {card['umbrella_title']}")
    print(f"ANCHOR: {card['anchor_text']}")
    print("--- DELTA EVENTS ---")
    for event in delta_events:
        print(f"event_date: {event['event_date']}")
        print(f"headline: {event['headline']}")
        print(f"what_happened: {event['what_happened']}")
        print(f"dialogue: {event['dialogue']}")
        print()
    print("--- TRANSMISSION ---")
    if transmission:
        print(f"CHAIN: {transmission['chain_latex']}")
        print(f"NODES: {transmission['nodes_markdown']}")
    print("===============================================================")


def main():
    result_1 = process_article(ARTICLE_1)
    if result_1.get("status") != "created":
        fail("article_1", f"Expected status 'created', got {result_1}")
    card_1_id = result_1["card_id"]
    print(f"PASS [article_1]: created card {card_1_id}")

    result_2 = process_article(ARTICLE_2)
    if result_2.get("status") != "created":
        fail("article_2", f"Expected status 'created', got {result_2}")
    card_2_id = result_2["card_id"]
    print(f"PASS [article_2]: created card {card_2_id}")

    result_3 = process_article(ARTICLE_3)
    if result_3.get("status") != "updated":
        fail("article_3", f"Expected status 'updated', got {result_3}")
    if result_3.get("card_id") != card_1_id:
        fail(
            "article_3",
            f"Expected card_id {card_1_id}, got {result_3.get('card_id')}",
        )
    print(f"PASS [article_3]: updated card {card_1_id}")

    events_1 = get_delta_events_for_card(card_1_id)
    if len(events_1) < 2:
        fail("delta_events_card_1", f"Expected at least 2 events, got {len(events_1)}")
    print(f"PASS [delta_events_card_1]: {len(events_1)} events found")

    events_2 = get_delta_events_for_card(card_2_id)
    if len(events_2) < 1:
        fail("delta_events_card_2", f"Expected at least 1 event, got {len(events_2)}")
    print(f"PASS [delta_events_card_2]: {len(events_2)} events found")

    transmission_1 = get_transmission_for_card(card_1_id)
    if transmission_1 is None:
        fail("transmission_card_1", "Expected a transmission, got None")
    print("PASS [transmission_card_1]: transmission found")

    transmission_2 = get_transmission_for_card(card_2_id)
    if transmission_2 is None:
        fail("transmission_card_2", "Expected a transmission, got None")
    print("PASS [transmission_card_2]: transmission found")

    active_count = get_active_card_count()
    if active_count != 2:
        fail("active_card_count", f"Expected exactly 2 active cards, got {active_count}")
    print("PASS [active_card_count]: exactly 2 active cards")

    print()
    print_card_quality_review(card_1_id)
    print()

    archive_card(card_1_id)
    archive_card(card_2_id)
    print("PASS [cleanup]: both test cards archived")

    print("Phase 4 LLM engine: ALL TESTS PASSED")


if __name__ == "__main__":
    main()
