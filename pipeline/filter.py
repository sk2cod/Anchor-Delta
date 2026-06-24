import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from db.noise_log import log_noise
from db.processed_articles import is_url_seen, mark_article_processed

SYDNEY_TZ = ZoneInfo("Australia/Sydney")

_KEYWORDS_PATH = os.path.join(os.path.dirname(__file__), "keywords.json")
with open(_KEYWORDS_PATH, "r", encoding="utf-8") as _f:
    _KEYWORDS = json.load(_f)

BLOCKLIST = _KEYWORDS["blocklist"]


def _canonical_url(url):
    return url.strip().lower().rstrip("/")


def _url_hash(url):
    return hashlib.sha256(_canonical_url(url).encode("utf-8")).hexdigest()


def _normalised_headline(headline):
    text = headline.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _headline_hash(headline):
    return hashlib.sha256(_normalised_headline(headline).encode("utf-8")).hexdigest()


def _parse_published_date(date_str):
    if not date_str:
        return None
    text = date_str.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    return None


def _gate_1_url_uniqueness(article, seen_urls):
    url_hash = _url_hash(article["url"])
    # is_url_seen only covers prior runs (mark_article_processed fires at the
    # end of this run), so duplicates within the same batch need a local set.
    if url_hash in seen_urls or is_url_seen(url_hash):
        log_noise(
            headline=article.get("title", ""),
            source_url=article["url"],
            gate_failed="gate_1",
            reason="duplicate url",
        )
        return False
    seen_urls.add(url_hash)
    article["_url_hash"] = url_hash
    return True


def _gate_2_headline_dedup(article, seen_headlines, survivors):
    headline_hash = _headline_hash(article.get("title", ""))
    article["_headline_hash"] = headline_hash

    existing_entry = seen_headlines.get(headline_hash)

    # Duplicate headlines are compared against the best candidate seen so far
    # in this run, not a stored content length (processed_articles only keeps
    # hashes), so the longer-content survivor can only be decided in-memory.
    if existing_entry is not None:
        existing_article = existing_entry["article"]
        if len(article.get("content", "")) > len(existing_article.get("content", "")):
            if existing_entry["in_survivors"]:
                survivors.remove(existing_article)
            log_noise(
                headline=existing_article.get("title", ""),
                source_url=existing_article["url"],
                gate_failed="gate_2",
                reason="duplicate headline, shorter content",
            )
            seen_headlines[headline_hash] = {"article": article, "in_survivors": False}
            return True
        else:
            log_noise(
                headline=article.get("title", ""),
                source_url=article["url"],
                gate_failed="gate_2",
                reason="duplicate headline, shorter content",
            )
            return False

    seen_headlines[headline_hash] = {"article": article, "in_survivors": False}
    return True


def _gate_3_keyword_filter(article):
    title_lower = article.get("title", "").lower()
    for term in BLOCKLIST:
        if term in title_lower:
            log_noise(
                headline=article.get("title", ""),
                source_url=article["url"],
                gate_failed="gate_3",
                reason=f"blocked keyword: {term}",
            )
            return False
    return True


def _gate_4_freshness_check(article):
    now_sydney = datetime.now(SYDNEY_TZ)
    parsed = _parse_published_date(article.get("published_date"))

    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed_sydney = parsed.astimezone(SYDNEY_TZ)

        if now_sydney - parsed_sydney > timedelta(hours=48):
            log_noise(
                headline=article.get("title", ""),
                source_url=article["url"],
                gate_failed="gate_4",
                reason="article older than 48 hours",
            )
            return None

        article["published_date"] = parsed_sydney.isoformat()
        return article

    article["published_date"] = now_sydney.isoformat()
    article["timestamp_fallback"] = True
    log_noise(
        headline=article.get("title", ""),
        source_url=article["url"],
        gate_failed="gate_4_warning",
        reason="missing timestamp, fallback applied",
    )
    return article


def run_filter_pipeline(articles):
    survivors = []
    seen_headlines = {}
    seen_urls = set()

    for article in articles:
        if not _gate_1_url_uniqueness(article, seen_urls):
            continue

        if not _gate_2_headline_dedup(article, seen_headlines, survivors):
            continue

        if not _gate_3_keyword_filter(article):
            continue

        article = _gate_4_freshness_check(article)
        if article is None:
            continue

        survivors.append(article)
        seen_headlines[article["_headline_hash"]]["in_survivors"] = True

    for article in survivors:
        mark_article_processed(article["_url_hash"], article["_headline_hash"], article["url"])

    return survivors
