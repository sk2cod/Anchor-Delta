from db.cards import get_active_cards
from pipeline.fetcher import TavilyFetcher
from pipeline.filter import run_filter_pipeline


def run_pipeline():
    fetcher = TavilyFetcher()

    fixed_articles = fetcher.fetch_fixed_queries()
    active_cards = get_active_cards()
    dynamic_articles = fetcher.fetch_dynamic_queries(active_cards)

    combined = fixed_articles + dynamic_articles
    seen_urls = set()
    deduped = []
    for article in combined:
        if article["url"] in seen_urls:
            continue
        seen_urls.add(article["url"])
        deduped.append(article)

    return run_filter_pipeline(deduped)
