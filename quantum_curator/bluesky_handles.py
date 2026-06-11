"""Bluesky handle allowlist loader + alias matcher.

Conservative whole-word matching, no fuzzy logic, no LLM extraction.
Trades coverage for precision — the failure mode of a missed mention
is silence; the failure mode of a wrong mention is spam.

Two public entry points:

  * ``find_mentions_in_text(text)`` -> list of (byte_start, byte_end,
    handle) tuples for every whole-word alias hit. Byte offsets are
    over the UTF-8 encoding of ``text``, which is the contract Bluesky
    facets require (graphemes are not used; offsets are bytes).

  * ``find_source_attribution(source_name)`` -> handle (or None) if the
    given source_name appears in some entry's ``source_names`` AND that
    entry has ``attribute_source: true``.

The YAML file is loaded once per process (via ``functools.lru_cache``)
and the compiled regex is cached alongside it. Tests can reset the
cache by calling ``load_handles.cache_clear()``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import yaml
from pydantic import BaseModel, Field


_DEFAULT_YAML_PATH = Path(__file__).parent / "data" / "bluesky_handles.yaml"


class HandleEntry(BaseModel):
    """One row of the handle allowlist."""

    handle: str
    aliases: List[str] = Field(default_factory=list)
    source_names: List[str] = Field(default_factory=list)
    attribute_source: bool = False


@lru_cache(maxsize=1)
def load_handles(yaml_path: Optional[str] = None) -> List[HandleEntry]:
    """Load + parse the handle allowlist. Cached per (resolved) path.

    Returns an empty list if the YAML is missing — callers degrade
    gracefully (no mentions, no attribution).
    """
    path = Path(yaml_path) if yaml_path else _DEFAULT_YAML_PATH
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        # Fail-closed: empty allowlist is safer than a partial parse.
        return []

    rows = doc.get("handles", []) or []
    entries: List[HandleEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            entries.append(HandleEntry(**row))
        except Exception:  # noqa: BLE001 — bad row → drop, keep parsing
            continue
    return entries


@lru_cache(maxsize=1)
def _compiled_alias_table() -> List[Tuple[re.Pattern[str], str]]:
    """Compile (pattern, handle) pairs once per process.

    Longest alias first so "Google Quantum AI" wins over "Google" on
    the overlapping prefix. Ties are broken by insertion order, which
    keeps the YAML order observable for debugging.
    """
    rows: List[Tuple[str, str]] = []
    for entry in load_handles():
        for alias in entry.aliases:
            if alias:
                rows.append((alias, entry.handle))
    # Longest alias first (stable sort preserves YAML order on ties).
    rows.sort(key=lambda r: -len(r[0]))
    return [
        (re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE), handle)
        for alias, handle in rows
    ]


def find_mentions_in_text(text: str) -> List[Tuple[int, int, str]]:
    """Return (byte_start, byte_end, handle) for each whole-word alias hit.

    Byte offsets are over the UTF-8 encoding of ``text`` (Bluesky facet
    contract). Case-insensitive whole-word match (``\\b`` boundaries +
    ``re.IGNORECASE``). Overlapping matches are resolved longest-first:
    if "Google Quantum AI" and "Google" both match at the same start,
    only the longer one is emitted.
    """
    if not text:
        return []

    out: List[Tuple[int, int, str]] = []
    occupied: List[Tuple[int, int]] = []  # char-offset spans already claimed

    def _overlaps(start: int, end: int) -> bool:
        for s, e in occupied:
            if start < e and end > s:
                return True
        return False

    # Cache the char->byte conversion across all matches in this text.
    # For each char index i, byte_offsets[i] = len(text[:i].encode("utf-8")).
    # Compute lazily — `text` may be short and ASCII-only.
    byte_prefix_cache: dict = {0: 0}

    def _byte_offset(char_idx: int) -> int:
        if char_idx in byte_prefix_cache:
            return byte_prefix_cache[char_idx]
        val = len(text[:char_idx].encode("utf-8"))
        byte_prefix_cache[char_idx] = val
        return val

    for pattern, handle in _compiled_alias_table():
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if _overlaps(start, end):
                continue
            occupied.append((start, end))
            out.append((_byte_offset(start), _byte_offset(end), handle))

    # Sort by byte_start so callers see deterministic order.
    out.sort(key=lambda r: r[0])
    return out


def find_source_attribution(source_name: str) -> Optional[str]:
    """Return handle if source_name maps to an attribute_source=true row.

    Matching is exact-equal on ``source_name`` (no normalization). The
    YAML stores source_names in the canonical form curator emits.
    """
    if not source_name:
        return None
    for entry in load_handles():
        if not entry.attribute_source:
            continue
        if source_name in entry.source_names:
            return entry.handle
    return None


def reset_caches() -> None:
    """Clear all in-process caches. For tests."""
    load_handles.cache_clear()
    _compiled_alias_table.cache_clear()
