"""RSS feed fetcher for Quantum Curator."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..config import get_settings
from ..models import RawArticle, Source, SourceType


class RSSFetcher:
    """Fetch articles from RSS feeds."""

    def __init__(self, timeout: int | None = None):
        settings = get_settings()
        self.timeout = timeout or settings.fetch_timeout

    async def fetch(self, source: Source) -> list[RawArticle]:
        """Fetch articles from an RSS feed source."""
        if not source.feed_url:
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(source.feed_url)
                response.raise_for_status()
                content = response.text
        except httpx.HTTPError as e:
            print(f"Error fetching RSS feed {source.feed_url}: {e}")
            return []

        feed = feedparser.parse(content)
        articles = []

        for entry in feed.entries:
            article = self._parse_entry(entry, source)
            if article:
                articles.append(article)

        return articles

    def _parse_entry(self, entry: Any, source: Source) -> RawArticle | None:
        """Parse a feed entry into a RawArticle."""
        try:
            # Get URL
            url = entry.get("link", "")
            if not url:
                return None

            # Get title
            title = entry.get("title", "")
            if not title:
                return None

            # Get summary/description
            summary = ""
            if "summary" in entry:
                summary = self._clean_html(entry.summary)
            elif "description" in entry:
                summary = self._clean_html(entry.description)

            # Get content if available
            content = ""
            if "content" in entry and entry.content:
                content = self._clean_html(entry.content[0].get("value", ""))

            # Get author
            author = entry.get("author", "")
            if not author and "authors" in entry and entry.authors:
                author = entry.authors[0].get("name", "")

            # Get published date
            published_at = None
            if "published_parsed" in entry and entry.published_parsed:
                try:
                    published_at = datetime(*entry.published_parsed[:6])
                except (ValueError, TypeError):
                    pass
            elif "updated_parsed" in entry and entry.updated_parsed:
                try:
                    published_at = datetime(*entry.updated_parsed[:6])
                except (ValueError, TypeError):
                    pass

            # Get image
            image_url = ""
            if "media_content" in entry and entry.media_content:
                image_url = entry.media_content[0].get("url", "")
            elif "media_thumbnail" in entry and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get("url", "")
            elif "enclosures" in entry and entry.enclosures:
                for enc in entry.enclosures:
                    if enc.get("type", "").startswith("image/"):
                        image_url = enc.get("href", "")
                        break

            return RawArticle(
                source_id=source.id,
                source_name=source.name,
                source_type=SourceType.RSS,
                title=title,
                url=url,
                summary=summary[:1000] if summary else "",
                content=content[:5000] if content else "",
                author=author,
                image_url=image_url,
                published_at=published_at,
                fetched_at=datetime.utcnow(),
            )

        except Exception as e:
            print(f"Error parsing RSS entry: {e}")
            return None

    def _clean_html(self, html: str) -> str:
        """Strip HTML tags and clean up text."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(separator=" ")
        # Normalize whitespace
        text = " ".join(text.split())
        return text.strip()
