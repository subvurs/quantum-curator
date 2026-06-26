"""Tests for render_bluesky_thread + threaded share_daily_summary.

Covers:
  * ``render_bluesky_thread`` — single-post fast path (byte-identical
    to ``render_bluesky``), overflow into 2-3 posts, link only on the
    last post, "(N/M)" position suffix on replies, 300-char budget.
  * ``share_daily_summary`` threading — reply chain has correct
    ``reply.root`` and ``reply.parent`` blocks, image embed on root
    only, per-post rows persisted to ``bluesky_thread_posts``.

These tests do not call the Bluesky API or hit the production DB —
the database calls are routed via a temporary path through
``BLUESKY_DB_PATH``.
"""

from __future__ import annotations

import sqlite3

import pytest

from quantum_curator import bluesky as bsky_module
from quantum_curator import config as config_module
from quantum_curator import db as db_module
from quantum_curator.bluesky_handles import reset_caches
from quantum_curator.intel.daily_summary import (
    render_bluesky,
    render_bluesky_thread,
)


# ---------- Fixtures ----------


@pytest.fixture
def short_payload() -> dict:
    """A payload that fits comfortably in a single 300-char post."""
    return {
        "tldr": ["IBM ships 1000-qubit chip."],
        "implications": [],
        "attention": [],
        "tags": ["hardware"],
    }


@pytest.fixture
def overflow_payload() -> dict:
    """A payload that overflows a single 300-char post."""
    return {
        "tldr": [
            "IBM ships 1000-qubit chip with improved coherence and fidelity gains across the entire array.",
            "Google demonstrates 99.9% gate fidelity on Willow processor.",
            "Quantinuum logical qubits cross break-even threshold for the first time.",
        ],
        "implications": [
            "Hardware progress outpacing 2024 roadmaps across vendors.",
            "Surface-code threshold within reach for IBM and Google.",
        ],
        "attention": [
            "Verify IBM benchmarks against published gate-error tables.",
            "Watch for Quantinuum follow-up paper in Q3.",
        ],
        "tags": ["hardware", "fidelity", "logical-qubits"],
    }


@pytest.fixture(autouse=True)
def _clear_caches():
    bsky_module._DID_CACHE.clear()
    reset_caches()
    yield
    bsky_module._DID_CACHE.clear()
    reset_caches()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Skip the real inter-post delay in the threaded share path.

    ``share_daily_summary`` sleeps ≥1 s before each reply so the root and
    reply land on distinct ``createdAt`` whole seconds (Bluesky collapses a
    same-second self-thread root out of the author feed). The delay is
    irrelevant to these structural assertions, so stub it to keep the suite
    fast.
    """
    monkeypatch.setattr(bsky_module.time, "sleep", lambda *_a, **_k: None)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Route DB writes through a tmp SQLite file via settings.data_dir."""
    # Re-point settings.data_dir at a tmp directory; database_path is
    # derived as data_dir / "curator.db".
    settings = config_module.get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db_module.init_db()
    yield str(tmp_path / "curator.db")


# ---------- render_bluesky_thread short path ----------


def test_render_thread_short_payload_single_post(short_payload):
    """Short payload (no implications, no attention) → length-1 list."""
    posts = render_bluesky_thread(short_payload, link="https://qrater.org")
    assert len(posts) == 1


def test_render_thread_short_payload_byte_identical_to_render_bluesky(
    short_payload,
):
    """Single-post fast path must match render_bluesky() byte-for-byte."""
    posts = render_bluesky_thread(short_payload, link="https://qrater.org")
    single = render_bluesky(short_payload)
    assert posts[0] == single


def test_render_thread_empty_payload_returns_single_fallback():
    posts = render_bluesky_thread({}, link="https://qrater.org")
    assert len(posts) == 1
    assert "https://qrater.org" in posts[0]


# ---------- render_bluesky_thread overflow path ----------


def test_render_thread_overflow_splits_into_multiple_posts(overflow_payload):
    posts = render_bluesky_thread(overflow_payload, link="https://qrater.org")
    assert len(posts) >= 2


def test_render_thread_each_post_under_300_chars(overflow_payload):
    posts = render_bluesky_thread(overflow_payload, link="https://qrater.org")
    for p in posts:
        assert len(p) <= 300, f"Post exceeds 300 chars: {len(p)} — {p!r}"


