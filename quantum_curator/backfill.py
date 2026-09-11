"""Backfill a missed date window: fetch, curate, and digest.

Why this exists
---------------
The daily pipeline only ever looks at "now": the arXiv fetcher asks for
the 50 most recently submitted papers, RSS fetchers read the feed's
current page, and ``curate`` selects uncurated articles fetched in the
last 24 hours. When the K11 box was off from 2026-08-19 06:41 to
2026-09-04 14:34 (and the run script hard-failed on ``git pull`` behind a
DNS outage on Aug 17–19), the resumed Sep 4 run picked up only what the
feeds still carried. Seventeen days of arXiv submissions and most of the
news window were never ingested, and no digests exist for Aug 18–Sep 3.

Three stages, each idempotent and separately invokable from the CLI:

``fetch``
    * arXiv: one API query per calendar day per arXiv source, using
      ``submittedDate:[YYYYMMDD0000 TO YYYYMMDD2359]`` and the same
      ``max_results`` the daily fetch uses (50), so the backfilled pool per
      day mirrors what the daily run would have seen. 3.5 s between
      requests (arXiv API etiquette).
    * paginated RSS (WordPress ``?paged=N``): The Quantum Insider and
      Quantum Computing Report expose older pages; walk back until the
      page is entirely older than ``since``.
    * every backfilled article has ``fetched_at`` set to its
      ``published_at`` (backdated). This matters: the daily ``curate``
      selects ``fetched_at >= now - 1 day``; without backdating, the next
      04:00 run would try to curate the whole backfilled pool in one go
      and blow its 6 h unit timeout.

``curate``
    Selects uncurated raw articles published inside the window, caps
    arXiv items per day (default 30, roughly what a daily run curates)
    and takes all non-arXiv items above the auto-publish threshold, then
    runs the normal ``Curator.curate_batch`` (commentary, Subvurs notes,
    subvurs_impact score) in small chunks. Progress is written to a JSON
    state file after every chunk so the job can be interrupted and
    resumed. Between chunks it optionally pauses while the daily
    ``quantum-curator.service`` is active so the two never contend for
    the local model at the same time.

``digests``
    For each calendar day in the window without a ``daily_digests`` row,
    builds one from the posts published that day.

All evidence produced here is labelled exactly like the daily run's
(same scorer version, same catalog version); the only difference is the
``fetched_at`` backdating, which is deliberate and documented above.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import feedparser
import httpx

from . import db
from .aggregator import Aggregator
from .config import get_settings
from .models import PostStatus, RawArticle, Source, SourceType
from .sources.arxiv import ARXIV_API_URL, ArxivFetcher
from .sources.rss import RSSFetcher


ARXIV_REQUEST_DELAY_SEC = 3.5
ARXIV_PER_DAY_DEFAULT = 50          # == ArxivFetcher.fetch(max_results=50)
CURATE_ARXIV_PER_DAY_DEFAULT = 30   # ~what a daily run curates from arXiv
CURATE_NEWS_MIN_RELEVANCE = 0.5     # == Curator.auto_publish(min_score)
RSS_MAX_PAGES = 60

# Feeds known to honour WordPress-style ``?paged=N``. Everything else is
# served as a single page and is already covered by the daily fetch.
PAGINATED_FEEDS: frozenset[str] = frozenset({
    "The Quantum Insider",
    "Quantum Computing Report",
})


# --- helpers ------------------------------------------------------------


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def day_range(since: date, until: date) -> list[date]:
    """Inclusive list of calendar days from ``since`` to ``until``."""
    if until < since:
        raise ValueError(f"until ({until}) is before since ({since})")
    return [since + timedelta(days=i) for i in range((until - since).days + 1)]


def arxiv_day_query(categories: list[str], day: date) -> str:
    """arXiv API ``search_query`` for one submission day."""
    cats = " OR ".join(f"cat:{c}" for c in (categories or ["quant-ph"]))
    stamp = day.strftime("%Y%m%d")
    return f"({cats}) AND submittedDate:[{stamp}0000 TO {stamp}2359]"


def backdate(articles: list[RawArticle], fallback: datetime) -> list[RawArticle]:
    """Set ``fetched_at`` to ``published_at`` so the daily selector ignores them."""
    for a in articles:
        a.fetched_at = _naive_utc(a.published_at) or fallback
    return articles


# Full path so an unrelated shell whose argv merely mentions the script
# name (e.g. an ssh one-liner inspecting the journal) is not mistaken
# for the daily run.
DAILY_RUN_PROCESS_PATTERN = "subvurs_deploy/curator/run_curator_daily.sh"


def daily_run_active() -> bool:
    """True when the daily pipeline is running (K11 only).

    Checks for the run script's process first (``pgrep -f``), then falls
    back to ``systemctl --user is-active``. The process check is primary
    because ``systemctl --user`` needs the user's session bus
    (``XDG_RUNTIME_DIR`` / ``DBUS_SESSION_BUS_ADDRESS``); under ``nohup``
    from an SSH session those are unset, the call fails with
    "Failed to connect to bus", and the guard silently reported "idle".
    That is exactly what happened on Sep 10–11 2026: the backfill never
    paused, contended with the daily run for the local model, and both
    daily runs hit the 6 h unit timeout inside intel-email.
    """
    try:
        proc = subprocess.run(
            ["pgrep", "-f", DAILY_RUN_PROCESS_PATTERN],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return True
    except (OSError, subprocess.TimeoutExpired):
        # pgrep missing (unlikely on Linux) or hung: fall through.
        pass
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", "quantum-curator.service"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        # No systemd (macOS dev box) or systemctl hung — treat as idle;
        # the pause is a courtesy, not a correctness requirement.
        return False
    return proc.stdout.strip() == "active"


# --- stage 1: fetch -----------------------------------------------------


async def fetch_arxiv_window(
    source: Source,
    since: date,
    until: date,
    per_day: int = ARXIV_PER_DAY_DEFAULT,
    *,
    delay_sec: float = ARXIV_REQUEST_DELAY_SEC,
    log: Callable[[str], None] = print,
) -> list[RawArticle]:
    """One arXiv API call per day; newest ``per_day`` submissions each."""
    fetcher = ArxivFetcher()
    out: list[RawArticle] = []
    async with httpx.AsyncClient(timeout=fetcher.timeout) as client:
        for day in day_range(since, until):
            params = {
                "search_query": arxiv_day_query(source.arxiv_categories, day),
                "start": 0,
                "max_results": per_day,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
            resp = await client.get(ARXIV_API_URL, params=params)
            resp.raise_for_status()
            got = fetcher._parse_response(resp.text, source)
            log(f"  arXiv {source.name} {day}: {len(got)} entries")
            out.extend(got)
            await asyncio.sleep(delay_sec)
    return out


async def fetch_paginated_rss(
    source: Source,
    since: date,
    *,
    max_pages: int = RSS_MAX_PAGES,
    log: Callable[[str], None] = print,
) -> list[RawArticle]:
    """Walk ``feed_url?paged=N`` back until a page is entirely older than ``since``."""
    if not source.feed_url:
        return []
    fetcher = RSSFetcher()
    since_dt = datetime.combine(since, datetime.min.time())
    out: list[RawArticle] = []
    sep = "&" if "?" in source.feed_url else "?"
    async with httpx.AsyncClient(
        timeout=fetcher.timeout,
        follow_redirects=True,
        headers={"User-Agent": "QuantumCurator/1.0 (+https://quantum-pulse.github.io)"},
    ) as client:
        for page in range(1, max_pages + 1):
            resp = await client.get(f"{source.feed_url}{sep}paged={page}")
            if resp.status_code == 404:
                # WordPress returns 404 past the last page.
                break
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
            if not feed.entries:
                break
            page_articles = [
                a for a in (fetcher._parse_entry(e, source) for e in feed.entries)
                if a is not None
            ]
            dated = [a.published_at for a in page_articles if a.published_at]
            out.extend(page_articles)
            log(f"  RSS {source.name} page {page}: {len(page_articles)} entries")
            if dated and max(dated) < since_dt:
                break
            await asyncio.sleep(1.0)
    return out


async def run_backfill_fetch(
    since: date,
    until: date,
    *,
    arxiv_per_day: int = ARXIV_PER_DAY_DEFAULT,
    include_news: bool = True,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Fetch, score, filter and save the window. Returns per-source counts."""
    settings = get_settings()
    aggregator = Aggregator()
    sources = db.list_sources(enabled=True)
    fetched: list[RawArticle] = []
    per_source: dict[str, int] = {}
    failures: dict[str, str] = {}

    for source in sources:
        try:
            if source.source_type == SourceType.ARXIV:
                got = await fetch_arxiv_window(
                    source, since, until, arxiv_per_day, log=log
                )
            elif include_news and source.source_type == SourceType.RSS \
                    and source.name in PAGINATED_FEEDS:
                got = await fetch_paginated_rss(source, since, log=log)
            else:
                continue
        except Exception as exc:  # noqa: BLE001 — per-source isolation
            # Mirror fetch_all_sources: one broken feed must not abort the
            # window; the failure is reported in the returned counts.
            failures[source.name] = f"{type(exc).__name__}: {exc}"
            log(f"  FAILED {source.name}: {failures[source.name][:200]}")
            continue
        per_source[source.name] = len(got)
        fetched.extend(got)

    # Same post-processing as the daily fetch: dedupe, score, relevance
    # floor, then keep only the window.
    unique = aggregator._deduplicate(fetched)
    scored = aggregator._score_articles(unique)
    min_score = settings.min_relevance_score
    since_dt = datetime.combine(since, datetime.min.time())
    until_dt = datetime.combine(until, datetime.max.time())
    kept: list[RawArticle] = []
    for a in scored:
        if a.relevance_score < min_score:
            continue
        pub = _naive_utc(a.published_at)
        if pub is None or not (since_dt <= pub <= until_dt):
            continue
        kept.append(a)
    backdate(kept, since_dt)

    counts = {"inserted": 0, "updated": 0, "fk_blocked": 0, "other_error": 0}
    for a in kept:
        outcome, _ = db.save_raw_article(a)
        counts[outcome] += 1

    return {
        "window": [since.isoformat(), until.isoformat()],
        "fetched_raw": len(fetched),
        "unique": len(unique),
        "kept_in_window": len(kept),
        "per_source": per_source,
        "failures": failures,
        **counts,
    }


