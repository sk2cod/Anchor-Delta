import logging

from config import ALL_DOMAINS_COST_GUARD_USD, DOMAIN_COST_GUARD_USD, STALE_CARD_DAYS
from db.cards import archive_stale_cards, get_active_cards
from db.noise_log import log_noise
from pipeline.engine import get_run_stats, reset_run_stats
from pipeline.fetcher import TavilyFetcher
from pipeline.filter import run_filter_pipeline
from pipeline.orchestrator import process_article

logger = logging.getLogger(__name__)


def run_pipeline(extra_queries: list[str] = None, progress_callback=None, domain=None):
    reset_run_stats()
    cost_limit = DOMAIN_COST_GUARD_USD if domain is not None else ALL_DOMAINS_COST_GUARD_USD

    archived = archive_stale_cards(days=STALE_CARD_DAYS)
    if archived > 0:
        logger.info(f"Auto-archived {archived} stale cards")

    fetcher = TavilyFetcher()

    rss_articles = fetcher.fetch_rss_articles(domain=domain)
    fixed_articles = fetcher.fetch_user_queries(extra_queries=extra_queries)
    active_cards = get_active_cards()
    try:
        dynamic_articles = fetcher.fetch_dynamic_queries(active_cards)
    except Exception as e:
        logger.warning(f"Tavily dynamic queries failed: {e}")
        dynamic_articles = []

    if domain is not None:
        fixed_articles = [a for a in fixed_articles if a.get("query_domain") == domain]
        dynamic_articles = [a for a in dynamic_articles if a.get("query_domain") == domain]

    combined = rss_articles + fixed_articles + dynamic_articles

    fetch_stats = {
        "rss_fetched": len(rss_articles),
        "dynamic_fetched": len(dynamic_articles),
        "total_fetched": len(combined),
        "survived_filter": 0,
        "reached_llm": 0,
    }

    seen_urls = set()
    deduped = []
    for article in combined:
        if article["url"] in seen_urls:
            continue
        seen_urls.add(article["url"])
        deduped.append(article)

    survivors = run_filter_pipeline(deduped, fetcher=fetcher)
    fetch_stats["survived_filter"] = len(survivors)

    results = []
    total_processed = 0
    for article in survivors:
        results.append(process_article(article))
        total_processed += 1

        if progress_callback is not None:
            progress_callback(results)

        if get_run_stats()["estimated_cost_usd"] >= cost_limit:
            log_noise(
                headline="COST GUARD TRIGGERED",
                source_url="system",
                gate_failed="cost_guard",
                reason=f"Estimated cost ${get_run_stats()['estimated_cost_usd']:.4f} exceeded limit ${cost_limit}"
            )
            break

    fetch_stats["reached_llm"] = total_processed

    return {
        "fetched": len(combined),
        "survived_filter": len(survivors),
        "results": results,
        "run_stats": get_run_stats(),
        "archived": archived,
        "fetch_stats": fetch_stats,
    }
