import sys
import uuid
from datetime import datetime, timedelta, timezone

from db.noise_log import get_noise_log_since
from pipeline.filter import run_filter_pipeline

# Unique per run so repeated executions don't collide with prior runs' rows
# in processed_articles (gate 1 / gate 2 dedup is partly DB-backed).
RUN_ID = uuid.uuid4().hex[:8]

NOW = datetime.now(timezone.utc)
FRESH = NOW.isoformat()
STALE = (NOW - timedelta(hours=72)).isoformat()

QUOTE_CONTENT = (
    '"We have reached a historic agreement on this issue," the minister said '
    "in a statement to reporters this afternoon."
)
ACTION_CONTENT = "The government announced new measures following a lengthy review process."
NO_SIGNAL_CONTENT = (
    "The committee held a routine meeting to go over budget line items and "
    "reviewed the minutes from the previous session."
)


def article(url, title, content, published_date, domain="top_stories"):
    return {
        "url": url,
        "title": title,
        "content": content,
        "published_date": published_date,
        "source_domain": "example.com",
        "query_domain": domain,
    }


# --- 2 exact URL duplicates (gate 1) ---
url_dup_url = f"https://example.com/{RUN_ID}/url-dup-story"
url_dup_a = article(url_dup_url, f"First Report On Url Dup Story {RUN_ID}", QUOTE_CONTENT, FRESH)
url_dup_b = article(url_dup_url, f"Second Report On Url Dup Story {RUN_ID}", QUOTE_CONTENT, FRESH)

# --- 2 identical normalised headlines, different content lengths (gate 2) ---
headline_dup_short = article(
    f"https://example.com/{RUN_ID}/headline-dup-short",
    f"Global Leaders Meet For Summit {RUN_ID}",
    ACTION_CONTENT,
    FRESH,
)
headline_dup_long = article(
    f"https://example.com/{RUN_ID}/headline-dup-long",
    f"global leaders meet for summit {RUN_ID}!!!",
    ACTION_CONTENT + " " + QUOTE_CONTENT + " Additional follow-up detail and context.",
    FRESH,
)

# --- 2 blocklisted keywords in title (gate 3) ---
blocklist_football = article(
    f"https://example.com/{RUN_ID}/football-story",
    f"Local Football Match Ends In Dramatic Finish {RUN_ID}",
    QUOTE_CONTENT,
    FRESH,
)
blocklist_celebrity = article(
    f"https://example.com/{RUN_ID}/celebrity-story",
    f"Celebrity Couple Seen At Awards Show {RUN_ID}",
    QUOTE_CONTENT,
    FRESH,
)

# --- 1 article older than 48 hours (gate 4 failure) ---
stale_article = article(
    f"https://example.com/{RUN_ID}/stale-story",
    f"Stale Report From Last Week {RUN_ID}",
    QUOTE_CONTENT,
    STALE,
)

# --- 1 article with no timestamp (gate 4 lenient pass) ---
no_timestamp_article = article(
    f"https://example.com/{RUN_ID}/no-timestamp-story",
    f"Undated Report On Ongoing Talks {RUN_ID}",
    ACTION_CONTENT,
    None,
)

# --- 2 articles with no signal density (gate 5 failure) ---
no_signal_a = article(
    f"https://example.com/{RUN_ID}/no-signal-a",
    f"Routine Committee Meeting Held {RUN_ID}",
    NO_SIGNAL_CONTENT,
    FRESH,
)
no_signal_b = article(
    f"https://example.com/{RUN_ID}/no-signal-b",
    f"Quarterly Review Process Continues {RUN_ID}",
    NO_SIGNAL_CONTENT,
    FRESH,
)

# --- 5 clean articles that should survive all five gates ---
clean_articles = [
    article(
        f"https://example.com/{RUN_ID}/clean-1",
        f"Clean Story One About Talks {RUN_ID}",
        QUOTE_CONTENT,
        FRESH,
    ),
    article(
        f"https://example.com/{RUN_ID}/clean-2",
        f"Clean Story Two About Sanctions {RUN_ID}",
        "Officials confirmed new sanctions were imposed on several entities today.",
        FRESH,
    ),
    article(
        f"https://example.com/{RUN_ID}/clean-3",
        f"Clean Story Three About Deployment {RUN_ID}",
        "Troops were deployed to the region as a result of the escalating conflict.",
        FRESH,
    ),
    article(
        f"https://example.com/{RUN_ID}/clean-4",
        f"Clean Story Four About Agreement {RUN_ID}",
        ACTION_CONTENT,
        FRESH,
    ),
    article(
        f"https://example.com/{RUN_ID}/clean-5",
        f"Clean Story Five About Warning {RUN_ID}",
        "The agency warned of further disruption following the policy change.",
        FRESH,
    ),
]

