"""arXiv API fetcher for Quantum Curator."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from ..config import get_settings
from ..models import RawArticle, Source, SourceType


ARXIV_API_URL = "https://export.arxiv.org/api/query"

# arXiv namespaces
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


class ArxivFetcher:
    """Fetch articles from arXiv API."""

    def __init__(self, timeout: int | None = None):
        settings = get_settings()
        self.timeout = timeout or settings.fetch_timeout

    async def fetch(
        self,
        source: Source,
        max_results: int = 50,
    ) -> list[RawArticle]:
        """Fetch articles from arXiv for specified categories.

        Args:
            source: Source with arxiv_categories defined
            max_results: Maximum number of results to fetch

        Returns:
            List of RawArticle objects
        """
        categories = source.arxiv_categories or ["quant-ph"]

        # Build query for multiple categories
        cat_queries = [f"cat:{cat}" for cat in categories]
        search_query = " OR ".join(cat_queries)

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(ARXIV_API_URL, params=params)
                response.raise_for_status()
                content = response.text
        except httpx.HTTPError as e:
            print(f"Error fetching arXiv: {e}")
            return []

        return self._parse_response(content, source)

    async def fetch_by_query(
        self,
        query: str,
        source: Source,
        max_results: int = 30,
    ) -> list[RawArticle]:
        """Fetch articles by search query.

        Args:
            query: Search query string
            source: Source for attribution
            max_results: Maximum number of results

        Returns:
            List of RawArticle objects
        """
        # Combine query with quantum categories
        categories = source.arxiv_categories or ["quant-ph", "cs.QI"]
        cat_query = " OR ".join(f"cat:{cat}" for cat in categories)
        full_query = f"({query}) AND ({cat_query})"

        params = {
            "search_query": full_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(ARXIV_API_URL, params=params)
                response.raise_for_status()
                content = response.text
        except httpx.HTTPError as e:
            print(f"Error fetching arXiv: {e}")
            return []

        return self._parse_response(content, source)

    def _parse_response(self, xml_content: str, source: Source) -> list[RawArticle]:
        """Parse arXiv API XML response."""
        articles = []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            print(f"Error parsing arXiv XML: {e}")
            return []

        for entry in root.findall(f"{ATOM_NS}entry"):
            article = self._parse_entry(entry, source)
            if article:
                articles.append(article)

        return articles

    def _parse_entry(self, entry: ET.Element, source: Source) -> RawArticle | None:
        """Parse a single arXiv entry."""
        try:
            # Get arXiv ID
            id_elem = entry.find(f"{ATOM_NS}id")
            if id_elem is None or not id_elem.text:
                return None
            arxiv_url = id_elem.text
            arxiv_id = self._extract_arxiv_id(arxiv_url)

            # Get title
            title_elem = entry.find(f"{ATOM_NS}title")
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
            # Clean up title (remove newlines)
            title = " ".join(title.split())
            if not title:
                return None

            # Get summary/abstract
            summary_elem = entry.find(f"{ATOM_NS}summary")
            summary = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else ""
            summary = " ".join(summary.split())

            # Get authors
            authors = []
            for author_elem in entry.findall(f"{ATOM_NS}author"):
                name_elem = author_elem.find(f"{ATOM_NS}name")
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text)

            # Get categories
            categories = []
            for cat_elem in entry.findall(f"{ATOM_NS}category"):
                term = cat_elem.get("term", "")
                if term:
                    categories.append(term)

            # Get published date
            published_elem = entry.find(f"{ATOM_NS}published")
            published_at = None
            if published_elem is not None and published_elem.text:
                try:
                    # arXiv uses ISO format
                    published_at = datetime.fromisoformat(
                        published_elem.text.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            # Construct abstract page URL
            url = f"https://arxiv.org/abs/{arxiv_id}"

            # Get PDF link
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

            return RawArticle(
                source_id=source.id,
                source_name=source.name,
                source_type=SourceType.ARXIV,
                title=title,
                url=url,
                summary=summary[:2000] if summary else "",
                content="",  # Full content would require PDF parsing
                author=", ".join(authors[:5]),  # First 5 authors
                image_url="",  # arXiv doesn't provide images
                published_at=published_at,
                fetched_at=datetime.utcnow(),
                arxiv_id=arxiv_id,
                arxiv_categories=categories,
                arxiv_authors=authors,
            )

        except Exception as e:
            print(f"Error parsing arXiv entry: {e}")
            return None

    def _extract_arxiv_id(self, url: str) -> str:
        """Extract arXiv ID from URL or ID string."""
        # Handle various formats:
        # http://arxiv.org/abs/2301.12345v1
        # https://arxiv.org/abs/quant-ph/0001234
        # 2301.12345
        match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7}(?:v\d+)?)", url)
        if match:
            return match.group(1)
        return url.split("/")[-1]
