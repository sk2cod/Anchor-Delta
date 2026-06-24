from urllib.parse import urlparse

from tavily import TavilyClient

from config import TAVILY_API_KEY

FIXED_QUERIES = {
    "geopolitics": "major geopolitical developments today",
    "top_stories": "top world news stories today",
    "finance": "global financial markets and economic news today",
    "ai_tech": "artificial intelligence and technology news today",
    "australia": "Australia politics economy news today",
    "india": "India politics economy business news today",
}


class TavilyFetcher:
    def __init__(self):
        self.client = TavilyClient(api_key=TAVILY_API_KEY)

    def fetch_fixed_queries(self):
        articles = []
        for domain, query in FIXED_QUERIES.items():
            response = self.client.search(
                query=query,
                search_depth="advanced",
                max_results=10,
                topic="news",
            )
            for result in response.get("results", []):
                articles.append(self._to_article_dict(result, domain))
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
