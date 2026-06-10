"""Tests for the Pillow-based daily-summary image card renderer.

Smoke tests that lock the basic shape — bytes returned, PNG magic
header, reasonable size, no exceptions on empty sections or long
bullets. Skipped cleanly if Pillow is not installed so the rest of
the test suite still runs on pillow-less envs.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PIL")

from quantum_curator.intel.image_card import render_summary_card


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _fixture_payload() -> dict:
    return {
        "tldr": [
            "IBM ships new 1000-qubit chip with improved coherence.",
            "Google demonstrates 99.9% gate fidelity on Willow.",
            "Quantinuum logical qubits cross break-even threshold.",
        ],
        "implications": [
            "Hardware progress is outpacing earlier roadmaps from 2024.",
            "Error rates approaching surface-code threshold across vendors.",
        ],
        "attention": [
            "Worth verifying the IBM benchmarks against published gate errors.",
        ],
        "tags": ["hardware", "fidelity", "logical-qubits"],
    }


def test_render_returns_png_bytes():
    out = render_summary_card(_fixture_payload(), "2026-06-10")
    assert isinstance(out, bytes)
    assert len(out) > 0
    assert out.startswith(PNG_MAGIC)


def test_render_size_under_1mb():
    """Bluesky's blob limit is 1MB; the card must stay safely below it."""
    out = render_summary_card(_fixture_payload(), "2026-06-10")
    assert len(out) < 1_000_000


def test_render_handles_empty_sections():
    """Empty implications / attention / tags should not raise."""
    payload = {
        "tldr": ["Only TL;DR today."],
        "implications": [],
        "attention": [],
        "tags": [],
    }
    out = render_summary_card(payload, "2026-06-10")
    assert out.startswith(PNG_MAGIC)


def test_render_handles_long_bullets():
    """Bullets wider than the canvas wrap rather than overflow horizontally.

    We can't easily assert the wrap visually, but we can assert the
    renderer doesn't crash and produces a valid PNG.
    """
    long_text = " ".join(["foobar"] * 60)  # ~360 chars, well past one line
    payload = {
        "tldr": [long_text],
        "implications": [long_text],
        "attention": [long_text],
        "tags": ["a"],
    }
    out = render_summary_card(payload, "2026-06-10")
    assert out.startswith(PNG_MAGIC)


def test_render_handles_completely_empty_payload():
    """No content at all still produces a valid (mostly empty) PNG."""
    out = render_summary_card({}, "2026-06-10")
    assert out.startswith(PNG_MAGIC)


def test_render_handles_missing_keys():
    """Payload with only one section key still renders."""
    payload = {"tldr": ["only this"]}
    out = render_summary_card(payload, "2026-06-10")
    assert out.startswith(PNG_MAGIC)
