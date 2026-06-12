"""SQLite database for Quantum Curator."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

SaveOutcome = Literal["inserted", "updated", "fk_blocked", "other_error"]

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
            subvurs_notes TEXT DEFAULT '',
            subvurs_impact_score REAL DEFAULT 0.0,
            subvurs_impact_report TEXT DEFAULT NULL,
            subvurs_impact_version TEXT DEFAULT NULL,
            -- Phase 5c (Intel→Curator migration, Plan B): anti-recurrence
            -- parity with quantum_intel_entries.first_brief_at. Stamped
            -- by intel.synthesizer.deliver() the first time a seed-side
            -- curated_post is cited in a brief. UPDATE ... WHERE
            -- intel_first_brief_at IS NULL gives idempotent "first cite
            -- wins" semantics. NULL = never cited.
            intel_first_brief_at TEXT DEFAULT NULL,
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

        CREATE TABLE IF NOT EXISTS bluesky_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT NOT NULL UNIQUE,
            bsky_uri TEXT NOT NULL,
            bsky_cid TEXT NOT NULL,
            shared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_bsky_post_id ON bluesky_shares(post_id);

        CREATE TABLE IF NOT EXISTS twitter_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT NOT NULL UNIQUE,
            tweet_id TEXT NOT NULL,
            shared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_twitter_post_id ON twitter_shares(post_id);

        -- Quantum Intel inventory (migrated from ~/Library/Application
        -- Support/quantum_intel/inventory.json in June 2026 as part of the
        -- Intel → Curator backend consolidation). entry_id is the same
        -- integer Intel's synthesizer.py emits in its SYNTH_PROMPT entry tags,
        -- so existing briefs that cite "entry_id=N" remain resolvable after
        -- migration. fingerprint is SHA-256(title|source)[:16] (cataloger.py
        -- _fingerprint), used as the dedup key.
        CREATE TABLE IF NOT EXISTS quantum_intel_entries (
            entry_id INTEGER PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            url TEXT DEFAULT '',
            date_collected TEXT NOT NULL,
            date_published TEXT DEFAULT '',
            entry_type TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            technical_detail TEXT DEFAULT '',
            enabling_capabilities TEXT DEFAULT '[]',
            domain_tags TEXT DEFAULT '[]',
            maturity TEXT DEFAULT '',
            -- subvurs_impact_* columns mirror curated_posts naming for
            -- cross-table consistency. subvurs_impact_report carries a
            -- JSON object {paths, evidence, fail_reason}; the 9
            -- already-scored entries in the Jun 2026 import have those
            -- three fields nested under this column.
            subvurs_impact_score REAL DEFAULT 0.0,
            subvurs_impact_report TEXT DEFAULT NULL,
            subvurs_impact_version TEXT DEFAULT NULL,
            first_brief_at TEXT DEFAULT NULL,
            imported_from TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_intel_fingerprint
            ON quantum_intel_entries(fingerprint);
        CREATE INDEX IF NOT EXISTS idx_intel_date_collected
            ON quantum_intel_entries(date_collected);
        CREATE INDEX IF NOT EXISTS idx_intel_subvurs_impact_score
            ON quantum_intel_entries(subvurs_impact_score);

        -- Dedup-only fingerprints: title|source SHA-256[:16] values that
        -- were seen by Intel but never made it into inventory (e.g.
        -- LLM extraction failed, content was off-topic, or the catalog
        -- pre-filter rejected them). Intel's dedup_index.json stores
        -- these alongside the inventory fingerprints; preserving them
        -- here keeps the dedup contract intact so the Curator-side
        -- synth pipeline doesn't re-pay LLM cost on already-rejected
        -- items. No PK FK — these are pure sentinels.
        CREATE TABLE IF NOT EXISTS quantum_intel_dedup (
            fingerprint TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL,
            imported_from TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Daily Bluesky digest tracking. Mirrors the bluesky_shares
        -- per-post pattern but keyed by date for idempotent
        -- "one summary per day" semantics. summary_date is YYYY-MM-DD
        -- in the local publication timezone.
        CREATE TABLE IF NOT EXISTS bluesky_daily_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary_date TEXT NOT NULL UNIQUE,
            bsky_uri TEXT NOT NULL,
            bsky_cid TEXT NOT NULL,
            post_text TEXT NOT NULL,
            shared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_bsky_daily_date
            ON bluesky_daily_summaries(summary_date);

        -- Per-post rows for threaded daily summaries. Created only
        -- when share_daily_summary takes the threaded path. The
        -- summary_date FK is the natural join key into
        -- bluesky_daily_summaries (which has UNIQUE on summary_date).
        CREATE TABLE IF NOT EXISTS bluesky_thread_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary_date TEXT NOT NULL,
            position INTEGER NOT NULL,
            bsky_uri TEXT NOT NULL,
            post_text TEXT NOT NULL,
            posted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(summary_date, position)
        );

        CREATE INDEX IF NOT EXISTS idx_bsky_thread_date
            ON bluesky_thread_posts(summary_date);
    """)

    # Migrate: add threading-tracking columns to bluesky_daily_summaries.
    # root_uri / root_cid duplicate the legacy bsky_uri / bsky_cid for
    # single-post rows so the threaded code path doesn't have to special-
    # case the schema. is_thread flags rows produced by the threaded
    # path so downstream consumers can fan out into bluesky_thread_posts.
    for ddl in (
        "ALTER TABLE bluesky_daily_summaries ADD COLUMN root_uri TEXT DEFAULT NULL",
        "ALTER TABLE bluesky_daily_summaries ADD COLUMN root_cid TEXT DEFAULT NULL",
        "ALTER TABLE bluesky_daily_summaries ADD COLUMN is_thread INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(ddl)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Migrate existing databases: add subvurs_notes column if missing
    try:
        conn.execute("ALTER TABLE curated_posts ADD COLUMN subvurs_notes TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migrate: add subvurs_impact_* columns (Phase B — proposal §8)
    for ddl in (
        "ALTER TABLE curated_posts ADD COLUMN subvurs_impact_score REAL DEFAULT 0.0",
        "ALTER TABLE curated_posts ADD COLUMN subvurs_impact_report TEXT DEFAULT NULL",
        "ALTER TABLE curated_posts ADD COLUMN subvurs_impact_version TEXT DEFAULT NULL",
    ):
        try:
            conn.execute(ddl)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Migrate: add intel_first_brief_at (Phase 5c, Intel→Curator migration)
    # Existing rows get NULL (correct — none have been cited as Intel
    # seeds yet because the seed pivot itself just landed in Phase 5a).
    try:
        conn.execute(
            "ALTER TABLE curated_posts ADD COLUMN intel_first_brief_at TEXT DEFAULT NULL"
        )
        conn.commit()
    except sqlite3.OperationalError:
        # Column already exists — the only OperationalError the SQLite
        # ALTER TABLE ADD COLUMN path raises here. Anything else (DB
        # locked, disk full) should propagate, but sqlite3 raises those
        # later from .commit() / .execute() on the real call sites.
        pass

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

def save_article(article: RawArticle) -> tuple[SaveOutcome, RawArticle]:
    """Save a raw article to the database.

    Behaviour by URL state:
      - URL is new           → INSERT, returns ("inserted", article)
      - URL already present  → UPDATE in place, returns ("updated", article)
                               (article.id is rewritten to the existing row's id
                               so the caller sees a consistent identifier)

    The UPDATE-on-collision design avoids SQLite's REPLACE conflict resolution,
    which does DELETE-then-INSERT and triggers
    `FOREIGN KEY constraint failed (19)` whenever a referencing
    `curated_posts.article_id` exists. That FK violation was previously
    swallowed silently by `except sqlite3.IntegrityError: pass`, which caused
    every refetch of a curated URL to be reported as saved but actually be
    dropped — the bug behind GH Actions runs that printed "Fetched 8 new
    articles" while persisting zero rows.

    `curated` is sticky-true on UPDATE: once an article has been marked
    curated=1, subsequent fetch-path saves (which pass `article.curated=False`
    by default) cannot un-curate it. The curator path
    (`curator.py:188` setting `article.curated = True`) still flips
    curated=0 → 1.
    """
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM raw_articles WHERE url = ?", (article.url,)
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO raw_articles
                (id, source_id, source_name, source_type, title, url, summary, content,
                 author, image_url, published_at, fetched_at, arxiv_id, arxiv_categories,
                 arxiv_authors, relevance_score, detected_topics, curated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
                ),
            )
            conn.commit()
            outcome: SaveOutcome = "inserted"
        else:
            article.id = existing["id"]
            conn.execute(
                """
                UPDATE raw_articles SET
                    source_id = ?,
                    source_name = ?,
                    source_type = ?,
                    title = ?,
                    summary = ?,
                    content = ?,
                    author = ?,
                    image_url = ?,
                    published_at = ?,
                    fetched_at = ?,
                    arxiv_id = ?,
                    arxiv_categories = ?,
                    arxiv_authors = ?,
                    relevance_score = ?,
                    detected_topics = ?,
                    curated = CASE WHEN curated = 1 THEN 1 ELSE ? END
                WHERE id = ?
                """,
                (
                    article.source_id,
                    article.source_name,
                    article.source_type.value,
                    article.title,
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
                    article.id,
                ),
            )
            conn.commit()
            outcome = "updated"
    except sqlite3.IntegrityError as exc:
        # Defensive classifier: with the UPDATE-on-collision path above the
        # curated_posts FK can no longer fire, but any future schema or call
        # path that re-introduces a FOREIGN KEY violation will be visible
        # rather than silently swallowed.
        if "FOREIGN KEY" in str(exc):
            outcome = "fk_blocked"
        else:
            outcome = "other_error"
    finally:
        conn.close()
    return outcome, article


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


def save_raw_article(article: RawArticle) -> tuple[SaveOutcome, RawArticle]:
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
         topics, tags, relevance_score, status, curated_at, published_to_site_at, slug, meta_description,
         subvurs_notes,
         subvurs_impact_score, subvurs_impact_report, subvurs_impact_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        post.subvurs_notes,
        post.subvurs_impact_score,
        post.subvurs_impact_report,
        post.subvurs_impact_version,
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
        subvurs_notes=row["subvurs_notes"] if "subvurs_notes" in row.keys() else "",
        subvurs_impact_score=(
            row["subvurs_impact_score"]
            if "subvurs_impact_score" in row.keys() and row["subvurs_impact_score"] is not None
            else 0.0
        ),
        subvurs_impact_report=(
            row["subvurs_impact_report"]
            if "subvurs_impact_report" in row.keys()
            else None
        ),
        subvurs_impact_version=(
            row["subvurs_impact_version"]
            if "subvurs_impact_version" in row.keys()
            else None
        ),
    )


