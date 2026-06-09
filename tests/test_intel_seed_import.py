"""Tests for Phase 5g — bundled intel archive seed import.

The seed-import system ships the Phase 1d quantum_intel_entries
archive (1216 entries + 38 dedup-only sentinels) as a gzipped JSON
file inside the package. On every CI cache-miss / fresh clone, the
``quantum-curator init`` command calls ``import_seed_inventory()`` so
the synthesizer's historical co-source pass has rows to read against
today's curated_posts seeds.

What these tests pin:

  1. Empty-table seeding: when quantum_intel_entries is empty, the
     bundled .json.gz is imported in full. Counts match the seed
     payload (entries, dedup, scored rows).
  2. Idempotency on a populated table: when rows already exist, the
     call returns immediately without touching the DB. The cache-hit
     path in CI must not re-INSERT or duplicate rows.
  3. ``force=True`` overrides the empty-table check and re-runs the
     INSERT OR IGNORE for every row. With existing rows this is a
     no-op skip (every fingerprint already present), confirming the
     UNIQUE-constraint guard. Used for local re-seeding diagnostics.
  4. Missing seed file degrades gracefully: returns zero counts
     without raising. Older installs that pre-date the .json.gz must
     still ``init`` successfully.
  5. The synthesizer's ``inventory_view.load_inventory()`` returns the
     seeded rows in the same shape it used pre-Phase-5g (JSON-shaped
     dict with decoded list columns and entry_ids preserved).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quantum_curator import config, db
from quantum_curator.intel import inventory_view
from quantum_curator.intel.import_inventory import (
    SEED_INVENTORY_PATH,
    import_seed_inventory,
)


# --- Fixtures -----------------------------------------------------

@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh schema in a temp dir — same pattern as test_intel_synth."""
    config.get_settings.cache_clear()
    settings = config.get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db.init_db()
    yield tmp_path
    config.get_settings.cache_clear()


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- Tests --------------------------------------------------------

def test_seed_file_ships_with_package():
    """The .json.gz exists at the expected package-relative path.

    If this fails the export script wasn't re-run before commit, or
    the file got gitignored / wheel-excluded. Either way the CI path
    silently degrades to an empty archive — fail loudly here instead.
    """
    assert SEED_INVENTORY_PATH.exists(), (
        f"seed file missing at {SEED_INVENTORY_PATH}; "
        f"run scripts/export_intel_seed.py to regenerate"
    )
    assert SEED_INVENTORY_PATH.stat().st_size > 0


def test_seed_into_empty_table_populates_archive(isolated_db):
    """Empty quantum_intel_entries → full seed import on first call."""
    conn = db.get_connection()
    assert _count(conn, "quantum_intel_entries") == 0
    conn.close()

    counts = import_seed_inventory()

    assert counts["seed_present"] == 1
    assert counts["table_was_empty"] == 1
    assert counts["entries_inserted"] > 1000  # current archive is 1216
    assert counts["dedup_inserted"] > 0
    # 9 scored entries shipped with the Jun 2026 Phase 1d archive
    assert counts["scored_carried"] >= 1

    conn = db.get_connection()
    try:
        n_entries = _count(conn, "quantum_intel_entries")
        n_dedup = _count(conn, "quantum_intel_dedup")
        n_scored = conn.execute(
            "SELECT COUNT(*) FROM quantum_intel_entries "
            "WHERE subvurs_impact_report IS NOT NULL"
        ).fetchone()[0]
        max_id = conn.execute(
            "SELECT MAX(entry_id) FROM quantum_intel_entries"
        ).fetchone()[0]
    finally:
        conn.close()

    assert n_entries == counts["entries_inserted"]
    assert n_dedup == counts["dedup_inserted"]
    assert n_scored == counts["scored_carried"]
    # entry_id preservation: max_id must be n_entries - 1 (contiguous
    # 0..N-1 in the Phase 1d archive) so future cataloger inserts
    # continue numbering at max+1.
    assert max_id == n_entries - 1


def test_seed_is_idempotent_on_populated_table(isolated_db):
    """Populated table → call returns immediately without touching DB."""
    first = import_seed_inventory()
    assert first["entries_inserted"] > 0

    second = import_seed_inventory()

    assert second["table_was_empty"] == 0
    assert second["entries_inserted"] == 0
    assert second["entries_skipped_existing"] == 0
    assert second["dedup_inserted"] == 0

    # Row count must be unchanged across the second call.
    conn = db.get_connection()
    try:
        assert _count(conn, "quantum_intel_entries") == first["entries_inserted"]
        assert _count(conn, "quantum_intel_dedup") == first["dedup_inserted"]
    finally:
        conn.close()


def test_seed_force_replays_insert_or_ignore(isolated_db):
    """force=True re-runs the INSERT OR IGNORE; all rows skip as existing."""
    first = import_seed_inventory()
    assert first["entries_inserted"] > 0

    forced = import_seed_inventory(force=True)

    assert forced["table_was_empty"] == 1  # force bypasses the empty guard
    assert forced["entries_inserted"] == 0
    assert forced["entries_skipped_existing"] == first["entries_inserted"]
    assert forced["dedup_skipped_existing"] == first["dedup_inserted"]


def test_seed_missing_file_degrades_gracefully(isolated_db, tmp_path):
    """Missing seed file → zero counts, no exception, table stays empty."""
    bogus = tmp_path / "nonexistent_seed.json.gz"
    counts = import_seed_inventory(seed_path=bogus)

    assert counts["seed_present"] == 0
    assert counts["entries_inserted"] == 0
    assert counts["dedup_inserted"] == 0

    conn = db.get_connection()
    try:
        assert _count(conn, "quantum_intel_entries") == 0
    finally:
        conn.close()


def test_seeded_rows_are_visible_to_inventory_view(isolated_db):
    """The synthesizer's load_inventory() reads seeded rows in JSON shape."""
    import_seed_inventory()

    inv = inventory_view.load_inventory()
    assert len(inv) > 1000

    first = inv[0]
    # Schema contract: list-typed columns must come back as Python lists,
    # not raw JSON strings, for the synthesizer's _condense_entry().
    assert isinstance(first["enabling_capabilities"], list)
    assert isinstance(first["domain_tags"], list)
    assert isinstance(first["entry_id"], int)
    assert first["title"]
    assert first["source"]
