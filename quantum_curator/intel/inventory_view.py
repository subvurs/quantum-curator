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

# Phase 5a: curated_posts seeds get synthetic int entry_ids in a high
# range so they cannot collide with quantum_intel_entries (max 1215
# at Phase 1d import; ceiling grows as Intel-format entries accrete).
# IDs above this offset reference curated_posts by their offset; the
# synthesizer's mark_first_brief_at call must NOT try to write them
# back into quantum_intel_entries (Phase 5c will add the parallel
# intel_first_brief_at column on curated_posts).
SEED_ID_OFFSET = 2_000_000


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


def today_curated_seeds(days: int = 1) -> list[dict]:
    """Today's curated_posts projected into InventoryEntry shape.

    Phase 5 / Plan B: the synthesizer's "today's new entries" used to
    come from quantum_intel_entries.date_collected, but Phase 1d was a
    one-shot import — nothing populates new rows daily. The same daily
    intake that already feeds Quantum Crier + Qrater is the right
    source for "today" — those are the articles Curator just curated.

    Mapping (curated_posts → InventoryEntry shape):
        entry_id          = SEED_ID_OFFSET + index_in_returned_list
        fingerprint       = original_url
        title             = title
        source            = source_name
        url               = original_url
        date_collected    = curated_at          (when Curator published it)
        date_published    = published_at        (article's original date)
        entry_type        = "curated_post"      (new value; LLM ignores)
        summary           = curator_commentary  if present else summary
        technical_detail  = summary             (raw article summary)
        enabling_capabilities = []              (no analog; empty OK)
        domain_tags       = topics              (JSON list, already a list-typed col)
        maturity          = "unknown"           (no analog)
        subvurs_impact_score   = subvurs_impact_score
        subvurs_impact_version = subvurs_impact_version
        first_brief_at    = None  (5c will add intel_first_brief_at)
        _curated_post_id  = curated_posts.id    (UUID, for 5c routing)

    The "today" window filters on ``curated_at`` (the timestamp when
    Curator created the post), NOT ``published_at`` (which is the
    article's original publication date — can be months old for older
    arXiv papers re-surfaced by today's fetch). ``date_collected`` is
    the inventory analog of "this was new to us today" and now carries
    ``curated_at`` so downstream "today's entries" semantics work.

    Only ``status='published'`` posts are seeds — drafts don't go to
    the user-facing site so they shouldn't seed Intel either.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, title, original_url, summary, source_name,
                   published_at, curated_at, curator_commentary, topics,
                   subvurs_impact_score, subvurs_impact_version
              FROM curated_posts
             WHERE status = 'published'
               AND curated_at >= ?
             ORDER BY curated_at DESC
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    seeds: list[dict] = []
    for idx, row in enumerate(rows):
        topics_raw = row["topics"]
        try:
            topics_list = json.loads(topics_raw) if topics_raw else []
            if not isinstance(topics_list, list):
                topics_list = []
        except (json.JSONDecodeError, TypeError):
            topics_list = []

        commentary = row["curator_commentary"]
        summary_raw = row["summary"]
        seeds.append({
            "entry_id": SEED_ID_OFFSET + idx,
            "fingerprint": row["original_url"],
            "title": row["title"],
            "source": row["source_name"],
            "url": row["original_url"],
            "date_collected": row["curated_at"],
            "date_published": row["published_at"],
            "entry_type": "curated_post",
            "summary": commentary if commentary else summary_raw,
            "technical_detail": summary_raw or "",
            "enabling_capabilities": [],
            "domain_tags": topics_list,
            "maturity": "unknown",
            "subvurs_impact_score": row["subvurs_impact_score"],
            "subvurs_impact_version": row["subvurs_impact_version"],
            "first_brief_at": None,
            "_curated_post_id": row["id"],
        })
    return seeds


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


def mark_curated_seed_first_brief_at(
    curated_post_id: str, ts: str | None = None
) -> bool:
    """Set ``intel_first_brief_at`` on a curated_post iff currently NULL.

    Phase 5c parallel to ``mark_first_brief_at``. Keyed by curated_posts.id
    (UUID, str) rather than entry_id (int) because seed-side citations come
    from synthetic IDs (SEED_ID_OFFSET + idx) that don't map to any real
    quantum_intel_entries row. The synthesizer recovers the UUID via the
    ``seed_id_to_uuid`` map it builds from ``today_curated_seeds()``.

    Returns True if the row was updated, False if it was already set
    (this curated_post was cited in an earlier brief) or doesn't exist.
    """
    ts = ts or datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE curated_posts
               SET intel_first_brief_at = ?
             WHERE id = ?
               AND intel_first_brief_at IS NULL
            """,
            (ts, curated_post_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()
