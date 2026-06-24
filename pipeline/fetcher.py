from urllib.parse import urlparse

from tavily import TavilyClient

from config import TAVILY_API_KEY

FIXED_QUERIES = [
    {"query": "geopolitics conflict diplomacy news today", "domain": "geopolitics"},
    {"query": "global financial markets economy news today", "domain": "finance"},
    {"query": "artificial intelligence technology news today", "domain": "ai_tech"},
    {"query": "Australia news today", "domain": "australia"},
    {"query": "India news today", "domain": "india"},
    {"query": "top world news breaking stories today", "domain": "top_stories"},
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


class TavilyFetcher:
    def __init__(self):
        self.client = TavilyClient(api_key=TAVILY_API_KEY)

    def fetch_fixed_queries(self, extra_queries: list[str] = None):
        articles = []
        for entry in FIXED_QUERIES:
            response = self.client.search(
                query=entry["query"],
                search_depth="advanced",
                max_results=20,
                topic="news",
            )
            for result in response.get("results", []):
                articles.append(self._to_article_dict(result, entry["domain"]))

        if extra_queries:
            for query in extra_queries:
                response = self.client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=5,
                    topic="news",
                )
                for result in response.get("results", []):
                    articles.append(self._to_article_dict(result, "top_stories"))

        articles = [a for a in articles if not _is_social_media_url(a["url"])]
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
            )
            for result in response.get("results", []):
                articles.append(self._to_article_dict(result, card.get("domain")))

        articles = [a for a in articles if not _is_social_media_url(a["url"])]
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