CORPUS = (
    [url_dup_a, url_dup_b]
    + [headline_dup_short, headline_dup_long]
    + [blocklist_football, blocklist_celebrity]
    + [stale_article]
    + [no_timestamp_article]
    + [no_signal_a, no_signal_b]
    + clean_articles
)

EXPECTED_SURVIVOR_COUNT = 8  # url-dup winner, headline-dup winner, no-timestamp, 5 clean

EXPECTED_DISCARDS = {
    url_dup_b["url"]: "gate_1",
    headline_dup_short["url"]: "gate_2",
    blocklist_football["url"]: "gate_3",
    blocklist_celebrity["url"]: "gate_3",
    stale_article["url"]: "gate_4",
    no_signal_a["url"]: "gate_5",
    no_signal_b["url"]: "gate_5",
}


def fail(step, message):
    print(f"FAIL [{step}]: {message}")
    sys.exit(1)


def main():
    assert len(CORPUS) == 15, f"Corpus must have 15 articles, has {len(CORPUS)}"

    survivors = run_filter_pipeline(CORPUS)

    if len(survivors) != EXPECTED_SURVIVOR_COUNT:
        fail(
            "survivor_count",
            f"Expected {EXPECTED_SURVIVOR_COUNT} survivors, got {len(survivors)}: "
            f"{[a['url'] for a in survivors]}",
        )
    print(f"PASS [survivor_count]: {len(survivors)} articles survived as expected")

    survivor_urls = {a["url"] for a in survivors}

    if url_dup_a["url"] not in survivor_urls:
        fail("gate_1_survivor", "First url-dup article should have survived gate 1")
    print("PASS [gate_1_survivor]: first occurrence of duplicated URL survived")

    if headline_dup_long["url"] not in survivor_urls:
        fail("gate_2_survivor", "Longer duplicate-headline article should have survived")
    if headline_dup_short["url"] in survivor_urls:
        fail("gate_2_survivor", "Shorter duplicate-headline article should NOT have survived")
    print("PASS [gate_2_survivor]: longer duplicate-headline article survived")

    no_ts_survivor = next(
        (a for a in survivors if a["url"] == no_timestamp_article["url"]), None
    )
    if no_ts_survivor is None:
        fail("gate_4_lenient", "No-timestamp article should have survived with fallback")
    if no_ts_survivor.get("timestamp_fallback") is not True:
        fail("gate_4_lenient", "No-timestamp survivor missing timestamp_fallback=True")
    print("PASS [gate_4_lenient]: no-timestamp article survived with timestamp_fallback=True")

    for clean in clean_articles:
        if clean["url"] not in survivor_urls:
            fail("clean_survivors", f"Clean article should have survived: {clean['url']}")
    print("PASS [clean_survivors]: all 5 clean articles survived")

    noise_entries = get_noise_log_since(hours=1)
    noise_by_url = {}
    for entry in noise_entries:
        noise_by_url.setdefault(entry["source_url"], []).append(entry)

    for url, expected_gate in EXPECTED_DISCARDS.items():
        entries = noise_by_url.get(url)
        if not entries:
            fail("noise_log", f"No noise_log entry found for discarded article {url}")
        if not any(e["gate_failed"] == expected_gate for e in entries):
            fail(
                "noise_log",
                f"noise_log entry for {url} did not have gate_failed={expected_gate}, "
                f"got {[e['gate_failed'] for e in entries]}",
            )
    print("PASS [noise_log]: every discarded article logged with correct gate_failed")

    fallback_entries = noise_by_url.get(no_timestamp_article["url"], [])
    if not any(e["gate_failed"] == "gate_4_warning" for e in fallback_entries):
        fail("noise_log_warning", "No gate_4_warning noise_log entry for no-timestamp article")
    print("PASS [noise_log_warning]: gate_4_warning logged for no-timestamp article")

    print("Phase 3 filter pipeline: ALL TESTS PASSED")


if __name__ == "__main__":
    main()
