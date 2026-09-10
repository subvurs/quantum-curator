"""Tests for the missed-window backfill (``quantum_curator.backfill``).

Pins the pieces that protect the daily pipeline from the backfill:

  * ``arxiv_day_query`` emits the per-day ``submittedDate`` range the
    arXiv API expects, with the category disjunction the daily fetch uses.
  * ``backdate`` sets ``fetched_at`` to ``published_at`` (naive UTC) so
    the daily ``curate`` selector (``fetched_at >= now - 1 day``) never
    sees the backfilled pool.
  * ``select_backfill_candidates`` honours the per-day arXiv cap, the
    news relevance floor, the window bounds, and skips curated rows.
  * ``run_backfill_curate`` is resumable: ids already in the state file
    are not re-curated, and ids that fail are not marked done.
  * ``run_backfill_digests`` skips days that already have a digest and
    days with no published posts, and creates the rest.

No network, no LLM: the curator is stubbed where it would call out.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from quantum_curator import backfill, config, db
from quantum_curator.models import (
    CuratedPost,
    DailyDigest,
    PostStatus,
    RawArticle,
    Source,
    SourceType,
)


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config.get_settings.cache_clear()
    settings = config.get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db.init_db()
    yield tmp_path
    config.get_settings.cache_clear()


def _source(name: str, stype: SourceType) -> Source:
    src = Source(name=name, source_type=stype, url="https://example.org",
                 feed_url="https://example.org/feed/")
    db.save_source(src)
    return src


def _article(src: Source, title: str, published: datetime, score: float,
             curated: bool = False) -> RawArticle:
    a = RawArticle(
        source_id=src.id, source_name=src.name, source_type=src.source_type,
        title=title, url=f"https://example.org/{abs(hash(title))}",
        summary="quantum computing qubit", published_at=published,
        relevance_score=score, curated=curated,
    )
    outcome, saved = db.save_raw_article(a)
    assert outcome == "inserted"
    return saved


# --- pure helpers -------------------------------------------------------


def test_arxiv_day_query_format():
    q = backfill.arxiv_day_query(["quant-ph", "cond-mat"], date(2026, 8, 21))
    assert q == (
        "(cat:quant-ph OR cat:cond-mat) AND "
        "submittedDate:[202608210000 TO 202608212359]"
    )


def test_arxiv_day_query_defaults_to_quant_ph():
    assert backfill.arxiv_day_query([], date(2026, 1, 2)).startswith("(cat:quant-ph)")


def test_day_range_inclusive_and_ordered():
    days = backfill.day_range(date(2026, 8, 30), date(2026, 9, 2))
    assert days == [date(2026, 8, 30), date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 2)]
    with pytest.raises(ValueError):
        backfill.day_range(date(2026, 9, 2), date(2026, 9, 1))


def test_backdate_uses_published_at_as_naive_utc():
    src = Source(name="s", source_type=SourceType.ARXIV, url="u")
    aware = datetime(2026, 8, 20, 15, 0, tzinfo=timezone(timedelta(hours=2)))
    a = RawArticle(source_id=src.id, source_name="s", source_type=SourceType.ARXIV,
                   title="t", url="https://x/1", published_at=aware)
    b = RawArticle(source_id=src.id, source_name="s", source_type=SourceType.ARXIV,
                   title="t2", url="https://x/2", published_at=None)
    fallback = datetime(2026, 8, 18)
    backfill.backdate([a, b], fallback)
    assert a.fetched_at == datetime(2026, 8, 20, 13, 0)      # converted to UTC, naive
    assert a.fetched_at.tzinfo is None
    assert b.fetched_at == fallback


# --- candidate selection ------------------------------------------------


def test_select_candidates_caps_arxiv_per_day_and_filters_news(isolated_db):
    arx = _source("arXiv Quantum Physics", SourceType.ARXIV)
    news = _source("The Quantum Insider", SourceType.RSS)
    d1 = datetime(2026, 8, 20, 10, 0)
    d2 = datetime(2026, 8, 21, 10, 0)
    # day 1: four arXiv (cap 2 keeps the two highest), two news (one below floor)
    _article(arx, "a1", d1, 0.9)
    _article(arx, "a2", d1, 0.8)
    _article(arx, "a3", d1, 0.7)
    _article(arx, "a4", d1, 0.6)
    _article(news, "n-good", d1, 0.7)
    _article(news, "n-low", d1, 0.4)
    # day 2: one arXiv already curated (skipped), one arXiv fresh
    _article(arx, "a5-curated", d2, 0.95, curated=True)
    _article(arx, "a6", d2, 0.5)
    # outside window
    _article(arx, "a7-outside", datetime(2026, 9, 5, 10, 0), 0.99)

    picked = backfill.select_backfill_candidates(
        date(2026, 8, 18), date(2026, 9, 3), arxiv_per_day=2
    )
    titles = sorted(p.title for p in picked)
    assert titles == ["a1", "a2", "a6", "n-good"]


# --- resumable curation -------------------------------------------------


class _StubCurator:
    """Stands in for Curator: records what it was asked to curate."""

    def __init__(self, fail_titles: set[str] | None = None):
        self.seen: list[str] = []
        self.fail_titles = fail_titles or set()

    async def curate_batch(self, articles, max_concurrent=3):
        posts = []
        for a in articles:
            self.seen.append(a.title)
            if a.title in self.fail_titles:
                continue
            posts.append(CuratedPost(
                article_id=a.id, title=a.title, original_url=a.url,
                source_name=a.source_name, summary=a.summary,
                curator_commentary="c", relevance_score=a.relevance_score,
                published_at=a.published_at, status=PostStatus.DRAFT,
            ))
        return posts

    async def auto_publish(self, posts):
        return posts


@pytest.mark.asyncio
async def test_curate_resumes_and_skips_failed(isolated_db, monkeypatch, tmp_path):
    arx = _source("arXiv Quantum Physics", SourceType.ARXIV)
    d = datetime(2026, 8, 25, 9, 0)
    a1 = _article(arx, "one", d, 0.9)
    a2 = _article(arx, "two", d, 0.8)
    a3 = _article(arx, "three", d, 0.7)

    state = tmp_path / "state.json"
    state.write_text(json.dumps({"done_ids": [a1.id], "posts_created": 1}))

    stub = _StubCurator(fail_titles={"three"})
    monkeypatch.setattr("quantum_curator.curator.Curator", lambda: stub)
    monkeypatch.setattr(backfill, "daily_run_active", lambda: False)

    result = await backfill.run_backfill_curate(
        date(2026, 8, 18), date(2026, 9, 3), state_path=state,
        chunk_size=5, pause_while_daily_run=True, log=lambda m: None,
    )
    assert stub.seen == ["two", "three"]              # "one" was already done
    saved = json.loads(state.read_text())
    assert set(saved["done_ids"]) == {a1.id, a2.id}   # "three" failed → retry next run
    assert result["curated_this_run"] == 1


# --- digests ------------------------------------------------------------


class _DigestCurator:
    def __init__(self):
        self.calls: list[tuple[datetime, int]] = []

    async def create_daily_digest(self, date=None, posts=None):
        self.calls.append((date, len(posts or [])))
        digest = DailyDigest(date=date, title=f"Digest {date:%Y-%m-%d}",
                             summary="s", post_ids=[p.id for p in posts or []])
        db.save_daily_digest(digest)
        return digest


@pytest.mark.asyncio
async def test_digests_created_only_for_days_with_posts_and_no_digest(isolated_db, monkeypatch):
    arx = _source("arXiv Quantum Physics", SourceType.ARXIV)
    for day in (20, 21, 22):
        a = _article(arx, f"p{day}", datetime(2026, 8, day, 8, 0), 0.9, curated=True)
        db.save_curated_post(CuratedPost(
            article_id=a.id, title=a.title, original_url=a.url, source_name=a.source_name,
            summary=a.summary, curator_commentary="c", relevance_score=0.9,
            published_at=a.published_at, status=PostStatus.PUBLISHED,
        ))
    # Aug 21 already has a digest
    db.save_daily_digest(DailyDigest(date=datetime(2026, 8, 21), title="existing", summary="x"))

    stub = _DigestCurator()
    monkeypatch.setattr("quantum_curator.curator.Curator", lambda: stub)
    result = await backfill.run_backfill_digests(
        date(2026, 8, 20), date(2026, 8, 23), log=lambda m: None
    )
    assert result["created"] == ["2026-08-20", "2026-08-22"]
    assert result["skipped_existing"] == ["2026-08-21"]
    assert result["no_posts"] == ["2026-08-23"]
    assert [c[1] for c in stub.calls] == [1, 1]
