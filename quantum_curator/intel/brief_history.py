"""Anti-recurrence helper: how often has each entry been cited recently?

Port of Intel's ``brief_history.py``, kept structurally identical so the
synth prompt's "Recently Cited Entry IDs" block reads the same way it
always did. Disk-scan rather than DB-backed because:

* Brief files are the canonical record of what was *delivered* — a
  brief that was generated but failed to render won't be in the dir,
  which is the right semantics for "did Mark see this entry recently?"
* The ``first_brief_at`` column tracks *first* citation (lifetime), not
  the rolling N-day window the prompt wants.

If briefs ever stop being written to disk, replace this with a
``quantum_intel_brief_citations(entry_id, brief_path, cited_at)`` query.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


_FILENAME_RE = re.compile(r"^(\d{8})_\d{4}_")
_ENTRY_IDS_RE = re.compile(r"Entry IDs:\s*\[([^\]]*)\]")


def _parse_brief_date(path: Path) -> datetime | None:
    m = _FILENAME_RE.match(path.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_entry_ids(text: str) -> list[int]:
    m = _ENTRY_IDS_RE.search(text)
    if not m:
        return []
    out: list[int] = []
    for tok in m.group(1).split(","):
        tok = tok.strip()
        if tok.lstrip("-").isdigit():
            out.append(int(tok))
    return out


def recent_brief_citations(briefs_dir: Path, lookback_days: int = 14) -> Counter:
    """Counter mapping entry_id → times cited in briefs of the last N days.

    Returns an empty Counter on first run / missing dir / unreadable files.
    Never raises — this is best-effort context for the synth prompt.
    """
    counter: Counter = Counter()
    if not briefs_dir.exists():
        return counter

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    for path in briefs_dir.glob("*.md"):
        d = _parse_brief_date(path)
        if d is None or d < cutoff:
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        for eid in _extract_entry_ids(text):
            counter[eid] += 1
    return counter
