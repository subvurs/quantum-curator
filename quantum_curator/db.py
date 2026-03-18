"""SQLite database for Quantum Curator."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import get_settings
from .models import (
    ContentTopic,
    CuratedPost,
    DailyDigest,
    PostStatus,
    RawArticle,
    Source,
    SourceType,
)


def get_connection() -> sqlite3.Connection:
    """Get a database connection."""
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Initialize database tables."""
    conn = get_connection()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            url TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            fetch_interval_hours INTEGER DEFAULT 6,
            last_fetched TEXT,
            metadata TEXT DEFAULT '{}',
            feed_url TEXT,
            arxiv_categories TEXT DEFAULT '[]',
            news_query TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS raw_articles (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            summary TEXT DEFAULT '',
            content TEXT DEFAULT '',
            author TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            arxiv_id TEXT DEFAULT '',
            arxiv_categories TEXT DEFAULT '[]',
            arxiv_authors TEXT DEFAULT '[]',
            relevance_score REAL DEFAULT 0.0,
            detected_topics TEXT DEFAULT '[]',
            curated INTEGER DEFAULT 0,
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );

        CREATE TABLE IF NOT EXISTS curated_posts (
            id TEXT PRIMARY KEY,
            article_id TEXT NOT NULL,
            title TEXT NOT NULL,
            original_url TEXT NOT NULL,
            summary TEXT DEFAULT '',
            author TEXT DEFAULT '',
            source_name TEXT NOT NULL,
            image_url TEXT DEFAULT '',
            published_at TEXT,
            curator_commentary TEXT DEFAULT '',
            curator_name TEXT DEFAULT '',
            curator_headline TEXT DEFAULT '',
            topics TEXT DEFAULT '[]',
            tags TEXT DEFAULT '[]',
            relevance_score REAL DEFAULT 0.0,
            status TEXT DEFAULT 'pending',
            curated_at TEXT,
            published_to_site_at TEXT,
            slug TEXT DEFAULT '',
            meta_description TEXT DEFAULT '',
            FOREIGN KEY (article_id) REFERENCES raw_articles(id)
        );

        CREATE TABLE IF NOT EXISTS daily_digests (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL UNIQUE,
            title TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            post_ids TEXT DEFAULT '[]',
            topics TEXT DEFAULT '[]',
            curator_name TEXT DEFAULT '',
            generated_at TEXT NOT NULL,
            published INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_articles_url ON raw_articles(url);
        CREATE INDEX IF NOT EXISTS idx_articles_fetched ON raw_articles(fetched_at);
        CREATE INDEX IF NOT EXISTS idx_posts_status ON curated_posts(status);
        CREATE INDEX IF NOT EXISTS idx_posts_published ON curated_posts(published_to_site_at);
        CREATE INDEX IF NOT EXISTS idx_digests_date ON daily_digests(date);
    """)

    conn.commit()
    conn.close()


# --- Source CRUD ---

def save_source(source: Source) -> Source:
    """Save a source to the database."""
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO sources
        (id, name, source_type, url, enabled, fetch_interval_hours, last_fetched,
         metadata, feed_url, arxiv_categories, news_query)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        source.id,
        source.name,
        source.source_type.value,
        source.url,
        1 if source.enabled else 0,
        source.fetch_interval_hours,
        source.last_fetched.isoformat() if source.last_fetched else None,
        json.dumps(source.metadata),
        source.feed_url,
        json.dumps(source.arxiv_categories),
        source.news_query,
    ))
    conn.commit()
    conn.close()
    return source


def get_source(source_id: str) -> Source | None:
    """Get a source by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_source(row)


def list_sources(enabled: bool | None = None, enabled_only: bool = False) -> list[Source]:
    """List all sources.

    Args:
        enabled: Filter by enabled status (True/False) or None for all
        enabled_only: Deprecated, use enabled=True instead
    """
    conn = get_connection()
    query = "SELECT * FROM sources"

    # Handle both parameter styles
    if enabled is True or enabled_only:
        query += " WHERE enabled = 1"
    elif enabled is False:
        query += " WHERE enabled = 0"

    rows = conn.execute(query).fetchall()
    conn.close()
    return [_row_to_source(r) for r in rows]


def update_source_last_fetched(source_id: str) -> None:
    """Update the last_fetched timestamp for a source."""
    conn = get_connection()
    conn.execute(
        "UPDATE sources SET last_fetched = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), source_id),
    )
    conn.commit()
    conn.close()


def _row_to_source(row: sqlite3.Row) -> Source:
    """Convert a database row to a Source model."""
    return Source(
        id=row["id"],
        name=row["name"],
        source_type=SourceType(row["source_type"]),
        url=row["url"],
        enabled=bool(row["enabled"]),
        fetch_interval_hours=row["fetch_interval_hours"],
        last_fetched=datetime.fromisoformat(row["last_fetched"]) if row["last_fetched"] else None,
        metadata=json.loads(row["metadata"]),
        feed_url=row["feed_url"],
        arxiv_categories=json.loads(row["arxiv_categories"]),
        news_query=row["news_query"],
    )


# --- RawArticle CRUD ---

def save_article(article: RawArticle) -> RawArticle:
    """Save a raw article to the database."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO raw_articles
            (id, source_id, source_name, source_type, title, url, summary, content,
             author, image_url, published_at, fetched_at, arxiv_id, arxiv_categories,
             arxiv_authors, relevance_score, detected_topics, curated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            article.id,
            article.source_id,
            article.source_name,
            article.source_type.value,
            article.title,
            article.url,
            article.summary,
            article.content,
            article.author,
            article.image_url,
            article.published_at.isoformat() if article.published_at else None,
            article.fetched_at.isoformat(),
            article.arxiv_id,
            json.dumps(article.arxiv_categories),
            json.dumps(article.arxiv_authors),
            article.relevance_score,
            json.dumps([t.value for t in article.detected_topics]),
            1 if article.curated else 0,
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Duplicate URL, ignore
    conn.close()
    return article


def get_article(article_id: str) -> RawArticle | None:
    """Get an article by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM raw_articles WHERE id = ?", (article_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_article(row)


def get_article_by_url(url: str) -> RawArticle | None:
    """Get an article by URL."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM raw_articles WHERE url = ?", (url,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_article(row)


def list_articles(
    since: datetime | None = None,
    min_relevance: float = 0.0,
    curated: bool | None = None,
    limit: int = 100,
) -> list[RawArticle]:
    """List articles with optional filtering."""
    conn = get_connection()
    query = "SELECT * FROM raw_articles WHERE relevance_score >= ?"
    params: list[Any] = [min_relevance]

    if since:
        query += " AND fetched_at >= ?"
        params.append(since.isoformat())

    if curated is not None:
        query += " AND curated = ?"
        params.append(1 if curated else 0)

    query += " ORDER BY fetched_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_row_to_article(r) for r in rows]


# Aliases for consistency
def list_raw_articles(
    since: datetime | None = None,
    min_relevance: float = 0.0,
    curated: bool | None = None,
    limit: int = 100,
) -> list[RawArticle]:
    """Alias for list_articles."""
    return list_articles(since=since, min_relevance=min_relevance, curated=curated, limit=limit)


def save_raw_article(article: RawArticle) -> RawArticle:
    """Alias for save_article."""
    return save_article(article)


def _row_to_article(row: sqlite3.Row) -> RawArticle:
    """Convert a database row to a RawArticle model."""
    return RawArticle(
        id=row["id"],
        source_id=row["source_id"],
        source_name=row["source_name"],
        source_type=SourceType(row["source_type"]),
        title=row["title"],
        url=row["url"],
        summary=row["summary"],
        content=row["content"],
        author=row["author"],
        image_url=row["image_url"],
        published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        arxiv_id=row["arxiv_id"],
        arxiv_categories=json.loads(row["arxiv_categories"]),
        arxiv_authors=json.loads(row["arxiv_authors"]),
        relevance_score=row["relevance_score"],
        detected_topics=[ContentTopic(t) for t in json.loads(row["detected_topics"])],
        curated=bool(row["curated"]) if "curated" in row.keys() else False,
    )


# --- CuratedPost CRUD ---

def save_post(post: CuratedPost) -> CuratedPost:
    """Save a curated post to the database."""
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO curated_posts
        (id, article_id, title, original_url, summary, author,
         source_name, image_url, published_at, curator_commentary, curator_name, curator_headline,
         topics, tags, relevance_score, status, curated_at, published_to_site_at, slug, meta_description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        post.id,
        post.article_id,
        post.title,
        post.original_url,
        post.summary,
        post.author,
        post.source_name,
        post.image_url,
        post.published_at.isoformat() if post.published_at else None,
        post.curator_commentary,
        post.curator_name,
        post.curator_headline,
        json.dumps([t.value for t in post.topics]),
        json.dumps(post.tags),
        post.relevance_score,
        post.status.value,
        post.curated_at.isoformat() if post.curated_at else None,
        post.published_to_site_at.isoformat() if post.published_to_site_at else None,
        post.slug,
        post.meta_description,
    ))
    conn.commit()
    conn.close()
    return post


def save_curated_post(post: CuratedPost) -> CuratedPost:
    """Alias for save_post."""
    return save_post(post)


def get_post(post_id: str) -> CuratedPost | None:
    """Get a post by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM curated_posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_post(row)


def list_posts(
    status: PostStatus | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[CuratedPost]:
    """List posts with optional filtering."""
    conn = get_connection()
    query = "SELECT * FROM curated_posts WHERE 1=1"
    params: list[Any] = []

    if status:
        query += " AND status = ?"
        params.append(status.value)

    if since:
        query += " AND COALESCE(published_at, curated_at) >= ?"
        params.append(since.isoformat())

    query += " ORDER BY COALESCE(published_at, curated_at) DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_row_to_post(r) for r in rows]


def get_posts_for_date(date: datetime) -> list[CuratedPost]:
    """Get all published posts for a specific date."""
    conn = get_connection()
    date_str = date.strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT * FROM curated_posts
        WHERE status = 'published'
        AND date(published_to_site_at) = ?
        ORDER BY relevance_score DESC
    """, (date_str,)).fetchall()
    conn.close()
    return [_row_to_post(r) for r in rows]


def update_post_status(post_id: str, status: PostStatus) -> bool:
    """Update the status of a post."""
    conn = get_connection()
    now = datetime.utcnow().isoformat()

    if status == PostStatus.CURATED:
        conn.execute(
            "UPDATE curated_posts SET status = ?, curated_at = ? WHERE id = ?",
            (status.value, now, post_id),
        )
    elif status == PostStatus.PUBLISHED:
        conn.execute(
            "UPDATE curated_posts SET status = ?, published_to_site_at = ? WHERE id = ?",
            (status.value, now, post_id),
        )
    else:
        conn.execute(
            "UPDATE curated_posts SET status = ? WHERE id = ?",
            (status.value, post_id),
        )

    affected = conn.total_changes
    conn.commit()
    conn.close()
    return affected > 0


def _row_to_post(row: sqlite3.Row) -> CuratedPost:
    """Convert a database row to a CuratedPost model."""
    return CuratedPost(
        id=row["id"],
        article_id=row["article_id"],
        title=row["title"],
        original_url=row["original_url"],
        summary=row["summary"],
        author=row["author"],
        source_name=row["source_name"],
        image_url=row["image_url"],
        published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
        curator_commentary=row["curator_commentary"],
        curator_name=row["curator_name"] if "curator_name" in row.keys() else "",
        curator_headline=row["curator_headline"],
        topics=[ContentTopic(t) for t in json.loads(row["topics"])],
        tags=json.loads(row["tags"]),
        relevance_score=row["relevance_score"],
        status=PostStatus(row["status"]),
        curated_at=datetime.fromisoformat(row["curated_at"]) if row["curated_at"] else None,
        published_to_site_at=datetime.fromisoformat(row["published_to_site_at"]) if row["published_to_site_at"] else None,
        slug=row["slug"],
        meta_description=row["meta_description"],
    )


def list_curated_posts(
    status: PostStatus | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[CuratedPost]:
    """Alias for list_posts."""
    return list_posts(status=status, since=since, limit=limit)


# --- DailyDigest CRUD ---

def save_digest(digest: DailyDigest) -> DailyDigest:
    """Save a daily digest."""
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO daily_digests
        (id, date, title, summary, post_ids, topics, curator_name, generated_at, published)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        digest.id,
        digest.date.strftime("%Y-%m-%d"),
        digest.title,
        digest.summary,
        json.dumps(digest.post_ids),
        json.dumps([t.value for t in digest.topics]),
        digest.curator_name,
        digest.generated_at.isoformat(),
        1 if digest.published else 0,
    ))
    conn.commit()
    conn.close()
    return digest


def save_daily_digest(digest: DailyDigest) -> DailyDigest:
    """Alias for save_digest."""
    return save_digest(digest)


def get_digest(date: datetime) -> DailyDigest | None:
    """Get the digest for a specific date."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM daily_digests WHERE date = ?",
        (date.strftime("%Y-%m-%d"),),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return DailyDigest(
        id=row["id"],
        date=datetime.strptime(row["date"], "%Y-%m-%d"),
        title=row["title"] if "title" in row.keys() else "",
        summary=row["summary"] if "summary" in row.keys() else "",
        post_ids=json.loads(row["post_ids"]),
        topics=[ContentTopic(t) for t in json.loads(row["topics"])] if "topics" in row.keys() else [],
        curator_name=row["curator_name"] if "curator_name" in row.keys() else "",
        generated_at=datetime.fromisoformat(row["generated_at"]),
        published=bool(row["published"]),
    )


def list_digests(limit: int = 30) -> list[DailyDigest]:
    """List recent digests."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT date FROM daily_digests ORDER BY date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    digests = []
    for row in rows:
        digest = get_digest(datetime.strptime(row["date"], "%Y-%m-%d"))
        if digest:
            digests.append(digest)

    return digests


def list_daily_digests(limit: int = 30) -> list[DailyDigest]:
    """Alias for list_digests."""
    return list_digests(limit=limit)