def list_curated_posts(
    status: PostStatus | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[CuratedPost]:
    """Alias for list_posts."""
    return list_posts(status=status, since=since, limit=limit)


# The exact tail of curator._generate_fallback_commentary(). Posts whose
# curator_commentary ends with this string were generated on the template
# fallback path (Claude API unavailable), not by the model — they are the
# recurate selector's signal. Kept here as the single source of truth so a
# template change forces both sites to update together.
FALLBACK_COMMENTARY_SIGNATURE = (
    "may have implications for the broader quantum computing field"
)


def list_fallback_commentary_posts(
    start_date: str,
    end_date: str,
) -> list[CuratedPost]:
    """List posts whose commentary is the template fallback, by curated_at.

    Args:
        start_date: inclusive lower bound, ``YYYY-MM-DD`` (matched against
            ``date(curated_at)``).
        end_date: inclusive upper bound, ``YYYY-MM-DD``.

    Returns every ``curated_posts`` row in ``[start_date, end_date]`` whose
    ``curator_commentary`` contains :data:`FALLBACK_COMMENTARY_SIGNATURE`,
    regardless of status (draft and published both degrade the site). Order
    is by ``curated_at`` so the caller sees a stable, day-grouped sequence.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM curated_posts
        WHERE curator_commentary LIKE '%' || ? || '%'
          AND date(curated_at) >= ?
          AND date(curated_at) <= ?
        ORDER BY curated_at
        """,
        (FALLBACK_COMMENTARY_SIGNATURE, start_date, end_date),
    ).fetchall()
    conn.close()
    return [_row_to_post(r) for r in rows]


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