def test_render_thread_link_only_on_last_post(overflow_payload):
    posts = render_bluesky_thread(overflow_payload, link="https://qrater.org")
    assert len(posts) >= 2
    # Link must appear in the final post.
    assert "https://qrater.org" in posts[-1]
    # And not in any earlier post.
    for p in posts[:-1]:
        assert "https://qrater.org" not in p


def test_render_thread_position_suffix_on_replies(overflow_payload):
    """Posts 2..M should carry an (i/M) position tag."""
    posts = render_bluesky_thread(overflow_payload, link="https://qrater.org")
    if len(posts) == 1:
        pytest.skip("Overflow fixture did not produce a thread")
    M = len(posts)
    # First post has no position tag.
    for i, p in enumerate(posts[1:], start=2):
        assert f"({i}/{M})" in p


def test_render_thread_first_post_has_tldr_header(overflow_payload):
    posts = render_bluesky_thread(overflow_payload, link="https://qrater.org")
    assert posts[0].startswith("TL;DR")


# ---------- share_daily_summary threading ----------


def _make_sharer_with_mocked_api():
    """Build a BlueskySharer (or equivalent) with HTTP API mocked."""
    sharer = bsky_module.BlueskySharer()
    sharer._handle = "test.bsky.social"
    sharer._app_password = "test-app-password"
    sharer._session = {"accessJwt": "fake-jwt", "did": "did:plc:test"}
    return sharer


def test_share_daily_summary_thread_posts_reply_chain(
    overflow_payload, tmp_db, monkeypatch
):
    """Posts 2+ must include reply.root + reply.parent blocks."""
    sharer = _make_sharer_with_mocked_api()
    if not sharer.is_configured:
        pytest.skip("BlueskySharer not configured for tests")

    # Capture every createRecord call body.
    posted_bodies: list[dict] = []

    def fake_post_one(self, client, text, *, link=None, embed=None,
                     reply=None, return_cid=False):
        posted_bodies.append({"text": text, "embed": embed, "reply": reply})
        idx = len(posted_bodies)
        uri = f"at://did:plc:test/app.bsky.feed.post/{idx}"
        cid = f"bafy-test-{idx}"
        if return_cid:
            return (uri, cid)
        return uri

    monkeypatch.setattr(
        bsky_module.BlueskySharer, "_post_one", fake_post_one
    )
    monkeypatch.setattr(
        bsky_module.BlueskySharer, "_login", lambda self, c: True
    )

    ok = sharer.share_daily_summary(
        text="ignored when payload provided",
        link="https://qrater.org",
        summary_date="2026-06-11",
        payload=overflow_payload,
        thread=True,
    )
    assert ok is True

    # If renderer produced a thread, validate reply chain.
    if len(posted_bodies) > 1:
        # Root has no reply block.
        assert posted_bodies[0]["reply"] is None
        # Reply 1 points at root for both root and parent.
        r1 = posted_bodies[1]["reply"]
        assert r1 is not None
        assert r1["root"]["uri"] == "at://did:plc:test/app.bsky.feed.post/1"
        assert r1["parent"]["uri"] == "at://did:plc:test/app.bsky.feed.post/1"
        # If there's a 3rd post, parent walks forward to post 2 but root stays.
        if len(posted_bodies) > 2:
            r2 = posted_bodies[2]["reply"]
            assert r2 is not None
            assert r2["root"]["uri"] == "at://did:plc:test/app.bsky.feed.post/1"
            assert r2["parent"]["uri"] == "at://did:plc:test/app.bsky.feed.post/2"


