"""Source registry with built-in quantum content sources."""

from __future__ import annotations

from typing import Any, Protocol

from ..models import RawArticle, Source, SourceType
from .. import db
from .rss import RSSFetcher
from .arxiv import ArxivFetcher
from .news import NewsAPIFetcher


class Fetcher(Protocol):
    """Protocol for source fetchers."""

    async def fetch(self, source: Source) -> list[RawArticle]:
        ...


# Built-in quantum content sources
BUILTIN_SOURCES: list[dict[str, Any]] = [
    # --- arXiv ---
    {
        "name": "arXiv Quantum Physics",
        "source_type": SourceType.ARXIV,
        "url": "https://arxiv.org",
        "arxiv_categories": ["quant-ph"],
        "fetch_interval_hours": 12,
    },
    {
        "name": "arXiv Quantum Information",
        "source_type": SourceType.ARXIV,
        "url": "https://arxiv.org",
        "arxiv_categories": ["cs.QI"],
        "fetch_interval_hours": 12,
    },

    # --- Major Quantum Companies ---
    {
        "name": "IBM Quantum Blog",
        "source_type": SourceType.RSS,
        "url": "https://www.ibm.com/quantum/blog",
        "feed_url": "https://www.ibm.com/quantum/blog/rss",
        "fetch_interval_hours": 6,
    },
    {
        "name": "Google AI Blog",
        "source_type": SourceType.RSS,
        "url": "https://ai.googleblog.com",
        "feed_url": "https://ai.googleblog.com/atom.xml",
        "fetch_interval_hours": 6,
    },
    {
        "name": "Microsoft Quantum Blog",
        "source_type": SourceType.RSS,
        "url": "https://cloudblogs.microsoft.com/quantum/",
        "feed_url": "https://cloudblogs.microsoft.com/quantum/feed/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "AWS Quantum Computing Blog",
        "source_type": SourceType.RSS,
        "url": "https://aws.amazon.com/blogs/quantum-computing/",
        "feed_url": "https://aws.amazon.com/blogs/quantum-computing/feed/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "IonQ Blog",
        "source_type": SourceType.RSS,
        "url": "https://ionq.com/news",
        "feed_url": "https://ionq.com/news/rss.xml",
        "fetch_interval_hours": 12,
    },

    # --- Quantum News Sites ---
    {
        "name": "Quantum Computing Report",
        "source_type": SourceType.RSS,
        "url": "https://quantumcomputingreport.com",
        "feed_url": "https://quantumcomputingreport.com/feed/",
        "fetch_interval_hours": 4,
    },
    {
        "name": "The Quantum Insider",
        "source_type": SourceType.RSS,
        "url": "https://thequantuminsider.com",
        "feed_url": "https://thequantuminsider.com/feed/",
        "fetch_interval_hours": 6,
    },

    # --- Science Publications ---
    {
        "name": "Quanta Magazine",
        "source_type": SourceType.RSS,
        "url": "https://www.quantamagazine.org",
        "feed_url": "https://www.quantamagazine.org/feed/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "Phys.org Quantum",
        "source_type": SourceType.RSS,
        "url": "https://phys.org/physics-news/quantum-physics/",
        "feed_url": "https://phys.org/rss-feed/physics-news/quantum-physics/",
        "fetch_interval_hours": 4,
    },
    {
        "name": "Nature Physics",
        "source_type": SourceType.RSS,
        "url": "https://www.nature.com/nphys/",
        "feed_url": "https://www.nature.com/nphys.rss",
        "fetch_interval_hours": 12,
    },
    {
        "name": "Science Daily - Quantum",
        "source_type": SourceType.RSS,
        "url": "https://www.sciencedaily.com/news/matter_energy/quantum_physics/",
        "feed_url": "https://www.sciencedaily.com/rss/matter_energy/quantum_physics.xml",
        "fetch_interval_hours": 6,
    },

    # --- Tech News ---
    {
        "name": "Ars Technica - Science",
        "source_type": SourceType.RSS,
        "url": "https://arstechnica.com/science/",
        "feed_url": "https://feeds.arstechnica.com/arstechnica/science",
        "fetch_interval_hours": 6,
    },
    {
        "name": "MIT Technology Review",
        "source_type": SourceType.RSS,
        "url": "https://www.technologyreview.com",
        "feed_url": "https://www.technologyreview.com/feed/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "Wired Science",
        "source_type": SourceType.RSS,
        "url": "https://www.wired.com/category/science/",
        "feed_url": "https://www.wired.com/feed/category/science/latest/rss",
        "fetch_interval_hours": 6,
    },

    # --- NewsAPI (if configured) ---
    {
        "name": "Quantum News (NewsAPI)",
        "source_type": SourceType.NEWS_API,
        "url": "https://newsapi.org",
        "news_query": '"quantum computing" OR "quantum computer" OR "qubit"',
        "fetch_interval_hours": 6,
    },
]


def register_builtin_sources() -> list[Source]:
    """Register all built-in sources in the database."""
    sources = []
    for source_data in BUILTIN_SOURCES:
        source = Source(**source_data)
        db.save_source(source)
        sources.append(source)
    return sources


def get_source_fetcher(source: Source) -> Fetcher:
    """Get the appropriate fetcher for a source type."""
    fetchers = {
        SourceType.RSS: RSSFetcher(),
        SourceType.ARXIV: ArxivFetcher(),
        SourceType.NEWS_API: NewsAPIFetcher(),
    }
    return fetchers.get(source.source_type, RSSFetcher())
