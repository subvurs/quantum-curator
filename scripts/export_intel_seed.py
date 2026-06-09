#!/usr/bin/env python3
"""Export quantum_intel_entries + quantum_intel_dedup to a gzipped seed file.

Run this locally any time the canonical archive grows (today: 1216
entries, 38 dedup-only sentinels — frozen at the Jun 2026 Phase 1d
import). The output ships with the package so CI gets the historical
corpus on first ``quantum-curator init`` instead of operating against
an empty quantum_intel_entries table.

Output: ``quantum_curator/intel/_seed_data/seed_inventory.json.gz``

Schema (post-gzip JSON):
    {
      "exported_at": ISO-8601 UTC,
      "source_db": str,
      "entries": [
        {entry_id, fingerprint, title, source, url, date_collected,
         date_published, entry_type, summary, technical_detail,
         enabling_capabilities, domain_tags, maturity,
         subvurs_impact_score, subvurs_impact_report,
         subvurs_impact_version},
        ...
      ],
      "dedup": [
        {fingerprint, first_seen},
        ...
      ]
    }

Excluded from export:
* created_at — set by the DB on INSERT
* imported_from — regenerated at import-time ("seed_inventory.json.gz")
* first_brief_at — anti-recurrence state belongs to the running DB, not
  the seed (seeds are a clean starting point; CI starts every brief
  uncited)

Usage:
    python scripts/export_intel_seed.py
    python scripts/export_intel_seed.py --db /path/to/curator.db --out /path/out.json.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "curator.db"
DEFAULT_OUT = (
    REPO_ROOT
    / "quantum_curator"
    / "intel"
    / "_seed_data"
    / "seed_inventory.json.gz"
)


def export_seed(db_path: Path, out_path: Path) -> dict[str, int]:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        entry_rows = conn.execute(
            """
            SELECT entry_id, fingerprint, title, source, url,
                   date_collected, date_published, entry_type,
                   summary, technical_detail,
                   enabling_capabilities, domain_tags, maturity,
                   subvurs_impact_score, subvurs_impact_report,
                   subvurs_impact_version
              FROM quantum_intel_entries
             ORDER BY entry_id ASC
            """
        ).fetchall()

        dedup_rows = conn.execute(
            """
            SELECT fingerprint, first_seen
              FROM quantum_intel_dedup
             ORDER BY fingerprint ASC
            """
        ).fetchall()
    finally:
        conn.close()

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(db_path),
        "entries": [dict(r) for r in entry_rows],
        "dedup": [dict(r) for r in dedup_rows],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    with gzip.open(out_path, "wb", compresslevel=9) as f:
        f.write(raw)

    return {
        "entries": len(entry_rows),
        "dedup": len(dedup_rows),
        "raw_bytes": len(raw),
        "gz_bytes": out_path.stat().st_size,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="Source SQLite DB")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output .json.gz")
    args = p.parse_args()

    print(f"  db:  {args.db}")
    print(f"  out: {args.out}")
    counts = export_seed(args.db, args.out)
    print(f"  exported entries={counts['entries']} dedup={counts['dedup']}")
    print(
        f"  size: raw={counts['raw_bytes']:,} B / gz={counts['gz_bytes']:,} B "
        f"({100 * counts['gz_bytes'] / counts['raw_bytes']:.1f}%)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
