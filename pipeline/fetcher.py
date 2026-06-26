import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup
from tavily import TavilyClient

from config import TAVILY_API_KEY

RSS_FEEDS = [
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "domain": "world"},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml", "domain": "world"},
    {"url": "https://www.theguardian.com/world/rss", "domain": "world"},
    {"url": "https://rss.dw.com/rss/en-all", "domain": "world"},
    {"url": "https://www.france24.com/en/rss", "domain": "world"},
    {"url": "https://feeds.bbci.co.uk/news/rss.xml", "domain": "world"},
    {"url": "https://www.theguardian.com/international/rss", "domain": "world"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "domain": "finance"},
    {"url": "https://www.ft.com/rss/home", "domain": "finance"},
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml", "domain": "finance"},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories", "domain": "finance"},
    {"url": "https://finance.yahoo.com/news/rssindex", "domain": "finance"},
    {"url": "https://www.investing.com/rss/news.rss", "domain": "finance"},
    {"url": "https://www.technologyreview.com/feed/", "domain": "ai_tech"},
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "domain": "ai_tech"},
    {"url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "domain": "ai_tech"},
    {"url": "https://www.abc.net.au/news/feed/51120/rss.xml", "domain": "australia"},
    {"url": "https://www.theguardian.com/australia-news/rss", "domain": "australia"},
    {"url": "https://www.smh.com.au/rss/feed.xml", "domain": "australia"},
    {"url": "https://www.sbs.com.au/news/feed", "domain": "australia"},
    {"url": "https://www.afr.com/rss/feed.xml", "domain": "australia"},
    {"url": "https://www.thehindu.com/business/feeder/default.rss", "domain": "india"},
    {"url": "https://www.thehindu.com/news/national/feeder/default.rss", "domain": "india"},
    {"url": "https://indianexpress.com/section/business/feed/", "domain": "india"},
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


def fetch_article_body(url: str, existing_content: str = "", timeout: int = 5) -> str:
    """
    Fetch full article body from URL.
    Returns full text if longer than existing_content, otherwise returns existing_content.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        if response.status_code != 200:
            return existing_content

        soup = BeautifulSoup(response.text, "lxml")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "figure", "iframe", "noscript"]):
            tag.decompose()

        # Try article-specific selectors first
        article_selectors = [
            "article", "[role='main']", ".article-body", ".story-body",
            ".post-content", ".entry-content", ".article-content", "main"
        ]
        body_text = ""
        for selector in article_selectors:
            element = soup.select_one(selector)
            if element:
                paragraphs = element.find_all("p")
                body_text = " ".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)
                if len(body_text) > 200:
                    break

        # Fallback to all paragraphs
        if len(body_text) < 200:
            paragraphs = soup.find_all("p")
            body_text = " ".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)

        # Only upgrade if fetched content is meaningfully longer
        if len(body_text) > len(existing_content) + 100:
            return body_text[:3000]  # Cap at 3000 chars
        return existing_content

    except Exception:
        return existing_content


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
                    articles.append(self._to_article_dict(result, "world"))

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

    def enrich_articles_with_body(self, articles: list[dict], max_workers: int = 10) -> list[dict]:
        """
        Concurrently fetch full article bodies for a list of articles.
        Updates the 'content' field if fetched body is longer than RSS teaser.
        """
        def enrich_one(article):
            enriched = article.copy()
            enriched["content"] = fetch_article_body(
                article["url"],
                existing_content=article.get("content", "")
            )
            return enriched

        enriched = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(enrich_one, article): article for article in articles}
            for future in as_completed(futures):
                try:
                    enriched.append(future.result())
                except Exception:
                    enriched.append(futures[future])  # Keep original on error

        return enriched
