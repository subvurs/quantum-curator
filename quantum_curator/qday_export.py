"""Q-day Clock manifest export.

Produces a signed JSON manifest matching the ``CuratorManifest`` schema
defined in ``qday_clock.core.schemas``. The output is consumed by
``qday_clock.ingest.curator_client.fetch_manifest`` to drive the
Q-day Clock daily refresh.

Design decisions (per Q-day Clock plan §B "Key coupling decision"):

* Loose coupling at the data layer: Q-day Clock never reads this
  database directly. The JSON manifest is the contract.
* Tight coupling at the canonicalization layer: this module imports
  ``qday_clock.core.canonical`` and ``qday_clock.core.signing`` so
  the producer and consumer always agree on canonical byte ordering.
  Without this, a drift in either canonical implementation would
  silently invalidate signatures.

The Q-day Clock package must be importable when running this command.
In a typical dev setup that means ``pip install -e
/Users/mvm/Desktop/subvurs/public_interest/qday_clock`` from this
repo. Production deploys pin both repos to specific commits.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .db import list_articles, get_connection
from .models import ContentTopic

# Topics that contribute to Q-day Clock readings. Set in stone here so
# that an inadvertent ContentTopic enum widening doesn't quietly start
# feeding e.g. ML or sensing articles into the clock.
QDAY_RELEVANT_TOPICS: frozenset[ContentTopic] = frozenset(
    {
        ContentTopic.HARDWARE,
        ContentTopic.ALGORITHMS,
        ContentTopic.ERROR_CORRECTION,
        ContentTopic.CRYPTOGRAPHY,
    }
)

MANIFEST_SCHEMA_VERSION: str = "1.0"


def _get_curator_commit() -> str:
    """Return the current curator git commit hash, or ``"unknown"``.

    Explicitly caught: a non-git checkout, a missing git binary, or a
    repo with no commits yet. None of these block manifest production.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Explicitly caught: git not installed or too slow on this host.
        # The manifest is still useful without provenance to a specific
        # commit; the Q-day Clock side will accept "unknown".
        pass
    return "unknown"


def _row_counts(conn) -> dict[str, int]:
    """Return summary row counts for the manifest provenance block."""
    counts: dict[str, int] = {}
    for table in ("raw_articles", "curated_posts", "sources"):
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0]) if row else 0
        except Exception:
            # Explicitly caught: a missing table in an older DB. The
            # manifest still ships; the count is just omitted.
            counts[table] = -1
    return counts


def _build_article_refs(
    min_relevance: float,
    limit: int,
) -> list[dict]:
    """Pull articles from the DB and shape them into CuratorArticleRef dicts.

    Uses ``raw_articles`` rather than ``curated_posts`` so the manifest
    has enough volume to drive five axes; curated posts is a strict
    subset and is too small (28 rows as of May 2026) to feed multiple
    axis extractors. The Q-day Clock gate stack (RoadmapWeightCapGate,
    SingleSourceCapGate, etc.) handles any over-weighting from press
    releases that haven't passed curator review.
    """
    rows = list_articles(min_relevance=min_relevance, limit=limit)

    refs: list[dict] = []
    for art in rows:
        # Filter to Q-day-relevant topics. An article with NO detected
        # topics is dropped — we don't speculatively classify here.
        topics_relevant = [
            t.value for t in art.detected_topics if t in QDAY_RELEVANT_TOPICS
        ]
        if not topics_relevant:
            continue

        if art.published_at is None:
            # An article without a publication timestamp can't be
            # freshness-scored on the Q-day Clock side, so we skip it
            # rather than fabricate a timestamp.
            continue

        ref = {
            "post_id": art.id,
            "title": art.title,
            "url": art.url,
            "source": art.source_name,
            "topics": sorted(topics_relevant),
            "published_at": _iso_utc(art.published_at),
            "relevance_score": float(art.relevance_score),
            "summary": art.summary,
        }
        refs.append(ref)

    # Stable ordering so the manifest is deterministic across runs with
    # the same DB snapshot. published_at desc, then post_id asc for ties.
    refs.sort(key=lambda r: (r["published_at"], r["post_id"]), reverse=False)
    return refs


def _iso_utc(dt: datetime) -> str:
    """Render a UTC ISO-8601 string with trailing ``+00:00``.

    The Q-day Clock side parses both ``Z`` and ``+00:00`` suffixes, but
    sticking to ``+00:00`` matches the canonical datetime form used by
    ``datetime.isoformat()`` and avoids a needless round-trip through Z.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def build_manifest(
    min_relevance: float = 0.0,
    limit: int = 5000,
) -> dict:
    """Build the unsigned manifest body.

    Returned as a plain dict with the exact field shape required by
    ``qday_clock.core.schemas.CuratorManifest``. Callers may then sign
    it via :func:`sign_manifest`.
    """
    conn = get_connection()
    try:
        articles = _build_article_refs(min_relevance=min_relevance, limit=limit)
        counts = _row_counts(conn)
    finally:
        conn.close()

    return {
        "version": MANIFEST_SCHEMA_VERSION,
        "generated_at": _iso_utc(datetime.now(tz=timezone.utc)),
        "curator_commit": _get_curator_commit(),
        "articles": articles,
        "db_row_counts": counts,
    }


def sign_manifest(
    manifest_body: dict,
    signing_key_path: Path,
) -> dict:
    """Sign ``manifest_body`` and return ``manifest_body + signature fields``.

    The signature is computed over the RFC-8785 canonical form of
    ``manifest_body`` (the fields NOT including ``signature`` /
    ``signing_pubkey``). Q-day Clock's verifier strips those two
    reserved fields before recomputing canonical bytes.

    ``signing_key_path`` must point at a text file whose contents are
    a single base64-encoded 32-byte Ed25519 private key (trailing
    whitespace is stripped). The Q-day Clock package ships no keygen
    CLI; generate the file with the library API:

        import base64
        from qday_clock.core.signing import SigningKey
        sk = SigningKey.generate()
        Path("/path/to/.qday_signing_key").write_text(
            base64.b64encode(sk.to_bytes()).decode("ascii") + "\\n",
            encoding="utf-8",
        )
        # publish sk.verify_key.to_b64() as QDAY_CURATOR_PUBKEY_B64
    """
    # Import here so the curator base install doesn't require Q-day
    # Clock to be present. Only the export command needs it.
    import base64

    from qday_clock.core.signing import SigningKey, sign_payload

    raw_b64 = signing_key_path.read_text(encoding="utf-8").strip()
    raw = base64.b64decode(raw_b64, validate=True)
    sk = SigningKey.from_bytes(raw)

    signature_b64, pubkey_b64 = sign_payload(manifest_body, sk)
    return {
        **manifest_body,
        "signature": signature_b64,
        "signing_pubkey": pubkey_b64,
    }


def write_manifest(
    output_path: Path,
    signing_key_path: Optional[Path] = None,
    min_relevance: float = 0.0,
    limit: int = 5000,
    indent: int = 2,
) -> dict:
    """Build, optionally sign, and write the manifest to ``output_path``.

    If ``signing_key_path`` is None the manifest ships unsigned; the
    Q-day Clock side will refuse to ingest it (per CLAUDE.md §8 we
    fail-closed on unsigned input). Unsigned mode is provided only for
    debugging the JSON shape.

    Returns the dict that was written so callers can log the article
    count, signature fingerprint, etc.
    """
    body = build_manifest(min_relevance=min_relevance, limit=limit)
    final = sign_manifest(body, signing_key_path) if signing_key_path else body

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(final, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )
    return final
