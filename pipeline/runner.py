import logging

from db.cards import get_active_cards
from db.noise_log import log_noise
from pipeline.engine import get_run_stats, reset_run_stats
from pipeline.fetcher import TavilyFetcher
from pipeline.filter import run_filter_pipeline
from pipeline.orchestrator import process_article

logger = logging.getLogger(__name__)

COST_GUARD_USD = 1.00


def run_pipeline(extra_queries: list[str] = None, progress_callback=None, domain=None):
    reset_run_stats()

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

    seen_urls = set()
    deduped = []
    for article in combined:
        if article["url"] in seen_urls:
            continue
        seen_urls.add(article["url"])
        deduped.append(article)

    survivors = run_filter_pipeline(deduped, fetcher=fetcher)

    results = []
    for article in survivors:
        results.append(process_article(article))

        if progress_callback is not None:
            progress_callback(results)

        if get_run_stats()["estimated_cost_usd"] >= COST_GUARD_USD:
            log_noise(
                headline="COST GUARD TRIGGERED",
                source_url="system",
                gate_failed="cost_guard",
                reason=f"Estimated cost ${get_run_stats()['estimated_cost_usd']:.4f} exceeded limit ${COST_GUARD_USD}"
            )
            break

    return {
        "fetched": len(combined),
        "survived_filter": len(survivors),
        "results": results,
        "run_stats": get_run_stats(),
    }
