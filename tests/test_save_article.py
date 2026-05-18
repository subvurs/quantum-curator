"""Tests for `quantum_curator.db.save_article`.

These tests pin the behavior of the Patch A + Patch B fix:

  Patch A — classified outcomes (no silent IntegrityError swallow):
      save_article returns (outcome, article) where outcome is one of
      "inserted" | "updated" | "fk_blocked" | "other_error".

  Patch B — UPDATE-on-collision (no FK trigger on duplicate URL):
      Re-saving an existing URL that is referenced by curated_posts
      must succeed and return "updated", not "fk_blocked", because the
      DELETE half of SQLite's INSERT OR REPLACE no longer fires.

Bug history (do not delete this paragraph without reviewing):
  GH Actions runs printed "Fetched 8 new articles" while persisting
  zero rows. Root cause was `INSERT OR REPLACE` on `raw_articles`,
  whose DELETE-then-INSERT conflict resolution triggered
  `FOREIGN KEY constraint failed (19)` against
  `curated_posts.article_id`. The error was swallowed by
  `except sqlite3.IntegrityError: pass`. See
  /Users/mvm/.claude/plans/polished-imagining-hopcroft.md.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from quantum_curator import config, db
from quantum_curator.models import (
    PostStatus,
    RawArticle,
    Source,
    SourceType,
)


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point `get_settings()` at a fresh temp data_dir and init schema."""
    config.get_settings.cache_clear()
    monkeypatch.setenv("QC_DATA_DIR_OVERRIDE_FOR_TESTS", str(tmp_path))

    # Direct monkeypatch is simpler than env-var plumbing.
    settings = config.get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    db.init_db()
    yield tmp_path
    config.get_settings.cache_clear()


def _make_source(name: str = "Test Source") -> Source:
    src = Source(
        name=name,
        source_type=SourceType.RSS,
        url="https://example.com/feed",
        feed_url="https://example.com/feed.xml",
    )
    db.save_source(src)
    return src


def _make_article(source: Source, url: str = "https://example.com/article/1") -> RawArticle:
    return RawArticle(
        source_id=source.id,
        source_name=source.name,
        source_type=source.source_type,
        title="Test article",
        url=url,
        summary="A summary.",
        fetched_at=datetime.utcnow(),
    )


def test_save_new_article_returns_inserted(isolated_db):
    source = _make_source()
    article = _make_article(source)

    outcome, returned = db.save_article(article)

    assert outcome == "inserted"
    assert returned.id == article.id

    # Round-trip from DB.
    fetched = db.get_article(article.id)
    assert fetched is not None
    assert fetched.url == article.url


def test_resave_same_url_returns_updated(isolated_db):
    source = _make_source()
    article = _make_article(source)
    db.save_article(article)

    # Second save with a new in-memory object that shares the same URL but
    # a different id (simulates the fetch path on a subsequent run).
    duplicate = _make_article(source, url=article.url)
    duplicate.title = "Updated title"
    assert duplicate.id != article.id

    outcome, returned = db.save_article(duplicate)

    assert outcome == "updated"
    # save_article rewrites the in-memory id to match the existing row so the
    # caller sees a single canonical identifier.
    assert returned.id == article.id

    fetched = db.get_article(article.id)
    assert fetched is not None
    assert fetched.title == "Updated title"


def test_resave_does_not_un_curate(isolated_db):
    """`curated` is sticky-true. A fetch-path resave must not flip 1 → 0."""
    source = _make_source()
    article = _make_article(source)
    article.curated = True
    db.save_article(article)

    refetched = _make_article(source, url=article.url)
    refetched.curated = False  # Default state coming from fetch path.
    db.save_article(refetched)

    fetched = db.get_article(article.id)
    assert fetched is not None
    assert fetched.curated is True, "curated flag must be sticky-true on update"


def test_resave_with_referencing_curated_post_does_not_fk_block(isolated_db):
    """The original bug: a curated_posts row referencing the article id
    used to make INSERT OR REPLACE blow up with FK violation. UPDATE-on-
    collision must keep the same row id and succeed."""
    source = _make_source()
    article = _make_article(source)
    db.save_article(article)

    # Insert a curated_posts row referencing this article (this is what
    # `curator.py` does during publication).
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO curated_posts (id, article_id, title, original_url, source_name, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "curated-post-1",
                article.id,
                article.title,
                article.url,
                article.source_name,
                PostStatus.PUBLISHED.value,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Refetch the same URL — this is the exact scenario that previously
    # produced "Fetched 8 articles, 0 persisted".
    refetched = _make_article(source, url=article.url)
    refetched.title = "Refetched title"
    outcome, _ = db.save_article(refetched)

    assert outcome == "updated", (
        "duplicate-URL refetch with a referencing curated_posts row must "
        "succeed via UPDATE, not return fk_blocked"
    )

    # Article row still exists, with the same id.
    fetched = db.get_article(article.id)
    assert fetched is not None
    assert fetched.title == "Refetched title"

    # The referencing curated_posts row is still intact.
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT article_id FROM curated_posts WHERE id = ?", ("curated-post-1",)
        ).fetchone()
        assert row is not None
        assert row["article_id"] == article.id
    finally:
        conn.close()


def test_fk_violation_on_orphan_source_returns_fk_blocked(isolated_db):
    """If a NEW article is inserted with a source_id that does not exist
    in `sources`, the FK on raw_articles.source_id fires. The classifier
    must report `fk_blocked` rather than silently dropping the row or
    crashing."""
    article = RawArticle(
        source_id="nonexistent-source-id",
        source_name="Phantom",
        source_type=SourceType.RSS,
        title="Orphan",
        url="https://example.com/orphan",
        fetched_at=datetime.utcnow(),
    )

    outcome, _ = db.save_article(article)

    assert outcome == "fk_blocked"
    # And the row must not have landed.
    assert db.get_article(article.id) is None


def test_save_raw_article_alias_matches_signature(isolated_db):
    """`save_raw_article` is the alias used by aggregator + curator. It
    must return the same tuple shape as `save_article`."""
    source = _make_source()
    article = _make_article(source, url="https://example.com/alias-test")
    outcome, returned = db.save_raw_article(article)
    assert outcome == "inserted"
    assert returned.id == article.id
