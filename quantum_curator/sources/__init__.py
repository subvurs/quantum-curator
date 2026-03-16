"""Content sources for Quantum Curator."""

from .registry import BUILTIN_SOURCES, get_source_fetcher, register_builtin_sources
from .rss import RSSFetcher
from .arxiv import ArxivFetcher
from .news import NewsAPIFetcher

__all__ = [
    "BUILTIN_SOURCES",
    "get_source_fetcher",
    "register_builtin_sources",
    "RSSFetcher",
    "ArxivFetcher",
    "NewsAPIFetcher",
]
