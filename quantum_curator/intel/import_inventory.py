"""One-time importer: Quantum Intel inventory.json → Curator SQLite.

Source files (read-only):
  ~/Library/Application Support/quantum_intel/inventory.json
  ~/Library/Application Support/quantum_intel/dedup_index.json

Target tables (in Curator's SQLite, created by db.init_db()):
  quantum_intel_entries     — full cataloged records, entry_id preserved
  quantum_intel_dedup       — dedup-only fingerprint sentinels

Design notes
------------
* Idempotent. Re-running is a no-op: ``INSERT OR IGNORE`` on the
  fingerprint UNIQUE constraint for entries, and on the fingerprint
  PRIMARY KEY for dedup-only sentinels.
* entry_id is preserved verbatim from Intel's inventory.json so that
  any historical brief that cites "entry_id=N" stays resolvable, and
  so that future synthesize calls keep numbering contiguous
  (next id = max(entry_id) + 1).
* The 9 entries that carry the recently-added Stage 2.5 fields
  (``subvurs_impact_score``, ``subvurs_impact_paths``,
  ``subvurs_impact_evidence``, ``subvurs_impact_fail_reason``,
  ``subvurs_impact_version``) get those folded into the table:
  - subvurs_impact_score → subvurs_impact_score (REAL)
  - subvurs_impact_version → subvurs_impact_version (TEXT)
  - paths + evidence + fail_reason → subvurs_impact_report (JSON)
* The single entry with the ``recataloged`` flag is imported with
  that flag preserved inside the ``imported_from`` audit string —
  we don't add a dedicated column for a one-off marker.
* Backup of inventory.json is taken before any DB write, named
  ``inventory.json.preimport.bak.<TS>`` in the Intel data dir.

CLI
---
    python -m quantum_curator.intel.import_inventory
    python -m quantum_curator.intel.import_inventory --dry-run
    python -m quantum_curator.intel.import_inventory --intel-dir /custom/path
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from .. import db


DEFAULT_INTEL_DIR = Path("/Users/mvm/Library/Application Support/quantum_intel")


def _backup_inventory(intel_dir: Path) -> Path:
    """Snapshot inventory.json before any DB write."""
    src = intel_dir / "inventory.json"
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = intel_dir / f"inventory.json.preimport.bak.{ts}"
    shutil.copy2(src, dst)
    return dst


def _build_impact_report(entry: dict[str, Any]) -> str | None:
    """Fold paths + evidence + fail_reason into one JSON blob.

    Returns None if the entry was never scored, so the column stays
    NULL (consistent with curated_posts.subvurs_impact_report
    semantics).
    """
    keys = ("subvurs_impact_paths", "subvurs_impact_evidence", "subvurs_impact_fail_reason")
    if not any(k in entry for k in keys):
        return None
    return json.dumps(
        {
            "paths": entry.get("subvurs_impact_paths"),
            "evidence": entry.get("subvurs_impact_evidence"),
            "fail_reason": entry.get("subvurs_impact_fail_reason"),
        },
        ensure_ascii=False,
    )


def _imported_from(entry: dict[str, Any]) -> str:
    parts = ["inventory.json"]
    if entry.get("recataloged"):
        parts.append("recataloged=true")
    return ";".join(parts)


def import_inventory(intel_dir: Path = DEFAULT_INTEL_DIR, *, dry_run: bool = False) -> dict[str, int]:
    """Run the import. Returns counts dict for caller logging."""
    inv_path = intel_dir / "inventory.json"
    ded_path = intel_dir / "dedup_index.json"

    if not inv_path.exists():
        raise FileNotFoundError(f"inventory.json not found at {inv_path}")
    if not ded_path.exists():
        raise FileNotFoundError(f"dedup_index.json not found at {ded_path}")

    inventory: list[dict[str, Any]] = json.loads(inv_path.read_text())
    dedup_index: dict[str, str] = json.loads(ded_path.read_text())

    # Inventory fingerprints — these go in quantum_intel_entries, NOT
    # the dedup-only table (the entries themselves are the dedup
    # signal). dedup_only_fps is the set difference.
    inv_fps = {e["fingerprint"] for e in inventory}
    dedup_only_fps = set(dedup_index.keys()) - inv_fps

    counts = {
        "inventory_total": len(inventory),
        "dedup_only_total": len(dedup_only_fps),
        "entries_inserted": 0,
        "entries_skipped_existing": 0,
        "dedup_inserted": 0,
        "dedup_skipped_existing": 0,
        "scored_carried": 0,
    }

    if dry_run:
        print(f"[dry-run] would import {counts['inventory_total']} inventory entries")
        print(f"[dry-run] would import {counts['dedup_only_total']} dedup-only fingerprints")
        print(f"[dry-run] would back up inventory.json (not done in dry-run)")
        return counts

    # Backup first — only after we've validated the source files load.
    backup_path = _backup_inventory(intel_dir)
    print(f"  Backed up inventory.json → {backup_path.name}")

    db.init_db()  # idempotent — creates new tables if missing
    conn = db.get_connection()
    try:
        cur = conn.cursor()

        # --- entries import ---
        for entry in inventory:
            impact_report = _build_impact_report(entry)
            if impact_report is not None:
                counts["scored_carried"] += 1

            cur.execute(
                """
                INSERT OR IGNORE INTO quantum_intel_entries (
                    entry_id, fingerprint, title, source, url,
                    date_collected, date_published, entry_type,
                    summary, technical_detail, enabling_capabilities,
                    domain_tags, maturity,
                    subvurs_impact_score, subvurs_impact_report, subvurs_impact_version,
                    imported_from
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(entry["entry_id"]),
                    entry["fingerprint"],
                    entry.get("title", ""),
                    entry.get("source", ""),
                    entry.get("url", ""),
                    entry.get("date_collected", ""),
                    entry.get("date_published", ""),
                    entry.get("type", ""),
                    entry.get("summary", ""),
                    entry.get("technical_detail", ""),
                    json.dumps(entry.get("enabling_capabilities", []), ensure_ascii=False),
                    json.dumps(entry.get("domain_tags", []), ensure_ascii=False),
                    entry.get("maturity", ""),
                    float(entry.get("subvurs_impact_score", 0.0)),
                    impact_report,
                    entry.get("subvurs_impact_version"),
                    _imported_from(entry),
                ),
            )
            if cur.rowcount == 1:
                counts["entries_inserted"] += 1
            else:
                counts["entries_skipped_existing"] += 1

        # --- dedup-only sentinels ---
        for fp in dedup_only_fps:
            first_seen = dedup_index.get(fp, "")
            cur.execute(
                """
                INSERT OR IGNORE INTO quantum_intel_dedup (
                    fingerprint, first_seen, imported_from
                ) VALUES (?, ?, ?)
                """,
                (fp, first_seen, "dedup_index.json"),
            )
            if cur.rowcount == 1:
                counts["dedup_inserted"] += 1
            else:
                counts["dedup_skipped_existing"] += 1

        conn.commit()
    finally:
        conn.close()

    return counts