def test_share_daily_summary_thread_image_embed_on_root_only(
    overflow_payload, tmp_db, monkeypatch
):
    """Image embed must be passed to the root post only."""
    sharer = _make_sharer_with_mocked_api()
    if not sharer.is_configured:
        pytest.skip("BlueskySharer not configured for tests")

    posted_embeds: list[dict | None] = []

    def fake_post_one(self, client, text, *, link=None, embed=None,
                     reply=None, return_cid=False):
        posted_embeds.append(embed)
        idx = len(posted_embeds)
        if return_cid:
            return (f"at://test/{idx}", f"cid-{idx}")
        return f"at://test/{idx}"

    monkeypatch.setattr(
        bsky_module.BlueskySharer, "_post_one", fake_post_one
    )
    monkeypatch.setattr(
        bsky_module.BlueskySharer, "_login", lambda self, c: True
    )
    # Stub the image-blob upload so we can pass image bytes through.
    monkeypatch.setattr(
        bsky_module.BlueskySharer,
        "_upload_image_blob",
        lambda self, c, b, mime="image/png": {"$type": "blob", "ref": "x"},
    )

    fake_image = b"fake-png-bytes"
    ok = sharer.share_daily_summary(
        text="ignored",
        link="https://qrater.org",
        summary_date="2026-06-11",
        payload=overflow_payload,
        thread=True,
        image_bytes=fake_image,
        image_alt="test alt",
    )
    assert ok is True

    if len(posted_embeds) > 1:
        # Root has an embed.
        assert posted_embeds[0] is not None
        # Replies do not.
        for e in posted_embeds[1:]:
            assert e is None


def test_share_daily_summary_thread_persists_to_db(
    overflow_payload, tmp_db, monkeypatch
):
    """Threaded share must persist per-post rows to bluesky_thread_posts."""
    sharer = _make_sharer_with_mocked_api()
    if not sharer.is_configured:
        pytest.skip("BlueskySharer not configured for tests")

    posted_bodies: list[dict] = []

    def fake_post_one(self, client, text, *, link=None, embed=None,
                     reply=None, return_cid=False):
        posted_bodies.append({"text": text})
        idx = len(posted_bodies)
        uri = f"at://did:plc:test/post/{idx}"
        cid = f"cid-{idx}"
        if return_cid:
            return (uri, cid)
        return uri

    monkeypatch.setattr(
        bsky_module.BlueskySharer, "_post_one", fake_post_one
    )
    monkeypatch.setattr(
        bsky_module.BlueskySharer, "_login", lambda self, c: True
    )

    ok = sharer.share_daily_summary(
        text="ignored",
        link="https://qrater.org",
        summary_date="2026-06-12",
        payload=overflow_payload,
        thread=True,
    )
    assert ok is True

    # Only proceed with DB assertions if a thread was actually created.
    if len(posted_bodies) <= 1:
        pytest.skip("Renderer did not produce a thread for this payload")

    conn = sqlite3.connect(tmp_db)
    try:
        rows = conn.execute(
            "SELECT position, bsky_uri, post_text FROM bluesky_thread_posts "
            "WHERE summary_date = ? ORDER BY position",
            ("2026-06-12",),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == len(posted_bodies)
    # Positions are 0..N-1.
    assert [r[0] for r in rows] == list(range(len(rows)))

    # And bluesky_daily_summaries.is_thread == 1.
    conn = sqlite3.connect(tmp_db)
    try:
        is_thread = conn.execute(
            "SELECT is_thread FROM bluesky_daily_summaries WHERE summary_date = ?",
            ("2026-06-12",),
        ).fetchone()
    finally:
        conn.close()
    assert is_thread is not None
    assert is_thread[0] == 1


def test_share_daily_summary_no_thread_flag_uses_single_post(
    overflow_payload, tmp_db, monkeypatch
):
    """thread=False forces the single-post path even with payload."""
    sharer = _make_sharer_with_mocked_api()
    if not sharer.is_configured:
        pytest.skip("BlueskySharer not configured for tests")

    call_count = 0

    def fake_post_one(self, client, text, *, link=None, embed=None,
                     reply=None, return_cid=False):
        nonlocal call_count
        call_count += 1
        uri = f"at://test/{call_count}"
        cid = f"cid-{call_count}"
        if return_cid:
            return (uri, cid)
        return uri

    monkeypatch.setattr(
        bsky_module.BlueskySharer, "_post_one", fake_post_one
    )
    monkeypatch.setattr(
        bsky_module.BlueskySharer, "_login", lambda self, c: True
    )

    ok = sharer.share_daily_summary(
        text="Short text here",
        link="https://qrater.org",
        summary_date="2026-06-13",
        payload=overflow_payload,
        thread=False,
    )
    assert ok is True
    # thread=False → only one post regardless of payload.
    assert call_count == 1
