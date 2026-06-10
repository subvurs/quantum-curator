"""Tests for Phase 5e — Intel synth deliver() routing + channel separation.

Pins Phase 5a/5c/5d behavior (Intel→Curator migration, Plan B pivot):

  1. deliver() routes cited entry_ids by SEED_ID_OFFSET:
       * eid <  SEED_ID_OFFSET → quantum_intel_entries.first_brief_at
       * eid >= SEED_ID_OFFSET → curated_posts.intel_first_brief_at via UUID map
       * eid >= SEED_ID_OFFSET with no UUID → silent no-op (the
         hallucinated-ID case — the LLM cited a synthetic ID we never
         handed it; stamping the wrong row would corrupt the
         anti-recurrence column).
  2. Both stamp paths are idempotent — a second deliver() call on the
     same entry_id / curated_post_id does NOT overwrite the original
     timestamp. UPDATE ... WHERE col IS NULL semantics.
  3. today_curated_seeds() projection: synthetic entry_ids start at
     SEED_ID_OFFSET, _curated_post_id round-trips, and only
     status='published' rows within the curated_at window seed.
  4. Channel-separation smoke test (no LLM call): render_text and
     render_bluesky stay in their lanes — daily_summary's Bluesky
     renderer is short and link-only; render_text is the multi-section
     plaintext digest. Neither path leaks the other channel's content.

These tests do not call the Anthropic API — they exercise routing on
synthetic concept dicts and pre-built payloads.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from quantum_curator import config, db
from quantum_curator.intel import daily_summary, inventory_view, synthesizer
from quantum_curator.models import RawArticle, Source, SourceType


# --- Fixtures -----------------------------------------------------

@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh schema in a temp dir. Same pattern as other Curator tests."""
    config.get_settings.cache_clear()
    settings = config.get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db.init_db()
    yield tmp_path
    _SOURCE_CACHE.pop(tmp_path, None)
    config.get_settings.cache_clear()


def _utc_iso(offset_minutes: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    ).isoformat()


_SOURCE_CACHE: dict[Path, str] = {}


def _ensure_source(data_dir: Path) -> str:
    """Create one shared Source row per test DB. Returns its id."""
    sid = _SOURCE_CACHE.get(data_dir)
    if sid is not None:
        return sid
    src = Source(
        name="Test Source",
        source_type=SourceType.RSS,
        url="https://example.com/feed",
        feed_url="https://example.com/feed.xml",
    )
    db.save_source(src)
    _SOURCE_CACHE[data_dir] = src.id
    return src.id


