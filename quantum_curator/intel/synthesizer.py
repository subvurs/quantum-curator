"""Combinatorial-product synthesizer (Stage 3 of the original Intel pipeline).

Port of ``synthesizer.synthesize`` from
``~/Library/Application Support/quantum_intel/synthesizer.py``,
re-pointed at Curator's SQLite-backed inventory and Curator's direct
Anthropic SDK call. Algorithmic shape is preserved verbatim — same
prompt, same context-window strategy (full-detail mode under
``INVENTORY_FULL_THRESHOLD``, otherwise stratified cluster sample),
same anti-recurrence directive, same confidence-floor filter.

Differences from the Intel original
-----------------------------------
* No multi-provider router. The Anthropic SDK is called sync inside
  a sync function — matches what ``curator.Curator._generate_commentary``
  already does. The .env-based ``pydantic-settings`` loader makes the
  API key reliably present, eliminating Intel's "ANTHROPIC_API_KEY not
  set" failure mode (entry_id=1215 in the historical inventory caught
  this live during Phase 1 verification).
* No EINTR-thread-deadline gymnastics. The Anthropic SDK has its own
  HTTP timeout and Curator never hits Ollama Cloud, so PEP 475 no
  longer applies. A simple ``max_retries=2`` on the SDK call is the
  whole timeout story.
* Inventory comes from ``quantum_intel_entries`` via ``inventory_view``,
  not ``inventory.json``.
* Briefs go to ``settings.data_dir / "intel_briefs"`` (gitignored).
* On successful brief generation, every cited entry's ``first_brief_at``
  is stamped in the DB (idempotent via ``mark_first_brief_at``).

Public surface
--------------
    synthesize(new_entries, model=...) -> list[dict]
        Run the synth LLM call; return viable concepts (confidence ≥ MIN).

    deliver(concepts, briefs_dir=...) -> list[Path]
        Render concepts as markdown files; stamp first_brief_at in DB.

    run_intel_synthesis(days=1) -> tuple[list[dict], list[Path]]
        One-shot: pull today's new entries + full inventory, synthesize,
        deliver. The CLI command is a thin wrapper over this.
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from ..config import get_settings
from . import inventory_view
from .brief_history import recent_brief_citations


# --- Tunables (kept in module-scope so the CLI can override per-run) ---

# Above this inventory size the full-detail prompt would blow the
# context window, so the prompt switches to per-domain stratified
# sampling. Intel's value, unchanged.
INVENTORY_FULL_THRESHOLD = 1500
MAX_BRIEFS_PER_RUN = 5
MIN_CONFIDENCE = 0.55
RECENT_BRIEF_LOOKBACK_DAYS = 14
SYNTH_TEMP = 0.7
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MODEL = "claude-sonnet-4-5"


# --- Prompts (verbatim from Intel synthesizer.py) ---

SYNTH_SYSTEM = (
    "You are a quantum technology commercialization strategist. "
    "You identify plausible commercial products that become possible only "
    "when two or more recent quantum discoveries are combined. Each concept "
    "must cite specific entry_ids from the inventory and stand on technical "
    "merit — not marketing language, not generic \"quantum improves X\" "
    "claims. Return results ONLY as valid JSON."
)

SYNTH_PROMPT = """\
# Quantum Technology Inventory

## Historical Inventory ({history_count} entries, grouped by domain)
{history_context}

## Today's New Entries ({today_count})
{todays_entries}

## Recently Cited Entry IDs (last {lookback_days} days)
{recent_cites}

# Task
Identify 1-{max_briefs} combinations of 2 or more discoveries from the \
inventory above that together enable a specific commercial product, \
service, or capability. Both the historical inventory and today's new \
entries are equally valid sources — the strongest pairings often come \
from re-reading older work in light of a recent result, not from \
combining two same-day entries.

A good combination is one where the value of combining is meaningfully \
greater than any single entry alone. Prefer combinations that span \
different domain_tags (cross-disciplinary pairings tend to be more \
valuable than same-domain ones).