# --- stage 2: curate ----------------------------------------------------


def select_backfill_candidates(
    since: date,
    until: date,
    *,
    arxiv_per_day: int = CURATE_ARXIV_PER_DAY_DEFAULT,
    news_min_relevance: float = CURATE_NEWS_MIN_RELEVANCE,
) -> list[RawArticle]:
    """Uncurated articles in the window, capped per day like a daily run."""
    since_dt = datetime.combine(since, datetime.min.time())
    until_dt = datetime.combine(until, datetime.max.time())
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM raw_articles
            WHERE curated = 0
              AND published_at IS NOT NULL
              AND published_at >= ? AND published_at <= ?
            ORDER BY published_at, relevance_score DESC
            """,
            (since_dt.isoformat(), until_dt.isoformat()),
        ).fetchall()
    finally:
        conn.close()

    articles = [db._row_to_article(r) for r in rows]
    by_day: dict[date, list[RawArticle]] = {}
    for a in articles:
        pub = _naive_utc(a.published_at)
        if pub is None:
            continue
        by_day.setdefault(pub.date(), []).append(a)

    selected: list[RawArticle] = []
    for day in sorted(by_day):
        items = sorted(by_day[day], key=lambda a: a.relevance_score, reverse=True)
        arxiv_items = [a for a in items if a.source_type == SourceType.ARXIV]
        other_items = [
            a for a in items
            if a.source_type != SourceType.ARXIV
            and a.relevance_score >= news_min_relevance
        ]
        selected.extend(other_items)
        selected.extend(arxiv_items[:arxiv_per_day])
    return selected


def _load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {"done_ids": [], "posts_created": 0, "started_at": datetime.utcnow().isoformat()}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.utcnow().isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(path)


async def run_backfill_curate(
    since: date,
    until: date,
    *,
    state_path: Path,
    arxiv_per_day: int = CURATE_ARXIV_PER_DAY_DEFAULT,
    chunk_size: int = 2,
    max_concurrent: int = 2,
    pause_while_daily_run: bool = True,
    pause_poll_sec: float = 120.0,
    auto_publish: bool = True,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Curate the window in resumable chunks. Returns a summary dict."""
    from .curator import Curator

    candidates = select_backfill_candidates(
        since, until, arxiv_per_day=arxiv_per_day
    )
    state = _load_state(state_path)
    done = set(state["done_ids"])
    todo = [a for a in candidates if a.id not in done]
    log(
        f"backfill-curate {since}..{until}: {len(candidates)} candidates, "
        f"{len(done)} already done, {len(todo)} to go"
    )
    if dry_run:
        by_day: dict[str, int] = {}
        for a in todo:
            key = (_naive_utc(a.published_at) or since_dt_fallback(since)).date().isoformat()
            by_day[key] = by_day.get(key, 0) + 1
        for k in sorted(by_day):
            log(f"  {k}: {by_day[k]}")
        return {"candidates": len(candidates), "todo": len(todo), "dry_run": True}

    curator = Curator()
    created = 0
    for i in range(0, len(todo), chunk_size):
        if pause_while_daily_run:
            while daily_run_active():
                log("daily quantum-curator.service is active — pausing backfill")
                await asyncio.sleep(pause_poll_sec)
        chunk = todo[i:i + chunk_size]
        posts = await curator.curate_batch(chunk, max_concurrent=max_concurrent)
        if auto_publish and posts:
            await curator.auto_publish(posts)
        created += len(posts)
        # Articles that raised inside curate_batch are logged there and
        # return None; they stay out of done_ids so a resume retries them.
        succeeded = {p.article_id for p in posts}
        state["done_ids"].extend(a.id for a in chunk if a.id in succeeded)
        state["posts_created"] = state.get("posts_created", 0) + len(posts)
        _save_state(state_path, state)
        log(
            f"  chunk {i // chunk_size + 1}/{(len(todo) + chunk_size - 1) // chunk_size}: "
            f"{len(posts)}/{len(chunk)} curated "
            f"(total this run {created}, state {len(state['done_ids'])})"
        )
    return {
        "candidates": len(candidates),
        "curated_this_run": created,
        "done_total": len(state["done_ids"]),
        "state_file": str(state_path),
    }