def _insert_curated_post(
    data_dir: Path,
    *,
    post_id: str | None = None,
    title: str = "Test curated post",
    status: str = "published",
    curated_at: str | None = None,
    topics: list[str] | None = None,
    intel_first_brief_at: str | None = None,
) -> str:
    """Insert a minimal curated_posts row (with FK chain). Returns the UUID."""
    pid = post_id or str(uuid4())
    aid = str(uuid4())
    topics_json = json.dumps(topics or ["quantum"])

    # FK chain: curated_posts → raw_articles → sources. Build it through
    # the db helpers so the model defaults stay honest.
    src_id = _ensure_source(data_dir)
    article = RawArticle(
        id=aid,
        source_id=src_id,
        source_name="Test Source",
        source_type=SourceType.RSS,
        title=title,
        url=f"https://example.com/{pid}",
        summary="A summary of the article body.",
        fetched_at=datetime.now(timezone.utc),
    )
    db.save_raw_article(article)

    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO curated_posts
              (id, article_id, title, original_url, summary, source_name,
               curator_commentary, topics, status, curated_at,
               published_at, intel_first_brief_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid,
                aid,
                title,
                f"https://example.com/{pid}",
                "A summary of the article body.",
                "Test Source",
                "Curator commentary for this post.",
                topics_json,
                status,
                curated_at or _utc_iso(offset_minutes=-5),
                _utc_iso(offset_minutes=-60 * 24),  # published yesterday
                intel_first_brief_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return pid


def _insert_intel_entry(
    entry_id: int,
    *,
    first_brief_at: str | None = None,
) -> None:
    """Insert a minimal quantum_intel_entries row."""
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO quantum_intel_entries
              (entry_id, fingerprint, title, source, url,
               date_collected, date_published, entry_type,
               summary, technical_detail, first_brief_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                f"fp{entry_id:016x}",
                f"Intel entry {entry_id}",
                "Intel Source",
                f"https://example.com/intel/{entry_id}",
                _utc_iso(offset_minutes=-60 * 24 * 30),  # 30d ago
                "",
                "preprint",
                "Historical entry summary.",
                "Technical detail blob.",
                first_brief_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _intel_first_brief_at(entry_id: int) -> str | None:
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT first_brief_at FROM quantum_intel_entries WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["first_brief_at"] if row else None


def _seed_intel_first_brief_at(curated_post_id: str) -> str | None:
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT intel_first_brief_at FROM curated_posts WHERE id = ?",
            (curated_post_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["intel_first_brief_at"] if row else None


def _make_concept(entry_ids: list[int], name: str = "concept-a") -> dict:
    """Build a minimal concept dict matching synthesizer.deliver()'s shape."""
    return {
        "product_name": name,
        "confidence": 0.9,
        "entry_ids_combined": entry_ids,
        "combination_insight": "Combine entries.",
        "target_market": "Researchers.",
        "value_proposition": "Better synthesis.",
        "technical_approach": "Combine entries algorithmically.",
        "competitive_moat": "Domain expertise.",
        "build_requirements": ["python"],
        "risk_factors": ["scope creep"],
        "first_three_steps": ["plan", "prototype", "test"],
        "estimated_timeline": "TBD",
    }


# --- 1. deliver() routing ----------------------------------------

def test_deliver_routes_intel_entry_to_first_brief_at(
    isolated_db, tmp_path: Path
):
    """eid < SEED_ID_OFFSET → quantum_intel_entries.first_brief_at."""
    _insert_intel_entry(42)

    assert _intel_first_brief_at(42) is None

    briefs_dir = tmp_path / "briefs"
    paths = synthesizer.deliver(
        [_make_concept([42])],
        briefs_dir=briefs_dir,
        seed_id_to_uuid={},
    )

    assert len(paths) == 1
    assert paths[0].exists()
    # Intel-side stamp landed.
    stamp = _intel_first_brief_at(42)
    assert stamp is not None and stamp != ""


def test_deliver_routes_seed_entry_to_intel_first_brief_at(
    isolated_db, tmp_path: Path
):
    """eid >= SEED_ID_OFFSET → curated_posts.intel_first_brief_at via UUID map."""
    uuid = _insert_curated_post(isolated_db)
    seed_id = inventory_view.SEED_ID_OFFSET + 0

    assert _seed_intel_first_brief_at(uuid) is None

    paths = synthesizer.deliver(
        [_make_concept([seed_id])],
        briefs_dir=tmp_path / "briefs",
        seed_id_to_uuid={seed_id: uuid},
    )

    assert len(paths) == 1
    # Seed-side stamp landed.
    stamp = _seed_intel_first_brief_at(uuid)
    assert stamp is not None and stamp != ""


def test_deliver_hallucinated_seed_id_silently_noops(
    isolated_db, tmp_path: Path
):
    """Seed-range eid with no UUID in the map → no stamp anywhere.

    Defensive: if a synthetic entry_id is cited that we never handed
    the LLM, stamping the wrong curated_posts row would corrupt the
    anti-recurrence column. The contract is silent no-op.
    """
    uuid = _insert_curated_post(isolated_db)
    real_seed_id = inventory_view.SEED_ID_OFFSET + 0
    bogus_seed_id = inventory_view.SEED_ID_OFFSET + 9999

    paths = synthesizer.deliver(
        [_make_concept([bogus_seed_id])],
        briefs_dir=tmp_path / "briefs",
        # Map ONLY the real seed; the bogus one has no entry.
        seed_id_to_uuid={real_seed_id: uuid},
    )

    assert len(paths) == 1
    # The real (un-cited) curated_post must stay NULL.
    assert _seed_intel_first_brief_at(uuid) is None


def test_deliver_seed_routing_with_none_uuid_map(
    isolated_db, tmp_path: Path
):
    """seed_id_to_uuid=None falls back to empty map (pre-5c posture)."""
    uuid = _insert_curated_post(isolated_db)
    seed_id = inventory_view.SEED_ID_OFFSET + 0

    paths = synthesizer.deliver(
        [_make_concept([seed_id])],
        briefs_dir=tmp_path / "briefs",
        seed_id_to_uuid=None,
    )

    assert len(paths) == 1
    # Without the UUID map seed-side stamps are silent no-ops.
    assert _seed_intel_first_brief_at(uuid) is None


# --- 2. Idempotence -----------------------------------------------

def test_deliver_intel_stamp_is_idempotent(
    isolated_db, tmp_path: Path
):
    """A second cite of the same entry_id does NOT overwrite the stamp."""
    _insert_intel_entry(7)

    synthesizer.deliver(
        [_make_concept([7], name="first")],
        briefs_dir=tmp_path / "briefs",
        seed_id_to_uuid={},
    )
    first_stamp = _intel_first_brief_at(7)
    assert first_stamp is not None

    # Sleep is unnecessary; the UPDATE ... WHERE col IS NULL gate
    # makes the second call a no-op regardless of clock advance.
    synthesizer.deliver(
        [_make_concept([7], name="second")],
        briefs_dir=tmp_path / "briefs",
        seed_id_to_uuid={},
    )

    assert _intel_first_brief_at(7) == first_stamp


def test_deliver_seed_stamp_is_idempotent(
    isolated_db, tmp_path: Path
):
    """A second cite of the same curated_post does NOT overwrite the stamp."""
    uuid = _insert_curated_post(isolated_db)
    seed_id = inventory_view.SEED_ID_OFFSET + 0

    synthesizer.deliver(
        [_make_concept([seed_id], name="first")],
        briefs_dir=tmp_path / "briefs",
        seed_id_to_uuid={seed_id: uuid},
    )
    first_stamp = _seed_intel_first_brief_at(uuid)
    assert first_stamp is not None

    synthesizer.deliver(
        [_make_concept([seed_id], name="second")],
        briefs_dir=tmp_path / "briefs",
        seed_id_to_uuid={seed_id: uuid},
    )

    assert _seed_intel_first_brief_at(uuid) == first_stamp


def test_deliver_non_integer_entry_ids_are_skipped(
    isolated_db, tmp_path: Path
):
    """Garbage entry_id values (None, str) get skipped, don't crash."""
    _insert_intel_entry(11)

    concept = _make_concept([11])
    concept["entry_ids_combined"] = [11, None, "abc", 11.5]  # mixed garbage

    paths = synthesizer.deliver(
        [concept],
        briefs_dir=tmp_path / "briefs",
        seed_id_to_uuid={},
    )

    assert len(paths) == 1
    # 11 still stamped; the garbage didn't crash the loop.
    assert _intel_first_brief_at(11) is not None


# --- 3. today_curated_seeds projection ----------------------------

def test_today_curated_seeds_projects_synthetic_ids(isolated_db):
    """Seeds get synthetic entry_ids starting at SEED_ID_OFFSET + 0."""
    uuid_a = _insert_curated_post(isolated_db, title="First")
    uuid_b = _insert_curated_post(isolated_db, title="Second")

    seeds = inventory_view.today_curated_seeds(days=1)

    assert len(seeds) == 2
    entry_ids = [s["entry_id"] for s in seeds]
    # IDs start at SEED_ID_OFFSET and are contiguous; ordering depends
    # on curated_at DESC but the offset+idx contract holds.
    assert sorted(entry_ids) == [
        inventory_view.SEED_ID_OFFSET,
        inventory_view.SEED_ID_OFFSET + 1,
    ]
    uuids = {s["_curated_post_id"] for s in seeds}
    assert uuids == {uuid_a, uuid_b}


def test_today_curated_seeds_skips_drafts(isolated_db):
    """Only status='published' rows seed (drafts stay private)."""
    _insert_curated_post(isolated_db, status="draft", title="A draft")
    _insert_curated_post(isolated_db, status="published", title="A live post")

    seeds = inventory_view.today_curated_seeds(days=1)

    assert len(seeds) == 1
    assert seeds[0]["title"] == "A live post"


def test_today_curated_seeds_respects_window(isolated_db):
    """Posts curated outside the window do not seed."""
    # Old post — curated 3 days ago, outside the 1-day window.
    _insert_curated_post(
        isolated_db,
        title="Old",
        curated_at=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
    )
    # Recent post — curated now.
    _insert_curated_post(isolated_db, title="Recent")

    seeds = inventory_view.today_curated_seeds(days=1)

    assert [s["title"] for s in seeds] == ["Recent"]


def test_today_curated_seeds_uses_commentary_when_present(isolated_db):
    """summary field maps to curator_commentary when available."""
    _insert_curated_post(isolated_db, title="With commentary")

    seeds = inventory_view.today_curated_seeds(days=1)
    assert len(seeds) == 1
    # _insert_curated_post sets curator_commentary="Curator commentary for this post."
    assert seeds[0]["summary"] == "Curator commentary for this post."
    # Raw article summary lands in technical_detail.
    assert seeds[0]["technical_detail"] == "A summary of the article body."
    assert seeds[0]["entry_type"] == "curated_post"


# --- 4. Channel-separation smoke -----------------------------------

def test_render_bluesky_is_short_and_link_only():
    """Bluesky path stays in its channel: short, ends with the link.

    Channel-separation contract (migration §5e):
      * Bluesky post is short (<= max_chars budget) and links qrater.org
      * No full brief bodies, no daily-text multi-section formatting
    """
    payload = {
        "tldr": [
            "IBM Heron achieves ~1e-3 two-qubit error on new chip [#1207].",
            "Preprint claims VQE convergence improvement on ground states.",
        ],
        "implications": [
            "Marginal shift vs prior corpus; no methodology change.",
        ],
        "attention": [],
        "tags": ["hardware", "vqe"],
        "window": {"n_today": 2, "n_prior": 100},
    }

    line = daily_summary.render_bluesky(payload, max_chars=280)

    assert len(line) <= 280
    assert "qrater.org" in line
    # Multi-section text formatting must NOT leak into the Bluesky post.
    assert "TL;DR" not in line
    assert "Implications" not in line
    assert "Worth attention" not in line
    # Lead bullet text appears (possibly truncated).
    assert "IBM Heron" in line or "qrater.org" in line


def test_render_bluesky_unavailable_payload_returns_short_fallback():
    """Empty/None payload → short fallback string with the link only."""
    fallback = daily_summary.render_bluesky({})
    assert "qrater.org" in fallback
    assert len(fallback) <= 280
    assert "TL;DR" not in fallback


def test_render_text_is_multisection_digest():
    """Plaintext path stays in its channel: multi-section digest.

    Channel-separation contract: render_text is the email / stdout
    fallback. It includes TL;DR, Implications, Attention, Tags — but
    NOT a single-line link CTA (that's the Bluesky channel).
    """
    payload = {
        "tldr": ["Headline development today."],
        "implications": ["This refines the prior picture."],
        "attention": ["Verify the cited preprint's methodology."],
        "tags": ["hardware"],
        "window": {"n_today": 1, "n_prior": 50},
    }

    text = daily_summary.render_text(payload)

    assert "TL;DR" in text
    assert "Implications vs prior" in text
    assert "Worth attention" in text
    assert "Tags:" in text
    assert "(window: 1 new, 50 prior)" in text
    # The full-text channel must NOT carry the Bluesky CTA link by default.
    assert "qrater.org" not in text


# --- 5. Citation validation ---------------------------------------
#
# The synth prompt requires "Each concept MUST combine at least 2
# distinct entry_ids from the inventory." Live runs have observed the
# LLM citing entry_ids that don't exist in either today's seed batch
# or the historical inventory — same hallucination root cause as the
# daily_summary [#2000007] bug. _validate_concept_citations() strips
# bogus IDs and drops concepts that fall below the 2-ID floor.


def test_validate_concept_citations_passes_all_valid():
    concept = _make_concept([1, 2, 3])
    kept, counts = synthesizer._validate_concept_citations([concept], {1, 2, 3})
    assert len(kept) == 1
    assert kept[0]["entry_ids_combined"] == [1, 2, 3]
    assert counts["stripped_ids"] == 0
    assert counts["dropped_concepts"] == 0


def test_validate_concept_citations_strips_invalid_ids():
    concept = _make_concept([1, 9999, 2, 8888])
    kept, counts = synthesizer._validate_concept_citations([concept], {1, 2})
    assert len(kept) == 1
    assert kept[0]["entry_ids_combined"] == [1, 2]
    assert counts["stripped_ids"] == 2
    assert counts["dropped_concepts"] == 0


def test_validate_concept_citations_drops_concept_below_two_ids():
    """Concept whose surviving valid IDs < 2 must be dropped entirely."""
    concept = _make_concept([1, 9999, 8888])
    kept, counts = synthesizer._validate_concept_citations([concept], {1, 2, 3})
    assert kept == []
    assert counts["stripped_ids"] == 2
    assert counts["dropped_concepts"] == 1


def test_validate_concept_citations_reproduces_seed_hallucination():
    """The actual failure mode: synth cites a high seed ID we never handed it.

    Mirrors the 2026-06-10 daily_summary [#2000007] case in the synth's
    integer-list shape. valid_ids spans SEED_ID_OFFSET..+4; the LLM
    cites +7. The bogus ID is stripped; if the remaining IDs still meet
    the 2-ID floor the concept survives.
    """
    SEED = inventory_view.SEED_ID_OFFSET
    valid = {SEED + 0, SEED + 1, SEED + 2, SEED + 3, SEED + 4}
    concept = _make_concept([SEED + 0, SEED + 7, SEED + 1])
    kept, counts = synthesizer._validate_concept_citations([concept], valid)
    assert len(kept) == 1
    assert SEED + 7 not in kept[0]["entry_ids_combined"]
    assert kept[0]["entry_ids_combined"] == [SEED + 0, SEED + 1]
    assert counts["stripped_ids"] == 1


def test_validate_concept_citations_dedupes_and_handles_garbage():
    """Duplicate IDs collapse; non-integer values count as stripped."""
    concept = _make_concept([1, "abc", 1, None, 2, 2.5])
    kept, counts = synthesizer._validate_concept_citations([concept], {1, 2})
    assert len(kept) == 1
    # 1 kept once (dedup), 2 kept once, the rest stripped or deduped.
    assert kept[0]["entry_ids_combined"] == [1, 2]
    # "abc" + None = 2 non-int strips. 2.5 coerces via int() to 2, which
    # is in valid_ids and already seen, so it dedupes silently (not a
    # strip). Duplicate 1 also dedupes, not strips.
    assert counts["stripped_ids"] == 2


def test_validate_concept_citations_handles_empty_concepts_list():
    kept, counts = synthesizer._validate_concept_citations([], {1, 2})
    assert kept == []
    assert counts == {"stripped_ids": 0, "dropped_concepts": 0, "kept_concepts": 0}


def test_validate_concept_citations_preserves_other_fields():
    """Filtering entry_ids_combined must not mutate other concept fields."""
    concept = _make_concept([1, 9999, 2], name="cross-domain-A")
    concept["combination_insight"] = "Specific insight here."
    kept, _ = synthesizer._validate_concept_citations([concept], {1, 2})
    assert kept[0]["product_name"] == "cross-domain-A"
    assert kept[0]["combination_insight"] == "Specific insight here."
    assert kept[0]["confidence"] == 0.9
    # Source concept is not mutated in-place.
    assert concept["entry_ids_combined"] == [1, 9999, 2]


def test_no_new_content_payload_is_deterministic_and_channel_safe():
    """Quiet-day payload renders sanely on both channels with no LLM call.

    Pins the Phase 5d _no_new_content_payload contract: the four
    required keys are present and typed as lists, so render_text and
    render_bluesky both produce non-empty, channel-appropriate output
    even on a zero-curated-posts day.
    """
    payload = daily_summary._no_new_content_payload(prior_count=1216)

    for key in ("tldr", "implications", "attention", "tags"):
        assert isinstance(payload[key], list)
    assert payload["window"] == {"n_today": 0, "n_prior": 1216}

    text = daily_summary.render_text(payload)
    assert "No new curated posts" in text

    line = daily_summary.render_bluesky(payload)
    assert "qrater.org" in line
    assert len(line) <= 280