Rules:
- Each concept MUST combine at least 2 distinct entry_ids from the inventory.
- At least one entry_id in each concept SHOULD come from the historical \
  inventory (i.e., not from today's new entries), unless the combination \
  is genuinely impossible without two same-day entries. Pure today×today \
  combinations are acceptable but should be the exception, not the rule.
- AVOID re-using the entry_ids listed under "Recently Cited" above unless \
  no plausible alternative exists. Recurring hub IDs produce echo-chamber \
  output. Reach further into the historical inventory for fresher pairings.
- No generic outputs ("quantum computing will improve X")
- No concepts achievable by a single entry alone
- Self-assess confidence 0.0-1.0 honestly. Use 0.4-0.6 for "plausible but \
  uncertain," 0.6-0.8 for "clear technical path," and 0.8+ only when the \
  combination is near-term achievable or already demonstrated. Only \
  concepts with confidence >= 0.55 will be delivered.
- Return an empty list [] only if you genuinely cannot find any \
  cross-discovery combination worth considering.
- Maximum {max_briefs} concepts.

Return a JSON array of objects:
[
  {{
    "product_name": "short product name",
    "entry_ids_combined": [list of entry_id integers],
    "combination_insight": "why these discoveries together unlock something new",
    "target_market": "specific market segment",
    "value_proposition": "one sentence",
    "technical_approach": "2-3 sentences on how to build it",
    "competitive_moat": "what makes this defensible",
    "build_requirements": ["list of 3-5 requirements"],
    "risk_factors": ["list of 2-3 risks"],
    "first_three_steps": ["step 1", "step 2", "step 3"],
    "estimated_timeline": "X months / years",
    "confidence": 0.0-1.0
  }}
]

Return ONLY the JSON array."""


# --- Helpers (ported from Intel) ---


def _condense_entry(entry: dict) -> str:
    tags = ", ".join(entry.get("domain_tags", []))
    caps = "; ".join(entry.get("enabling_capabilities", [])[:2])
    return (
        f"[{entry.get('entry_id', '?')}] "
        f"{entry.get('summary', entry.get('title', 'untitled'))} "
        f"({entry.get('maturity', '?')}) [{tags}] — {caps}"
    )


def _cluster_by_domain(entries: list[dict]) -> dict[str, list[dict]]:
    clusters: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        tags = e.get("domain_tags", ["uncategorized"]) or ["uncategorized"]
        primary = tags[0] if tags else "uncategorized"
        clusters[primary].append(e)
    return dict(clusters)


def _stratified_cluster_sample(entries: list[dict], k: int = 3) -> list[dict]:
    """Newest + oldest + one deterministic middle pick.

    Same Intel mechanic for breaking the hub-recurrence pattern; seed is
    derived from the cluster endpoints so the same inventory state
    produces the same prompt (debuggable).
    """
    n = len(entries)
    if n <= k:
        return list(entries)
    picks = [entries[-1], entries[0]]
    middle = entries[1:-1]
    if middle and k > 2:
        seed = (entries[0].get("entry_id") or 0) ^ (entries[-1].get("entry_id") or 0)
        rng = random.Random(seed)
        picks.extend(rng.sample(middle, min(k - 2, len(middle))))
    return picks


def _build_history_context(inventory: list[dict], today_ids: set[int]) -> str:
    historical = [e for e in inventory if e.get("entry_id") not in today_ids]
    if not historical:
        return "(No prior history — this is the first run.)"

    if len(historical) <= INVENTORY_FULL_THRESHOLD:
        clusters = _cluster_by_domain(historical)
        parts = []
        for domain in sorted(clusters.keys()):
            entries = sorted(clusters[domain], key=lambda e: e.get("entry_id", 0))
            count = len(entries)
            lines = [f"  - {_condense_entry(e)}" for e in entries]
            parts.append(f"### {domain} ({count} entries)\n" + "\n".join(lines))
        return "\n\n".join(parts)

    clusters = _cluster_by_domain(historical)
    parts = []
    for domain, entries in sorted(clusters.items(), key=lambda x: -len(x[1])):
        count = len(entries)
        maturities: dict[str, int] = defaultdict(int)
        for e in entries:
            maturities[e.get("maturity", "unknown")] += 1
        mat_str = ", ".join(f"{k}: {v}" for k, v in sorted(maturities.items()))
        sample = _stratified_cluster_sample(entries, k=3)
        examples = "\n".join(f"  - {_condense_entry(e)}" for e in sample)
        parts.append(f"### {domain} ({count} entries, {mat_str})\n{examples}")
    return "\n\n".join(parts)


# --- JSON extraction (small, robust) ---

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> Any:
    """Pull the first JSON array (preferred) or object from a model reply.

    Tolerant of preamble/postamble text the model occasionally emits
    despite "Return ONLY the JSON array" — Anthropic models obey ~99%
    of the time, but the failures are loud markdown fences.
    """
    text = text.strip()
    # Strip ```json fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_ARRAY_RE.search(text)
    if m:
        return json.loads(m.group(0))
    m = _JSON_OBJ_RE.search(text)
    if m:
        return json.loads(m.group(0))
    raise ValueError("No JSON array or object found in model reply")


# --- Main entry point ---


def synthesize(
    new_entries: list[dict],
    inventory: list[dict] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    max_briefs: int = MAX_BRIEFS_PER_RUN,
    min_confidence: float = MIN_CONFIDENCE,
    temperature: float = SYNTH_TEMP,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    lookback_days: int = RECENT_BRIEF_LOOKBACK_DAYS,
    briefs_dir: Path | None = None,
) -> list[dict]:
    """Run combinatorial synthesis over today's entries + full history.

    Returns a list of concept dicts whose self-reported confidence
    exceeds ``min_confidence``. Returns ``[]`` (never raises) on any
    LLM failure, empty input, or unparseable JSON — same fail-closed
    posture as the Intel original.
    """
    if not new_entries:
        return []

    settings = get_settings()
    if not settings.has_anthropic:
        print("[intel.synthesize] anthropic_api_key not set — skipping")
        return []

    briefs_dir = briefs_dir or (settings.data_dir / "intel_briefs")
    inventory = inventory if inventory is not None else inventory_view.load_inventory()

    today_ids = {e.get("entry_id") for e in new_entries}
    todays_text = "\n".join(_condense_entry(e) for e in new_entries)
    history_text = _build_history_context(inventory, today_ids)

    cites = recent_brief_citations(briefs_dir, lookback_days=lookback_days)
    if cites:
        ranked = sorted(cites.items(), key=lambda kv: (-kv[1], kv[0]))[:30]
        recent_cites_text = ", ".join(f"{eid} ({n}x)" for eid, n in ranked)
    else:
        recent_cites_text = "(none — first run or no recent briefs)"

    history_count = sum(1 for e in inventory if e.get("entry_id") not in today_ids)
    prompt = SYNTH_PROMPT.format(
        todays_entries=todays_text,
        today_count=len(new_entries),
        history_context=history_text,
        history_count=history_count,
        recent_cites=recent_cites_text,
        lookback_days=lookback_days,
        max_briefs=max_briefs,
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=2)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=SYNTH_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 — Anthropic SDK raises a wide tree; fail-closed
        print(f"[intel.synthesize] LLM call failed: {exc}")
        return []

    raw = response.content[0].text if response.content else ""
    try:
        concepts = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"[intel.synthesize] could not parse JSON reply: {exc}")
        return []

    if isinstance(concepts, dict):
        concepts = [concepts]
    elif not isinstance(concepts, list):
        print(f"[intel.synthesize] expected list, got {type(concepts).__name__}")
        return []

    viable = [
        c for c in concepts
        if isinstance(c, dict) and float(c.get("confidence", 0)) >= min_confidence
    ]
    viable = viable[:max_briefs]
    return viable


# --- Markdown rendering + delivery ---


def _format_brief(concept: dict) -> str:
    lines = [
        f"# {concept.get('product_name', 'Untitled Concept')}",
        "",
        f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Confidence**: {concept.get('confidence', 'N/A')}",
        "",
        "## Discoveries Combined",
        f"Entry IDs: {concept.get('entry_ids_combined', [])}",
        "",
        "## Combination Insight",
        concept.get("combination_insight", ""),
        "",
        "## Target Market",
        concept.get("target_market", ""),
        "",
        "## Value Proposition",
        concept.get("value_proposition", ""),
        "",
        "## Technical Approach",
        concept.get("technical_approach", ""),
        "",
        "## Competitive Moat",
        concept.get("competitive_moat", ""),
        "",
        "## Build Requirements",
    ]
    for req in concept.get("build_requirements", []):
        lines.append(f"- {req}")
    lines += ["", "## Risk Factors"]
    for risk in concept.get("risk_factors", []):
        lines.append(f"- {risk}")
    lines += ["", "## First Three Steps"]
    for i, step in enumerate(concept.get("first_three_steps", []), 1):
        lines.append(f"{i}. {step}")
    lines += [
        "",
        "## Estimated Timeline",
        concept.get("estimated_timeline", "TBD"),
        "",
    ]
    return "\n".join(lines)


def deliver(concepts: list[dict], briefs_dir: Path | None = None) -> list[Path]:
    """Write briefs to disk and stamp ``first_brief_at`` on cited entries.

    Returns the list of paths written. No-op (returns ``[]``) if
    ``concepts`` is empty.
    """
    if not concepts:
        return []

    settings = get_settings()
    briefs_dir = briefs_dir or (settings.data_dir / "intel_briefs")
    briefs_dir.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat()
    written: list[Path] = []
    for concept in concepts:
        name = (concept.get("product_name") or "concept").lower()
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        path = briefs_dir / f"{ts}_{safe_name}.md"
        path.write_text(_format_brief(concept))
        written.append(path)

        # Stamp first_brief_at on every cited entry that hasn't been
        # cited before. UPDATE ... WHERE first_brief_at IS NULL gives us
        # idempotence — repeat citations are silent no-ops.
        for eid in concept.get("entry_ids_combined", []):
            try:
                inventory_view.mark_first_brief_at(int(eid), now_iso)
            except (TypeError, ValueError):
                continue

    return written


def run_intel_synthesis(days: int = 1, **kwargs: Any) -> tuple[list[dict], list[Path]]:
    """One-shot: today's entries → synthesize → deliver.

    ``days`` controls the "today" window over ``date_collected``.
    Keyword args are forwarded to ``synthesize`` (model, max_briefs, …).
    """
    new = inventory_view.today_entries(days=days)
    if not new:
        print(f"[intel.synth] no entries in the last {days}d — nothing to synthesize")
        return [], []
    inventory = inventory_view.load_inventory()
    concepts = synthesize(new, inventory=inventory, **kwargs)
    paths = deliver(concepts)
    return concepts, paths
