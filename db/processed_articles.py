from datetime import datetime, timedelta, timezone

from db.client import supabase_client


def is_url_seen(url_hash):
    response = (
        supabase_client.table("processed_articles")
        .select("id")
        .eq("url_hash", url_hash)
        .execute()
    )
    return len(response.data) > 0


def is_headline_seen(headline_hash):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    response = (
        supabase_client.table("processed_articles")
        .select("id")
        .eq("headline_hash", headline_hash)
        .gte("processed_at", cutoff)
        .execute()
    )
    return len(response.data) > 0


def mark_article_processed(url_hash, headline_hash, source_url):
    supabase_client.table("processed_articles").insert(
        {
            "url_hash": url_hash,
            "headline_hash": headline_hash,
            "source_url": source_url,
        }
    ).execute()
