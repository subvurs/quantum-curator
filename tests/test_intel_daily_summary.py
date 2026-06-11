"""Tests for the daily_summary citation validator + render_bluesky packing.

Covers the two regressions surfaced by the 2026-06-10 Bluesky post:

  1. The summary LLM emitted ``[#2000007]`` — an entry_id that did not
     appear in either today's seed batch (2000000-2000004) or the
     historical archive (max ~1215). ``_validate_citations`` strips
     invalid tokens while preserving the surrounding prose; the
     ``_strip_invalid_citations`` primitive is also exercised directly.

  2. ``render_bluesky`` previously emitted only ``tldr[0]`` + tags +
     CTA at a 280-char cap. The new behavior packs as many full TL;DR
     bullets as fit in the 300-grapheme Bluesky budget and falls back
     to a truncated first bullet only when no full bullet fits.

These tests do not call the Anthropic API or hit the database.
"""

from __future__ import annotations

import pytest

from quantum_curator.intel.daily_summary import (
    _strip_invalid_citations,
    _validate_citations,
    render_bluesky,
    render_bluesky_thread,
)


# ---------- _strip_invalid_citations primitive ----------


def test_strip_keeps_valid_id():
    text = "Foo [#5] bar."
    out, kept, stripped = _strip_invalid_citations(text, {5, 10})
    assert out == "Foo [#5] bar."
    assert kept == 1
    assert stripped == 0


def test_strip_removes_invalid_id_and_collapses_space():
    text = "Foo bar [#9999] baz."
    out, kept, stripped = _strip_invalid_citations(text, {1, 2})
    assert out == "Foo bar baz."
    assert kept == 0
    assert stripped == 1


def test_strip_handles_multiple_tokens_per_string():
    text = "A [#1] then [#9999] last."
    out, kept, stripped = _strip_invalid_citations(text, {1})
    assert out == "A [#1] then last."
    assert kept == 1
    assert stripped == 1


def test_strip_removes_trailing_punctuation_artifact():
    # The token-then-period case should not leave " ." behind.
    text = "Important finding [#9999]."
    out, _, stripped = _strip_invalid_citations(text, {1})
    assert out == "Important finding."
    assert stripped == 1


def test_strip_fast_path_no_tokens():
    text = "No citations here at all."
    out, kept, stripped = _strip_invalid_citations(text, set())
    assert out == text
    assert kept == 0
    assert stripped == 0


def test_strip_reproduces_2m_offset_hallucination():
    """The actual 2026-06-10 failure mode.

    Today's ``today_curated_seeds()`` produced entries with IDs
    2000000..2000004 (SEED_ID_OFFSET = 2_000_000). The summary LLM
    cited ``[#2000007]`` — an ID that does not exist anywhere. The
    validator must strip the token, not preserve it.
    """
    valid_ids = {2_000_000, 2_000_001, 2_000_002, 2_000_003, 2_000_004}
    text = "Hardware demonstrated coherence improvement [#2000007] in lab tests."
    out, kept, stripped = _strip_invalid_citations(text, valid_ids)
    assert "[#2000007]" not in out
    assert kept == 0
    assert stripped == 1
    assert "coherence improvement" in out


# ---------- _validate_citations payload traversal ----------


def test_validate_scans_all_three_sections():
    payload = {
        "tldr": ["TL bullet with [#1] valid."],
        "implications": ["Imp bullet with [#9999] invalid."],
        "attention": ["Att bullet with [#2] valid."],
        "tags": ["x"],
    }
    cleaned, counts = _validate_citations(payload, {1, 2})
    assert "[#1]" in cleaned["tldr"][0]
    assert "[#9999]" not in cleaned["implications"][0]
    assert "[#2]" in cleaned["attention"][0]
    assert counts["kept"] == 2
    assert counts["stripped"] == 1


def test_validate_no_op_when_all_valid():
    payload = {
        "tldr": ["A [#1] B."],
        "implications": [],
        "attention": [],
        "tags": [],
    }
    cleaned, counts = _validate_citations(payload, {1})
    assert cleaned["tldr"][0] == "A [#1] B."
    assert counts["stripped"] == 0


def test_validate_handles_missing_keys_gracefully():
    payload = {"tldr": ["X [#9] Y."]}  # no implications / attention
    cleaned, counts = _validate_citations(payload, {1})
    assert "[#9]" not in cleaned["tldr"][0]
    assert counts["stripped"] == 1


# ---------- render_bluesky packing ----------


def test_render_bluesky_packs_multiple_short_bullets():
    payload = {
        "tldr": [
            "Bullet one short.",
            "Bullet two short.",
            "Bullet three short.",
        ],
        "tags": ["quantum"],
    }
    out = render_bluesky(payload)
    assert "Bullet one" in out
    assert "Bullet two" in out
    assert "Bullet three" in out
    assert "https://qrater.org" in out
    assert "#quantum" in out
    assert len(out) <= 300


def test_render_bluesky_falls_back_to_truncated_first_bullet():
    # 400-char bullet — cannot fit in 300-char budget.
    long_bullet = "x" * 400
    payload = {"tldr": [long_bullet], "tags": []}
    out = render_bluesky(payload)
    assert "https://qrater.org" in out
    assert "…" in out  # truncation marker
    assert len(out) <= 300


def test_render_bluesky_respects_300_char_budget():
    payload = {
        "tldr": ["B" * 50, "C" * 50, "D" * 50, "E" * 50],
        "tags": ["a", "b", "c"],
    }
    out = render_bluesky(payload)
    assert len(out) <= 300


def test_render_bluesky_empty_payload_safe():
    out = render_bluesky({})
    assert "qrater.org" in out


def test_render_bluesky_stops_packing_before_overflow():
    """When the next bullet would push us over budget, packing stops
    cleanly — we don't emit a partial bullet just because we could."""
    payload = {
        "tldr": ["A short bullet.", "X" * 280],
        "tags": [],
    }
    out = render_bluesky(payload)
    assert "A short bullet" in out
    # The 280-char second bullet must not appear in full.
    assert "X" * 280 not in out
    assert len(out) <= 300


# ---------- render_bluesky vs render_bluesky_thread byte-identity ----------


def test_render_bluesky_thread_short_path_byte_identical_to_render_bluesky():
    """For a payload that fits in a single 300-char post, the thread
    renderer's first (and only) element must match render_bluesky()
    byte-for-byte. This locks the byte-identity contract: the
    threading code path must not perturb the single-post output for
    the common short-payload case.
    """
    payload = {
        "tldr": ["Bullet one short.", "Bullet two short."],
        "implications": [],
        "attention": [],
        "tags": ["quantum"],
    }
    single = render_bluesky(payload)
    thread = render_bluesky_thread(payload, link="https://qrater.org")
    assert len(thread) == 1
    assert thread[0] == single