def _verify(conn: sqlite3.Connection, intel_dir: Path) -> None:
    """Post-import sanity checks against the source files."""
    inv = json.loads((intel_dir / "inventory.json").read_text())
    ded = json.loads((intel_dir / "dedup_index.json").read_text())

    inv_fps = {e["fingerprint"] for e in inv}
    dedup_only_fps = set(ded.keys()) - inv_fps
    max_entry_id_src = max((int(e["entry_id"]) for e in inv), default=-1)

    entries_n = conn.execute("SELECT COUNT(*) FROM quantum_intel_entries").fetchone()[0]
    dedup_n = conn.execute("SELECT COUNT(*) FROM quantum_intel_dedup").fetchone()[0]
    max_entry_id_db = conn.execute("SELECT COALESCE(MAX(entry_id), -1) FROM quantum_intel_entries").fetchone()[0]
    scored_n = conn.execute(
        "SELECT COUNT(*) FROM quantum_intel_entries WHERE subvurs_impact_report IS NOT NULL"
    ).fetchone()[0]

    print("\nVerification:")
    print(f"  inventory.json entries:           {len(inv)}")
    print(f"  quantum_intel_entries rows:       {entries_n}")
    print(f"  dedup-only fingerprints (source): {len(dedup_only_fps)}")
    print(f"  quantum_intel_dedup rows:         {dedup_n}")
    print(f"  max(entry_id) source:             {max_entry_id_src}")
    print(f"  max(entry_id) db:                 {max_entry_id_db}")
    print(f"  scored (impact_report not NULL):  {scored_n}")

    ok = (
        entries_n >= len(inv)
        and dedup_n >= len(dedup_only_fps)
        and max_entry_id_db == max_entry_id_src
    )
    if ok:
        print("  STATUS: OK (counts match, entry_ids preserved)")
    else:
        print("  STATUS: MISMATCH — investigate before retiring inventory.json")
        sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--intel-dir",
        type=Path,
        default=DEFAULT_INTEL_DIR,
        help="Path to Quantum Intel data directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be imported without writing",
    )
    args = parser.parse_args()

    print(f"Quantum Intel → Curator inventory import")
    print(f"  intel_dir = {args.intel_dir}")
    counts = import_inventory(args.intel_dir, dry_run=args.dry_run)
    print("\nCounts:")
    for k, v in counts.items():
        print(f"  {k}: {v}")

    if not args.dry_run:
        conn = db.get_connection()
        try:
            _verify(conn, args.intel_dir)
        finally:
            conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
