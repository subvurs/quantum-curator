"""Read-side helpers over the ``quantum_intel_entries`` table.

The synthesizer / daily_summary / emailer modules used to consume
``inventory.json`` directly. Post-migration the same data lives in
SQLite (Phase 1d wrote 1216 entries + 38 dedup sentinels there). This
module reconstitutes the JSON shape callers expect, so the existing
prompt-builders don't need to be rewritten around SQL rows.

Stable surface
--------------
``load_inventory()``      → list[dict]  (all entries, newest first)
``today_entries(days=1)`` → list[dict]  (entries from the last N days)
``mark_first_brief_at`` (entry_id, ts) updates the per-entry
``first_brief_at`` column iff currently NULL — gives synthesizer a
DB-backed "this entry was used in a brief" timestamp without needing
to scan the filesystem on every run.

JSON shape
----------
The dict matches what ``inventory.json`` carried, minus the audit
columns Curator added (``imported_from``, ``created_at``,
``subvurs_impact_report``):

    entry_id, fingerprint, title, source, url, date_collected,
    date_published, entry_type, summary, technical_detail,
    enabling_capabilities (list), domain_tags (list), maturity,
    subvurs_impact_score, subvurs_impact_version, first_brief_at
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db


_LIST_COLS = ("enabling_capabilities", "domain_tags")


def _row_to_dict(row: Any) -> dict[str, Any]:
    """sqlite3.Row → JSON-shaped inventory dict."""
    d = dict(row)
    # Decode list-typed JSON columns; tolerate legacy NULLs / bad blobs
    # by falling back to [] rather than crashing the synth prompt.
    for col in _LIST_COLS:
        raw = d.get(col)
        if raw in (None, ""):
            d[col] = []
            continue
        try:
            d[col] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            d[col] = []
    return d


def load_inventory() -> list[dict]:
    """Return every entry in quantum_intel_entries, newest entry_id first."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT entry_id, fingerprint, title, source, url,
                   date_collected, date_published, entry_type,
                   summary, technical_detail,
                   enabling_capabilities, domain_tags, maturity,
                   subvurs_impact_score, subvurs_impact_version,
                   first_brief_at
            FROM quantum_intel_entries
            ORDER BY entry_id DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def today_entries(days: int = 1) -> list[dict]:
    """Entries with ``date_collected`` within the last ``days`` days.

    ``date_collected`` was stored verbatim from Intel's inventory.json,
    which uses ISO-8601 UTC strings (``YYYY-MM-DDTHH:MM:SS+00:00``).
    String comparison is correct for that format.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT entry_id, fingerprint, title, source, url,
                   date_collected, date_published, entry_type,
                   summary, technical_detail,
                   enabling_capabilities, domain_tags, maturity,
                   subvurs_impact_score, subvurs_impact_version,
                   first_brief_at
            FROM quantum_intel_entries
            WHERE date_collected >= ?
            ORDER BY entry_id DESC
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def entries_by_ids(entry_ids: list[int]) -> list[dict]:
    """Look up entries by entry_id (preserves caller-supplied ordering)."""
    if not entry_ids:
        return []
    placeholders = ",".join("?" * len(entry_ids))
    conn = db.get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT entry_id, fingerprint, title, source, url,
                   date_collected, date_published, entry_type,
                   summary, technical_detail,
                   enabling_capabilities, domain_tags, maturity,
                   subvurs_impact_score, subvurs_impact_version,
                   first_brief_at
            FROM quantum_intel_entries
            WHERE entry_id IN ({placeholders})
            """,
            entry_ids,
        ).fetchall()
    finally:
        conn.close()
    by_id = {r["entry_id"]: _row_to_dict(r) for r in rows}
    return [by_id[i] for i in entry_ids if i in by_id]


def mark_first_brief_at(entry_id: int, ts: str | None = None) -> bool:
    """Set ``first_brief_at`` on the entry iff currently NULL.

    Returns True if the row was updated, False if it was already set
    (i.e. this entry was cited in an earlier brief) or doesn't exist.
    """
    ts = ts or datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE quantum_intel_entries
               SET first_brief_at = ?
             WHERE entry_id = ?
               AND first_brief_at IS NULL
            """,
            (ts, entry_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()
