import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from config import FRESHNESS_HOURS
from db.noise_log import log_noise
from db.processed_articles import is_url_seen, mark_article_processed
from pipeline.simhash import (
    SIMHASH_THRESHOLD,
    TFIDF_THRESHOLD,
    compute_title_simhash,
    compute_tfidf_similarity,
    is_simhash_duplicate,
)

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


def _gate_1_url_uniqueness(article, seen_urls, run_id=None):
    url_hash = _url_hash(article["url"])
    # is_url_seen only covers prior runs (mark_article_processed fires at the
    # end of this run), so duplicates within the same batch need a local set.
    if url_hash in seen_urls or is_url_seen(url_hash):
        log_noise(
            headline=article.get("title", ""),
            source_url=article["url"],
            gate_failed="gate_1",
            reason="duplicate url",
            run_id=run_id,
        )
        return False
    seen_urls.add(url_hash)
    article["_url_hash"] = url_hash
    return True


def _find_simhash_match_index(new_hash, seen_simhashes, threshold=SIMHASH_THRESHOLD):
    new_val = int(new_hash)
    for idx, existing in enumerate(seen_simhashes):
        if bin(new_val ^ int(existing)).count("1") <= threshold:
            return idx
    return None


def _find_tfidf_match_index(new_text, seen_texts, threshold=TFIDF_THRESHOLD):
    best_index = None
    best_score = 0.0
    for idx, existing_text in enumerate(seen_texts):
        score = compute_tfidf_similarity(new_text, [existing_text])
        if score >= threshold and score > best_score:
            best_score = score
            best_index = idx
    return best_index


def _gate_2_dedup(article, seen_simhashes, seen_texts, seen_lengths, seen_articles, survivors, run_id=None):
    article["_headline_hash"] = _headline_hash(article.get("title", ""))

    title = article.get("title", "")
    content = article.get("content", "") or ""
    text = title + " " + content[:300]
    content_length = len(content)

    new_simhash = compute_title_simhash(title)

    # Stage A: SimHash on the title catches near-identical headlines cheaply.
    match_index = None
    if is_simhash_duplicate(new_simhash, seen_simhashes):
        match_index = _find_simhash_match_index(new_simhash, seen_simhashes)

    # Stage B: TF-IDF on title + content excerpt catches reworded headlines
    # that SimHash misses, since it only ever runs if Stage A found nothing.
    if match_index is None and seen_texts:
        match_index = _find_tfidf_match_index(text, seen_texts)

    # seen_simhashes/seen_texts/seen_lengths/seen_articles are kept in lockstep
    # so a matched index can recover the original article for logging/removal.
    if match_index is not None:
        existing_length = seen_lengths[match_index]
        existing_article = seen_articles[match_index]

        if content_length > existing_length:
            if existing_article in survivors:
                survivors.remove(existing_article)
            log_noise(
                headline=existing_article.get("title", ""),
                source_url=existing_article["url"],
                gate_failed="gate_2",
                reason="near-duplicate headline, shorter content discarded",
                run_id=run_id,
            )
            seen_simhashes[match_index] = new_simhash
            seen_texts[match_index] = text
            seen_lengths[match_index] = content_length
            seen_articles[match_index] = article
            return True

        log_noise(
            headline=article.get("title", ""),
            source_url=article["url"],
            gate_failed="gate_2",
            reason="near-duplicate headline, shorter content discarded",
            run_id=run_id,
        )
        return False

    seen_simhashes.append(new_simhash)
    seen_texts.append(text)
    seen_lengths.append(content_length)
    seen_articles.append(article)
    return True


def _gate_3_keyword_filter(article, run_id=None):
    title_lower = article.get("title", "").lower()
    for term in BLOCKLIST:
        if term in title_lower:
            log_noise(
                headline=article.get("title", ""),
                source_url=article["url"],
                gate_failed="gate_3",
                reason=f"blocked keyword: {term}",
                run_id=run_id,
            )
            return False
    return True


_AI_TECH_FRESHNESS_HOURS = 96


def _gate_4_freshness_check(article, run_id=None):
    now_sydney = datetime.now(SYDNEY_TZ)
    parsed = _parse_published_date(article.get("published_date"))

    domain = article.get("query_domain", "")
    freshness_hours = _AI_TECH_FRESHNESS_HOURS if domain == "ai_tech" else FRESHNESS_HOURS

    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed_sydney = parsed.astimezone(SYDNEY_TZ)

        # Reject articles from previous years immediately
        if parsed_sydney.year < now_sydney.year:
            log_noise(
                headline=article.get("title", ""),
                source_url=article["url"],
                gate_failed="gate_4",
                reason=f"article from previous year ({parsed_sydney.year}), rejected",
                run_id=run_id,
            )
            return None

        if now_sydney - parsed_sydney > timedelta(hours=freshness_hours):
            log_noise(
                headline=article.get("title", ""),
                source_url=article["url"],
                gate_failed="gate_4",
                reason=f"article older than {freshness_hours} hours",
                run_id=run_id,
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
        run_id=run_id,
    )
    return article


def run_filter_pipeline(articles, fetcher=None, run_id=None):
    # Gate 3 and Gate 4 first — cheap checks, no API calls or DB lookups,
    # so obvious noise is eliminated before paying for body enrichment.
    cheap_survivors = []
    for article in articles:
        if not _gate_3_keyword_filter(article, run_id=run_id):
            continue

        article = _gate_4_freshness_check(article, run_id=run_id)
        if article is None:
            continue

        cheap_survivors.append(article)

    if fetcher is not None:
        cheap_survivors = fetcher.enrich_articles_with_body(cheap_survivors)

    # Gate 1 and Gate 2 run on enriched content, so SimHash/TF-IDF dedup
    # sees full article bodies rather than RSS teaser text.
    survivors = []
    seen_simhashes = []
    seen_texts = []
    seen_lengths = []
    seen_articles = []
    seen_urls = set()

    for article in cheap_survivors:
        if not _gate_1_url_uniqueness(article, seen_urls, run_id=run_id):
            continue

        if not _gate_2_dedup(article, seen_simhashes, seen_texts, seen_lengths, seen_articles, survivors, run_id=run_id):
            continue

        survivors.append(article)

    for article in survivors:
        mark_article_processed(article["_url_hash"], article["_headline_hash"], article["url"])

    return survivors