def since_dt_fallback(since: date) -> datetime:
    return datetime.combine(since, datetime.min.time())


# --- stage 3: digests ---------------------------------------------------


def posts_published_on(day: date) -> list:
    """Published posts whose published_at (or curated_at) falls on ``day``."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM curated_posts
            WHERE status = ?
              AND date(COALESCE(published_at, curated_at)) = ?
            ORDER BY relevance_score DESC
            """,
            (PostStatus.PUBLISHED.value, day.isoformat()),
        ).fetchall()
    finally:
        conn.close()
    return [db._row_to_post(r) for r in rows]


async def run_backfill_digests(
    since: date,
    until: date,
    *,
    overwrite: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Create a daily digest for each day in the window lacking one."""
    from .curator import Curator

    curator = Curator()
    created: list[str] = []
    skipped: list[str] = []
    empty: list[str] = []
    for day in day_range(since, until):
        day_dt = datetime.combine(day, datetime.min.time())
        if not overwrite and db.get_digest(day_dt) is not None:
            skipped.append(day.isoformat())
            continue
        posts = posts_published_on(day)
        if not posts:
            empty.append(day.isoformat())
            log(f"  {day}: no published posts — no digest")
            continue
        digest = await curator.create_daily_digest(date=day_dt, posts=posts)
        created.append(day.isoformat())
        log(f"  {day}: digest from {len(posts)} posts — {digest.title}")
    return {"created": created, "skipped_existing": skipped, "no_posts": empty}
