"""NewsAPI fetcher for Quantum Curator."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx

from ..config import get_settings
from ..models import RawArticle, Source, SourceType


NEWSAPI_URL = "https://newsapi.org/v2/everything"


class NewsAPIFetcher:
    """Fetch articles from NewsAPI."""

    def __init__(self, api_key: str | None = None, timeout: int | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.news_api_key
        self.timeout = timeout or settings.fetch_timeout

    async def fetch(
        self,
        source: Source,
        days_back: int = 3,
        max_results: int = 50,
    ) -> list[RawArticle]:
        """Fetch quantum computing news from NewsAPI.

        Args:
            source: Source with news_query defined (optional)
            days_back: How many days back to search
            max_results: Maximum number of results

        Returns:
            List of RawArticle objects
        """
        if not self.api_key:
            print("NewsAPI key not configured")
            return []

        # Build query
        query = source.news_query or self._default_query()

        # Date range
        from_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        params = {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "pageSize": min(max_results, 100),  # NewsAPI max is 100
            "language": "en",
            "apiKey": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(NEWSAPI_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as e:
            print(f"Error fetching NewsAPI: {e}")
            return []

        if data.get("status") != "ok":
            print(f"NewsAPI error: {data.get('message', 'Unknown error')}")
            return []

        articles = []
        for item in data.get("articles", []):
            article = self._parse_article(item, source)
            if article:
                articles.append(article)

        return articles

    async def fetch_by_query(
        self,
        query: str,
        source: Source,
        days_back: int = 7,
        max_results: int = 30,
    ) -> list[RawArticle]:
        """Fetch articles by custom query.

        Args:
            query: Search query
            source: Source for attribution
            days_back: How many days back to search
            max_results: Maximum number of results

        Returns:
            List of RawArticle objects
        """
        if not self.api_key:
            print("NewsAPI key not configured")
            return []

        from_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        params = {
            "q": query,
            "from": from_date,
            "sortBy": "relevancy",
            "pageSize": min(max_results, 100),
            "language": "en",
            "apiKey": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(NEWSAPI_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as e:
            print(f"Error fetching NewsAPI: {e}")
            return []

        if data.get("status") != "ok":
            return []

        articles = []
        for item in data.get("articles", []):
            article = self._parse_article(item, source)
            if article:
                articles.append(article)

        return articles

    def _default_query(self) -> str:
        """Build default quantum-focused query."""
        # NewsAPI supports AND, OR, NOT operators and phrase matching
        terms = [
            '"quantum computing"',
            '"quantum computer"',
            '"quantum processor"',
            '"qubit"',
            '"quantum advantage"',
            '"quantum supremacy"',
        ]
        return " OR ".join(terms)

    def _parse_article(self, item: dict[str, Any], source: Source) -> RawArticle | None:
        """Parse a NewsAPI article item."""
        try:
            url = item.get("url", "")
            title = item.get("title", "")

            if not url or not title:
                return None

            # Skip removed articles
            if "[Removed]" in title:
                return None

            # Get description/summary
            description = item.get("description", "") or ""

            # Get content (NewsAPI truncates to ~200 chars)
            content = item.get("content", "") or ""

            # Get author
            author = item.get("author", "") or ""

            # Get source name
            source_info = item.get("source", {})
            source_name = source_info.get("name", source.name)

            # Get image
            image_url = item.get("urlToImage", "") or ""

            # Get published date
            published_at = None
            published_str = item.get("publishedAt", "")
            if published_str:
                try:
                    published_at = datetime.fromisoformat(
                        published_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            return RawArticle(
                source_id=source.id,
                source_name=source_name,
                source_type=SourceType.NEWS_API,
                title=title,
                url=url,
                summary=description[:1000] if description else "",
                content=content[:2000] if content else "",
                author=author,
                image_url=image_url,
                published_at=published_at,
                fetched_at=datetime.utcnow(),
            )

        except Exception as e:
            print(f"Error parsing NewsAPI article: {e}")
            return None
