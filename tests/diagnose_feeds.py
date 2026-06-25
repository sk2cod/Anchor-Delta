import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pipeline.fetcher import TavilyFetcher
from pipeline.filter import SYDNEY_TZ, _parse_published_date


def _group_by_domain(articles):
    by_domain = defaultdict(list)
    for article in articles:
        by_domain[article["query_domain"]].append(article)
    return by_domain


def _domain_summary(domain_articles, now_sydney):
    lengths = [len(a.get("content", "") or "") for a in domain_articles]
    total = len(domain_articles)
    avg_length = sum(lengths) / total if total else 0
    over_500 = sum(1 for length in lengths if length > 500)
    under_150 = sum(1 for length in lengths if length < 150)

    older_than_48h = 0
    for article in domain_articles:
        parsed = _parse_published_date(article.get("published_date"))
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if now_sydney - parsed.astimezone(SYDNEY_TZ) > timedelta(hours=48):
            older_than_48h += 1

    return {
        "total": total,
        "avg_length": avg_length,
        "over_500": over_500,
        "under_150": under_150,
        "older_than_48h": older_than_48h,
    }


def main():
    fetcher = TavilyFetcher()
    articles = fetcher.fetch_rss_articles()
    now_sydney = datetime.now(SYDNEY_TZ)

    print(f"Total RSS articles fetched: {len(articles)}")
    print("=" * 100)

    for article in articles:
        content_length = len(article.get("content", "") or "")
        print(f"[{article['query_domain']}] {article['title'][:80]}")
        print(f"  content_length: {content_length}")
        print(f"  published_date: {article.get('published_date')}")
        print(f"  source_domain:  {article.get('source_domain')}")
        print()

    by_domain_before = _group_by_domain(articles)
    summary_before = {
        domain: _domain_summary(domain_articles, now_sydney)
        for domain, domain_articles in by_domain_before.items()
    }

    print("=" * 100)
    print("SUMMARY BY DOMAIN — BEFORE ENRICHMENT")
    print("=" * 100)
    for domain in sorted(summary_before):
        s = summary_before[domain]
        print(f"\n{domain}:")
        print(f"  total articles:        {s['total']}")
        print(f"  avg content length:    {s['avg_length']:.0f}")
        print(f"  content > 500 chars:   {s['over_500']}")
        print(f"  content < 150 chars:   {s['under_150']} (would be filtered)")
        print(f"  older than 48 hours:   {s['older_than_48h']}")

    print()
    print("Fetching full article bodies (enrichment)...")
    enriched_articles = fetcher.enrich_articles_with_body(articles)

    by_domain_after = _group_by_domain(enriched_articles)
    summary_after = {
        domain: _domain_summary(domain_articles, now_sydney)
        for domain, domain_articles in by_domain_after.items()
    }

    print("=" * 100)
    print("SUMMARY BY DOMAIN — AFTER ENRICHMENT")
    print("=" * 100)
    for domain in sorted(summary_after):
        s = summary_after[domain]
        print(f"\n{domain}:")
        print(f"  total articles:        {s['total']}")
        print(f"  avg content length:    {s['avg_length']:.0f}")
        print(f"  content > 500 chars:   {s['over_500']}")
        print(f"  content < 150 chars:   {s['under_150']} (would be filtered)")
        print(f"  older than 48 hours:   {s['older_than_48h']}")

    print()
    print("=" * 100)
    print("BEFORE vs AFTER COMPARISON")
    print("=" * 100)
    print(f"{'domain':<14}{'avg before':>12}{'avg after':>12}{'delta':>10}{'>500 before':>14}{'>500 after':>13}")
    for domain in sorted(summary_before):
        before = summary_before[domain]
        after = summary_after.get(domain, before)
        delta = after["avg_length"] - before["avg_length"]
        print(
            f"{domain:<14}{before['avg_length']:>12.0f}{after['avg_length']:>12.0f}"
            f"{delta:>+10.0f}{before['over_500']:>14}{after['over_500']:>13}"
        )


if __name__ == "__main__":
    main()
