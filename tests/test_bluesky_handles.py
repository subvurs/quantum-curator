"""Tests for ``quantum_curator.bluesky_handles`` allowlist + matcher.

Covers:
  * YAML load → list[HandleEntry]
  * Whole-word case-insensitive alias matching
  * Byte-offset correctness over multi-byte UTF-8 characters
  * Longest-alias-first overlap resolution
  * Source attribution opt-in via ``attribute_source`` flag
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from quantum_curator import bluesky_handles
from quantum_curator.bluesky_handles import (
    HandleEntry,
    find_mentions_in_text,
    find_source_attribution,
    load_handles,
    reset_caches,
)


@pytest.fixture
def fixture_yaml(tmp_path: Path) -> Path:
    """A small fixture YAML wired up via load_handles(str(path))."""
    path = tmp_path / "handles.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "handles": [
                    {
                        "handle": "ibm.bsky.social",
                        "aliases": ["IBM", "IBM Quantum", "IBM Research"],
                        "source_names": ["Qiskit Blog (IBM)"],
                        "attribute_source": True,
                    },
                    {
                        "handle": "google.bsky.social",
                        "aliases": ["Google Quantum AI", "Google"],
                        "source_names": ["Google Research Blog"],
                        "attribute_source": True,
                    },
                    {
                        "handle": "rigetti.bsky.social",
                        "aliases": ["Rigetti"],
                        "source_names": ["Rigetti Blog"],
                        "attribute_source": False,  # explicit opt-out
                    },
                ]
            }
        )
    )
    return path


@pytest.fixture(autouse=True)
def _reset_caches():
    """Each test starts with empty caches."""
    reset_caches()
    yield
    reset_caches()


# ---------- load_handles ----------


def test_load_handles_parses_yaml(fixture_yaml: Path):
    entries = load_handles(str(fixture_yaml))
    assert len(entries) == 3
    assert all(isinstance(e, HandleEntry) for e in entries)
    assert entries[0].handle == "ibm.bsky.social"
    assert "IBM Quantum" in entries[0].aliases
    assert entries[0].attribute_source is True
    assert entries[2].attribute_source is False


def test_load_handles_missing_file_returns_empty(tmp_path: Path):
    missing = tmp_path / "does_not_exist.yaml"
    assert load_handles(str(missing)) == []


def test_load_handles_default_path_resolves_to_packaged_yaml():
    # Resets clear the cache so this load actually reads the file.
    entries = load_handles()
    assert isinstance(entries, list)
    # The shipped YAML has at least the IBM + Google rows.
    handles = {e.handle for e in entries}
    assert "ibm.bsky.social" in handles
    assert "google.bsky.social" in handles


# ---------- find_mentions_in_text ----------


def test_find_mentions_exact_alias_match(fixture_yaml: Path, monkeypatch):
    monkeypatch.setattr(
        bluesky_handles,
        "_DEFAULT_YAML_PATH",
        fixture_yaml,
    )
    reset_caches()
    hits = find_mentions_in_text("IBM unveils new processor today.")
    assert len(hits) == 1
    s, e, h = hits[0]
    assert h == "ibm.bsky.social"
    assert "IBM unveils new processor today.".encode("utf-8")[s:e] == b"IBM"


def test_find_mentions_case_insensitive(fixture_yaml: Path, monkeypatch):
    monkeypatch.setattr(bluesky_handles, "_DEFAULT_YAML_PATH", fixture_yaml)
    reset_caches()
    hits = find_mentions_in_text("ibm posted results")
    assert len(hits) == 1
    assert hits[0][2] == "ibm.bsky.social"


def test_find_mentions_word_boundary(fixture_yaml: Path, monkeypatch):
    """`IBMer` should NOT match the `IBM` alias."""
    monkeypatch.setattr(bluesky_handles, "_DEFAULT_YAML_PATH", fixture_yaml)
    reset_caches()
    hits = find_mentions_in_text("An IBMer wrote about this")
    assert hits == []


def test_find_mentions_longest_first_overlap_resolution(
    fixture_yaml: Path, monkeypatch
):
    """`Google Quantum AI` should win over `Google` on overlap."""
    monkeypatch.setattr(bluesky_handles, "_DEFAULT_YAML_PATH", fixture_yaml)
    reset_caches()
    hits = find_mentions_in_text("Google Quantum AI announced something.")
    # Only one mention, not two (Google would also match).
    assert len(hits) == 1
    s, e, h = hits[0]
    assert h == "google.bsky.social"
    text = "Google Quantum AI announced something."
    assert text.encode("utf-8")[s:e].decode("utf-8") == "Google Quantum AI"


def test_find_mentions_byte_offsets_multibyte_utf8(
    fixture_yaml: Path, monkeypatch
):
    """Em dash (U+2014, 3 UTF-8 bytes) before alias keeps byte offsets correct."""
    monkeypatch.setattr(bluesky_handles, "_DEFAULT_YAML_PATH", fixture_yaml)
    reset_caches()
    # "A—IBM" — em dash takes 3 bytes in UTF-8
    text = "A—IBM ships chip"
    hits = find_mentions_in_text(text)
    assert len(hits) == 1
    s, e, h = hits[0]
    assert h == "ibm.bsky.social"
    assert text.encode("utf-8")[s:e] == b"IBM"


def test_find_mentions_multiple_distinct_aliases(
    fixture_yaml: Path, monkeypatch
):
    monkeypatch.setattr(bluesky_handles, "_DEFAULT_YAML_PATH", fixture_yaml)
    reset_caches()
    hits = find_mentions_in_text("IBM and Google collaborated.")
    handles = {h for _, _, h in hits}
    assert handles == {"ibm.bsky.social", "google.bsky.social"}


def test_find_mentions_empty_text():
    assert find_mentions_in_text("") == []


def test_find_mentions_sorted_by_byte_start(
    fixture_yaml: Path, monkeypatch
):
    """Results come back in byte_start order regardless of pattern order."""
    monkeypatch.setattr(bluesky_handles, "_DEFAULT_YAML_PATH", fixture_yaml)
    reset_caches()
    hits = find_mentions_in_text("Google then IBM then Rigetti.")
    starts = [s for s, _, _ in hits]
    assert starts == sorted(starts)


# ---------- find_source_attribution ----------


def test_source_attribution_returns_handle(
    fixture_yaml: Path, monkeypatch
):
    monkeypatch.setattr(bluesky_handles, "_DEFAULT_YAML_PATH", fixture_yaml)
    reset_caches()
    assert find_source_attribution("Qiskit Blog (IBM)") == "ibm.bsky.social"
    assert find_source_attribution("Google Research Blog") == "google.bsky.social"


def test_source_attribution_opt_out(fixture_yaml: Path, monkeypatch):
    """attribute_source=false → None even on matching source_name."""
    monkeypatch.setattr(bluesky_handles, "_DEFAULT_YAML_PATH", fixture_yaml)
    reset_caches()
    # Rigetti row has attribute_source=False
    assert find_source_attribution("Rigetti Blog") is None


def test_source_attribution_unknown_returns_none(
    fixture_yaml: Path, monkeypatch
):
    monkeypatch.setattr(bluesky_handles, "_DEFAULT_YAML_PATH", fixture_yaml)
    reset_caches()
    assert find_source_attribution("Unknown Source") is None
    assert find_source_attribution("") is None
