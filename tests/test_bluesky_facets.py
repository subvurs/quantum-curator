"""Tests for tag/mention/attribution facet builders in bluesky.py.

Covers:
  * `_build_tag_facets` — one facet per #word, tag value excludes '#'
  * Byte offsets match `text[i:j].encode("utf-8")` exactly
  * `_build_mention_facets` — DID resolution stub + dedup against
    `exclude_spans`
  * `_build_attribution_facet` — covers only @handle portion (skips "via ")
  * `_maybe_append_attribution` — budget-aware suffix
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quantum_curator import bluesky as bsky_module
from quantum_curator import bluesky_handles
from quantum_curator.bluesky import (
    _build_attribution_facet,
    _build_mention_facets,
    _build_tag_facets,
    _byte_offset,
    _maybe_append_attribution,
)
from quantum_curator.bluesky_handles import reset_caches


@pytest.fixture(autouse=True)
def _clear_did_cache():
    bsky_module._DID_CACHE.clear()
    reset_caches()
    yield
    bsky_module._DID_CACHE.clear()
    reset_caches()


@pytest.fixture
def fake_did_resolver(monkeypatch):
    """Stub `_resolve_handle` to deterministic DIDs without HTTP."""
    mapping = {
        "ibm.bsky.social": "did:plc:ibm-test",
        "google.bsky.social": "did:plc:google-test",
        "quantinuum.bsky.social": "did:plc:quantinuum-test",
        "ionq.bsky.social": "did:plc:ionq-test",
        "microsoft.bsky.social": "did:plc:microsoft-test",
        "aws.bsky.social": "did:plc:aws-test",
    }

    def fake(client, handle):
        return mapping.get(handle)

    monkeypatch.setattr(bsky_module, "_resolve_handle", fake)
    return mapping


# ---------- _build_tag_facets ----------


def test_tag_facets_one_per_hashtag():
    text = "#A #B #C"
    facets = _build_tag_facets(text)
    assert len(facets) == 3


def test_tag_facet_excludes_hash_from_tag_value():
    text = "Hello #QuantumHardware world"
    facets = _build_tag_facets(text)
    assert len(facets) == 1
    f = facets[0]
    assert f["features"][0]["$type"] == "app.bsky.richtext.facet#tag"
    assert f["features"][0]["tag"] == "QuantumHardware"
    assert "#" not in f["features"][0]["tag"]


def test_tag_facets_byte_offsets_correct():
    text = "Look at #QuantumHardware right here"
    facets = _build_tag_facets(text)
    f = facets[0]
    s = f["index"]["byteStart"]
    e = f["index"]["byteEnd"]
    assert text.encode("utf-8")[s:e].decode("utf-8") == "#QuantumHardware"


def test_tag_facets_byte_offsets_with_multibyte_prefix():
    """An em dash (3 UTF-8 bytes) before the hashtag shifts offsets."""
    text = "A—#Tag1 #Tag2"
    facets = _build_tag_facets(text)
    # Tag1 starts after "A—" which is 1 + 3 = 4 bytes
    assert len(facets) == 2
    for f in facets:
        s = f["index"]["byteStart"]
        e = f["index"]["byteEnd"]
        sub = text.encode("utf-8")[s:e].decode("utf-8")
        assert sub.startswith("#")


def test_tag_facets_no_hashtag_returns_empty():
    assert _build_tag_facets("No hashtags here") == []


# ---------- _build_mention_facets ----------


def test_mention_facets_built_for_known_aliases(fake_did_resolver):
    client = MagicMock()
    text = "IBM and Google announced new partnerships."
    facets = _build_mention_facets(client, text)
    dids = {f["features"][0]["did"] for f in facets}
    assert "did:plc:ibm-test" in dids
    assert "did:plc:google-test" in dids


def test_mention_facets_skipped_when_did_resolution_fails(monkeypatch):
    monkeypatch.setattr(bsky_module, "_resolve_handle", lambda c, h: None)
    client = MagicMock()
    text = "IBM announced something today."
    facets = _build_mention_facets(client, text)
    assert facets == []


def test_mention_facets_dedupe_overlapping_aliases(fake_did_resolver):
    """`Google Quantum AI` doesn't also fire a separate `Google` facet."""
    client = MagicMock()
    text = "Google Quantum AI announced new processor"
    facets = _build_mention_facets(client, text)
    # Only one facet expected on the longer-match span.
    assert len(facets) == 1
    assert facets[0]["features"][0]["did"] == "did:plc:google-test"


def test_mention_facets_respect_exclude_spans(fake_did_resolver):
    """`exclude_spans` blocks emission of facets on those byte ranges."""
    client = MagicMock()
    text = "IBM announced something"
    # Compute the byte span of "IBM"
    s = _byte_offset(text, 0)
    e = _byte_offset(text, len("IBM"))
    facets = _build_mention_facets(client, text, exclude_spans={(s, e)})
    assert facets == []


# ---------- _build_attribution_facet ----------


def test_attribution_facet_covers_only_at_handle_portion(fake_did_resolver):
    client = MagicMock()
    text = "Title here\n\nvia @ibm.bsky.social"
    facet, span = _build_attribution_facet(client, text)
    assert facet is not None
    assert span is not None
    s, e = span
    # The facet must cover exactly "@ibm.bsky.social", not "via @..."
    sub = text.encode("utf-8")[s:e].decode("utf-8")
    assert sub == "@ibm.bsky.social"
    assert facet["features"][0]["did"] == "did:plc:ibm-test"


def test_attribution_facet_none_when_no_via_suffix(fake_did_resolver):
    client = MagicMock()
    text = "No attribution here"
    facet, span = _build_attribution_facet(client, text)
    assert facet is None
    assert span is None


def test_attribution_facet_none_when_did_fails(monkeypatch):
    monkeypatch.setattr(bsky_module, "_resolve_handle", lambda c, h: None)
    client = MagicMock()
    text = "Title\n\nvia @nobody.bsky.social"
    facet, span = _build_attribution_facet(client, text)
    assert facet is None
    assert span is None


# ---------- _maybe_append_attribution ----------


def test_attribution_appended_when_known_source_and_budget():
    text = "Short title"
    out = _maybe_append_attribution(text, "Qiskit Blog (IBM)", max_chars=300)
    assert out.endswith("\nvia @ibm.bsky.social")


def test_attribution_skipped_when_unknown_source():
    text = "Short title"
    out = _maybe_append_attribution(text, "Some Random Blog", max_chars=300)
    assert out == text
    assert "via @" not in out


def test_attribution_skipped_when_no_budget():
    # Title fills nearly all 300 chars; suffix would overflow.
    text = "X" * 295
    out = _maybe_append_attribution(text, "Qiskit Blog (IBM)", max_chars=300)
    assert out == text
    assert "via @" not in out
