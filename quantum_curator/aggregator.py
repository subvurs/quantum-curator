"""Article aggregation and relevance scoring for Quantum Curator."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import QUANTUM_KEYWORDS, QUANTUM_TOPICS, get_settings
from .models import ContentTopic, RawArticle, Source, SourceType
from . import db
from .sources import get_source_fetcher


class Aggregator:
    """Aggregate articles from multiple sources with deduplication and scoring."""

    def __init__(self):
        self.settings = get_settings()

    async def fetch_all_sources(
        self,
        sources: list[Source] | None = None,
        force: bool = False,
    ) -> tuple[list[RawArticle], dict[str, int]]:
        """Fetch articles from all sources.

        Args:
            sources: List of sources to fetch (default: all enabled)
            force: Fetch even if within interval

        Returns:
            Tuple of (filtered articles, save outcome counts). The counts
            dict has keys 'inserted', 'updated', 'fk_blocked', 'other_error'
            so the CLI can report — and gate on — actual persistence rather
            than the in-memory length of `filtered`.
        """
        if sources is None:
            sources = db.list_sources(enabled=True)

        now = datetime.utcnow()
        articles: list[RawArticle] = []

        # Per-source outcome tracking. Previously _fetch_source swallowed
        # every exception with a bare print(), so the caller could not
        # distinguish "feed returned []" from "feed raised TimeoutError"
        # from "feed raised ParseError". That made it possible for 12 of
        # 19 sources to silently return zero articles for a week (May
        # 18-25 2026) while the fetch summary still reported a clean
        # number. _fetch_source now lets exceptions propagate to
        # asyncio.gather(return_exceptions=True), where we classify
        # them per-source and roll them into `counts` for the CLI to
        # warn on.
        source_ok = 0
        source_empty = 0
        source_error = 0
        source_skipped_interval = 0
        source_failures: list[dict[str, str]] = []
        empty_sources: list[str] = []

        # Build (source, coro) pairs so we can attribute each gather
        # result back to the source that produced it.
        pending: list[tuple[Source, Any]] = []
        for source in sources:
            # Check if fetch is due
            if not force and source.last_fetched_at:
                next_fetch = source.last_fetched_at + timedelta(
                    hours=source.fetch_interval_hours
                )
                if now < next_fetch:
                    source_skipped_interval += 1
                    continue

            pending.append((source, self._fetch_source(source)))

        if pending:
            results = await asyncio.gather(
                *(coro for _, coro in pending),
                return_exceptions=True,
            )
            for (source, _), result in zip(pending, results):
                if isinstance(result, BaseException):
                    source_error += 1
                    source_failures.append({
                        "source": source.name,
                        "error_type": type(result).__name__,
                        "error": str(result)[:200],
                    })
                    print(
                        f"Fetch error from {source.name}: "
                        f"{type(result).__name__}: {result}"
                    )
                elif isinstance(result, list):
                    if result:
                        source_ok += 1
                        articles.extend(result)
                    else:
                        source_empty += 1
                        empty_sources.append(source.name)
                else:
                    # Defensive: signature is list[RawArticle], but
                    # classify anything else as an error so we don't
                    # silently drop it like the old code path did.
                    source_error += 1
                    source_failures.append({
                        "source": source.name,
                        "error_type": "UnexpectedReturnType",
                        "error": f"got {type(result).__name__}",
                    })

        # Deduplicate
        unique_articles = self._deduplicate(articles)

        # Score relevance
        scored_articles = self._score_articles(unique_articles)

        # Extract OG images for articles missing image_url (skip arXiv)
        articles_needing_images = [
            a for a in scored_articles
            if not a.image_url and a.source_type != SourceType.ARXIV
        ]
        if articles_needing_images:
            from .image_extractor import extract_og_image

            image_tasks = [extract_og_image(a.url) for a in articles_needing_images]
            image_results = await asyncio.gather(*image_tasks, return_exceptions=True)
            for article, result in zip(articles_needing_images, image_results):
                if isinstance(result, str) and result:
                    article.image_url = result

        # Filter by minimum relevance
        min_score = self.settings.min_relevance_score
        filtered = [a for a in scored_articles if a.relevance_score >= min_score]

        # Filter out articles older than max_article_age_days
        max_age = timedelta(days=self.settings.max_article_age_days)
        cutoff = datetime.now(timezone.utc) - max_age
        before_count = len(filtered)
        filtered = [
            a for a in filtered
            if a.published_at is None
            or (a.published_at.replace(tzinfo=a.published_at.tzinfo or timezone.utc) >= cutoff)
        ]
        dropped = before_count - len(filtered)
        if dropped:
            print(f"Dropped {dropped} articles older than {self.settings.max_article_age_days} days")

        # Save to database, tracking per-outcome counts so the caller can
        # distinguish "8 articles in memory" from "8 articles persisted".
        # Source-fetch outcomes (ok / empty / error / skipped_interval)
        # are folded into the same dict so existing 2-tuple callers
        # (cli.fetch, fetch_and_score) don't need a signature change.
        counts: dict[str, Any] = {
            "inserted": 0,
            "updated": 0,
            "fk_blocked": 0,
            "other_error": 0,
            "sources_ok": source_ok,
            "sources_empty": source_empty,
            "sources_error": source_error,
            "sources_skipped_interval": source_skipped_interval,
            "source_failures": source_failures,
            "empty_sources": empty_sources,
        }
        for article in filtered:
            outcome, _ = db.save_raw_article(article)
            counts[outcome] += 1

        return filtered, counts

    async def _fetch_source(self, source: Source) -> list[RawArticle]:
        """Fetch articles from a single source.

        Exceptions are deliberately allowed to propagate. The caller
        (`fetch_all_sources`) wraps this in
        `asyncio.gather(return_exceptions=True)` and classifies each
        failure into `counts['source_failures']` so silent feed breakage
        becomes visible in the run log instead of looking like an empty
        feed. `last_fetched_at` is only updated on success — a source
        that consistently errors will keep being retried each run, which
        is the intended behavior.
        """
        fetcher = get_source_fetcher(source)
        articles = await fetcher.fetch(source)
        source.last_fetched_at = datetime.utcnow()
        db.save_source(source)
        return articles

    def _deduplicate(self, articles: list[RawArticle]) -> list[RawArticle]:
        """Remove duplicate articles based on URL and content similarity."""
        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        unique: list[RawArticle] = []

        # Also check against existing articles in DB
        existing = db.list_raw_articles(limit=1000)
        for existing_article in existing:
            seen_urls.add(self._normalize_url(existing_article.url))
            seen_hashes.add(self._content_hash(existing_article))

        for article in articles:
            # Normalize URL
            normalized_url = self._normalize_url(article.url)
            if normalized_url in seen_urls:
                continue

            # Check content similarity
            content_hash = self._content_hash(article)
            if content_hash in seen_hashes:
                continue

            seen_urls.add(normalized_url)
            seen_hashes.add(content_hash)
            unique.append(article)

        return unique

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for comparison."""
        # Remove protocol, www, trailing slash, query params
        url = url.lower()
        url = re.sub(r'^https?://', '', url)
        url = re.sub(r'^www\.', '', url)
        url = url.split('?')[0]
        url = url.rstrip('/')
        return url

    def _content_hash(self, article: RawArticle) -> str:
        """Create a hash of article content for similarity detection."""
        # Use title + first 200 chars of summary
        content = f"{article.title.lower()}{article.summary[:200].lower()}"
        # Remove common words and punctuation
        content = re.sub(r'[^\w\s]', '', content)
        content = ' '.join(content.split()[:20])  # First 20 words
        return hashlib.md5(content.encode()).hexdigest()

    def _score_articles(self, articles: list[RawArticle]) -> list[RawArticle]:
        """Score articles for quantum relevance."""
        for article in articles:
            score = self._calculate_relevance(article)
            article.relevance_score = score
            article.topics = self._detect_topics(article)
        return articles

    def _calculate_relevance(self, article: RawArticle) -> float:
        """Calculate relevance score (0-1) based on quantum keywords."""
        text = f"{article.title} {article.summary} {article.content}".lower()

        # Count keyword matches
        keyword_counts = Counter()
        for keyword in QUANTUM_KEYWORDS:
            pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
            matches = len(re.findall(pattern, text))
            if matches:
                keyword_counts[keyword] = matches

        if not keyword_counts:
            return 0.0

        # Base score from unique keywords found
        unique_keywords = len(keyword_counts)
        base_score = min(unique_keywords / 5, 1.0)  # 5+ keywords = max base

        # Boost for high-value terms
        high_value = [
            'quantum computing', 'quantum computer', 'qubit',
            'quantum advantage', 'quantum supremacy', 'quantum processor',
            'fault-tolerant', 'error correction', 'quantum algorithm'
        ]
        high_value_count = sum(1 for k in keyword_counts if k.lower() in high_value)
        boost = min(high_value_count * 0.15, 0.3)

        # Boost for arXiv (higher quality)
        if article.source_type == SourceType.ARXIV:
            boost += 0.1

        # Title relevance bonus
        title_keywords = sum(
            1 for k in QUANTUM_KEYWORDS
            if k.lower() in article.title.lower()
        )
        if title_keywords >= 2:
            boost += 0.1

        return min(base_score + boost, 1.0)

    def _detect_topics(self, article: RawArticle) -> list[ContentTopic]:
        """Detect which quantum topics the article covers."""
        text = f"{article.title} {article.summary}".lower()
        detected = []

        for topic, keywords in QUANTUM_TOPICS.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    try:
                        detected.append(ContentTopic(topic))
                    except ValueError:
                        pass
                    break

        return detected or [ContentTopic.GENERAL]

    async def get_top_articles(
        self,
        limit: int = 20,
        since: datetime | None = None,
        topics: list[ContentTopic] | None = None,
    ) -> list[RawArticle]:
        """Get top articles for curation.

        Args:
            limit: Maximum articles to return
            since: Only articles after this date
            topics: Filter by topics

        Returns:
            List of top-scored articles
        """
        if since is None:
            since = datetime.utcnow() - timedelta(days=1)

        # Get recent articles from DB
        articles = db.list_raw_articles(
            since=since,
            curated=False,
            limit=limit * 2,  # Fetch extra for filtering
        )

        # Filter by topics if specified
        if topics:
            articles = [
                a for a in articles
                if any(t in a.topics for t in topics)
            ]

        # Sort by relevance
        articles.sort(key=lambda a: a.relevance_score, reverse=True)

        return articles[:limit]


async def fetch_and_score(force: bool = False) -> tuple[list[RawArticle], dict[str, int]]:
    """Convenience function to fetch and score all sources."""
    aggregator = Aggregator()
    return await aggregator.fetch_all_sources(force=force)
