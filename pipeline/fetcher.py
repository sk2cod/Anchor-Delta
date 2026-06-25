import re
from urllib.parse import urlparse

import feedparser
from tavily import TavilyClient

from config import TAVILY_API_KEY

RSS_FEEDS = [
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "domain": "geopolitics"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "domain": "geopolitics"},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml", "domain": "geopolitics"},
    {"url": "https://feeds.bbci.co.uk/news/rss.xml", "domain": "top_stories"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "domain": "top_stories"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "domain": "finance"},
    {"url": "https://www.ft.com/rss/home", "domain": "finance"},
    {"url": "https://www.technologyreview.com/feed/", "domain": "ai_tech"},
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "domain": "ai_tech"},
    {"url": "https://www.wired.com/feed/rss", "domain": "ai_tech"},
    {"url": "https://www.abc.net.au/news/feed/51120/rss.xml", "domain": "australia"},
    {"url": "https://www.theguardian.com/australia-news/rss", "domain": "australia"},
    {"url": "https://www.smh.com.au/rss/feed.xml", "domain": "australia"},
    {"url": "https://www.sbs.com.au/news/feed", "domain": "australia"},
    {"url": "https://www.afr.com/rss/feed.xml", "domain": "australia"},
    {"url": "https://www.thehindu.com/news/national/feeder/default.rss", "domain": "india"},
    {"url": "https://indianexpress.com/feed/", "domain": "india"},
    {"url": "https://www.livemint.com/rss/news", "domain": "india"},
]

SOCIAL_MEDIA_DOMAINS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "reddit.com",
    "linkedin.com",
)


def _is_social_media_url(url: str) -> bool:
    return any(domain in url for domain in SOCIAL_MEDIA_DOMAINS)


_YEAR_PATTERN = re.compile(r"(19|20)\d{2}")
_LONG_NUMERIC_ID_PATTERN = re.compile(r"\d{6,}")
_OPAQUE_ARTICLE_ID_PATTERN = re.compile(r"/articles/[a-zA-Z0-9]{8,}")

TRUSTED_ARTICLE_DOMAINS = (
    "bbc.com",
    "bbc.co.uk",
    "news.google.com",
    "reuters.com",
    "theguardian.com",
    "smh.com.au",
    "abc.net.au",
    "thehindu.com",
    "indianexpress.com",
    "livemint.com",
    "ft.com",
    "cnbc.com",
    "wired.com",
    "arstechnica.com",
    "technologyreview.com",
    "aljazeera.com",
    "sbs.com.au",
)


def _is_index_page(url: str) -> bool:
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()
    path = parsed_url.path

    if any(trusted in domain for trusted in TRUSTED_ARTICLE_DOMAINS):
        return False

    if "/rss/articles/" in path:
        return False

    if _OPAQUE_ARTICLE_ID_PATTERN.search(path):
        return False

    segments = [segment for segment in path.split("/") if segment]

    if len(segments) < 2:
        return True

    if _YEAR_PATTERN.search(path):
        return False
    if _LONG_NUMERIC_ID_PATTERN.search(path):
        return False
    if any(len(segment.split("-")) >= 4 for segment in segments):
        return False

    return True


class TavilyFetcher:
    def __init__(self):
        self.client = TavilyClient(api_key=TAVILY_API_KEY)

    def fetch_user_queries(self, extra_queries: list[str] = None):
        articles = []

        if extra_queries:
            for query in extra_queries:
                response = self.client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=5,
                    topic="news",
                    days=1,
                )
                for result in response.get("results", []):
                    articles.append(self._to_article_dict(result, "top_stories"))

        articles = [
            a for a in articles
            if not _is_social_media_url(a["url"])
            and not _is_index_page(a["url"])
            and len(a.get("content", "")) >= 300
        ]
        return self._dedupe_by_url(articles)

    def fetch_dynamic_queries(self, active_cards):
        articles = []
        for card in active_cards:
            query = f"{card['umbrella_title']} latest update"
            response = self.client.search(
                query=query,
                search_depth="advanced",
                max_results=10,
                topic="news",
                days=1,
            )
            for result in response.get("results", []):
                articles.append(self._to_article_dict(result, card.get("domain")))

        articles = [
            a for a in articles
            if not _is_social_media_url(a["url"])
            and not _is_index_page(a["url"])
            and len(a.get("content", "")) >= 300
        ]
        return self._dedupe_by_url(articles)

    def fetch_rss_articles(self) -> list[dict]:
        articles = []
        for feed_entry in RSS_FEEDS:
            parsed_feed = feedparser.parse(feed_entry["url"])
            source_domain = urlparse(feed_entry["url"]).netloc

            for entry in parsed_feed.entries[:15]:
                summary = entry.get("summary", "") or ""
                description = entry.get("description", "") or ""
                content = summary if len(summary) >= len(description) else description

                articles.append(
                    {
                        "url": entry.get("link", ""),
                        "title": entry.get("title", ""),
                        "content": content,
                        "published_date": entry.get("published"),
                        "source_domain": source_domain,
                        "query_domain": feed_entry["domain"],
                    }
                )

        articles = [
            a for a in articles
            if not _is_social_media_url(a["url"])
            and not _is_index_page(a["url"])
            and len(a.get("content", "")) >= 150
        ]
        return self._dedupe_by_url(articles)

    @staticmethod
    def _to_article_dict(result, query_domain):
        url = result.get("url", "")
        return {
            "url": url,
            "title": result.get("title", ""),
            "content": result.get("content", ""),
            "published_date": result.get("published_date"),
            "source_domain": urlparse(url).netloc,
            "query_domain": query_domain,
        }

    @staticmethod
    def _dedupe_by_url(articles):
        seen_urls = set()
        deduped = []
        for article in articles:
            if article["url"] in seen_urls:
                continue
            seen_urls.add(article["url"])
            deduped.append(article)
        return deduped
