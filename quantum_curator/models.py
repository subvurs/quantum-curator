"""Data models for Quantum Curator."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id() -> str:
    """Generate a new unique ID."""
    return str(uuid4())


class SourceType(str, Enum):
    """Type of content source."""

    RSS = "rss"
    ARXIV = "arxiv"
    NEWS_API = "news_api"
    TWITTER = "twitter"
    MANUAL = "manual"


class PostStatus(str, Enum):
    """Status of a curated post."""

    PENDING = "pending"  # Fetched, not yet curated
    DRAFT = "draft"  # Commentary added, not yet published
    CURATED = "curated"  # Commentary added, ready to publish
    PUBLISHED = "published"  # Published to site
    REJECTED = "rejected"  # Filtered out (low relevance, duplicate, etc.)


class ContentTopic(str, Enum):
    """Topic categories for quantum content."""

    HARDWARE = "hardware"
    ALGORITHMS = "algorithms"
    ERROR_CORRECTION = "error_correction"
    CRYPTOGRAPHY = "cryptography"
    MACHINE_LEARNING = "machine_learning"
    SIMULATION = "simulation"
    SENSING = "sensing"
    INDUSTRY = "industry"
    RESEARCH = "research"
    POLICY = "policy"
    GENERAL = "general"


class Source(BaseModel):
    """A content source (RSS feed, API, etc.)."""

    id: str = Field(default_factory=new_id)
    name: str
    source_type: SourceType
    url: str
    enabled: bool = True
    fetch_interval_hours: int = 6  # How often to fetch
    last_fetched: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # For RSS
    feed_url: str | None = None

    # For arXiv
    arxiv_categories: list[str] = Field(default_factory=list)  # e.g., ["quant-ph", "cs.QI"]

    # For NewsAPI
    news_query: str | None = None

    @property
    def last_fetched_at(self) -> datetime | None:
        """Alias for last_fetched."""
        return self.last_fetched

    @last_fetched_at.setter
    def last_fetched_at(self, value: datetime | None) -> None:
        self.last_fetched = value


class RawArticle(BaseModel):
    """A raw article fetched from a source before curation."""

    id: str = Field(default_factory=new_id)
    source_id: str
    source_name: str
    source_type: SourceType

    # Content
    title: str
    url: str
    summary: str = ""
    content: str = ""  # Full content if available
    author: str = ""
    image_url: str = ""

    # Metadata
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    # For arXiv
    arxiv_id: str = ""
    arxiv_categories: list[str] = Field(default_factory=list)
    arxiv_authors: list[str] = Field(default_factory=list)

    # Processing
    relevance_score: float = 0.0
    detected_topics: list[ContentTopic] = Field(default_factory=list)
    curated: bool = False  # Whether this article has been curated

    @property
    def topics(self) -> list[ContentTopic]:
        """Alias for detected_topics."""
        return self.detected_topics

    @topics.setter
    def topics(self, value: list[ContentTopic]) -> None:
        self.detected_topics = value


class CuratedPost(BaseModel):
    """A curated post ready for the site."""

    id: str = Field(default_factory=new_id)
    article_id: str  # Reference to RawArticle

    # Original content (can use title/summary or original_* prefixed versions)
    title: str = ""  # Display title
    original_url: str = ""
    summary: str = ""  # Display summary
    source_name: str = ""  # Display source name
    author: str = ""
    image_url: str = ""
    published_at: datetime | None = None

    # Curation
    curator_commentary: str = ""  # AI-generated or manual commentary
    curator_name: str = ""  # Who curated this
    curator_headline: str = ""  # Optional rewritten headline
    topics: list[ContentTopic] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0

    # Status
    status: PostStatus = PostStatus.PENDING
    curated_at: datetime | None = None
    published_to_site_at: datetime | None = None

    # SEO
    slug: str = ""
    meta_description: str = ""

    # Aliases for backward compatibility
    @property
    def original_title(self) -> str:
        return self.title

    @property
    def original_summary(self) -> str:
        return self.summary

    @property
    def original_source(self) -> str:
        return self.source_name

    @property
    def original_author(self) -> str:
        return self.author

    @property
    def original_image_url(self) -> str:
        return self.image_url

    def generate_slug(self) -> str:
        """Generate URL-friendly slug from title."""
        import re
        slug = self.title.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug)
        slug = slug.strip("-")
        # Add date prefix for uniqueness
        date_prefix = (self.published_at or datetime.utcnow()).strftime("%Y-%m-%d")
        return f"{date_prefix}-{slug[:80]}"


class DailyDigest(BaseModel):
    """A daily digest of curated posts."""

    id: str = Field(default_factory=new_id)
    date: datetime
    title: str = ""  # "Quantum News Digest - March 16, 2026"
    summary: str = ""  # AI-generated summary of the day's news
    post_ids: list[str] = Field(default_factory=list)  # IDs of included posts
    topics: list[ContentTopic] = Field(default_factory=list)
    curator_name: str = ""
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    published: bool = False

    # Aliases for backward compatibility
    @property
    def headline(self) -> str:
        return self.title

    @property
    def intro(self) -> str:
        return self.summary


class SiteConfig(BaseModel):
    """Configuration for the generated site."""

    site_name: str = ""
    site_description: str = ""
    base_url: str = ""
    curator_name: str = ""
    curator_bio: str = ""
    social_links: dict[str, str] = Field(default_factory=dict)  # platform -> url
    analytics_id: str = ""  # Google Analytics
    custom_css: str = ""

    # Aliases
    @property
    def title(self) -> str:
        return self.site_name

    @property
    def description(self) -> str:
        return self.site_description

    @property
    def url(self) -> str:
        return self.base_url
