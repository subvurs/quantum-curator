"""Daily Intel summary — TL;DR, implications-vs-prior, attention rec.

New in the migration (not present in the legacy Intel pipeline).
Migration doc decision D5: each daily run produces a structured
summary intended for (a) the Curator email body, (b) the qrater.org
front page, and (c) the truncated Bluesky link-post (Phase 3).

Dual data source (Phase 5d, Plan B pivot)
-----------------------------------------
The first live workflow run exposed that ``quantum_intel_entries`` is
a one-shot Phase 1d import (1216 historical rows, no daily refresh),
so "today's new entries" came up empty every run. Post-pivot:

* "Today" source     = ``curated_posts`` via ``today_curated_seeds()``
                       (same intake that drives Quantum Crier + Qrater).
* "Prior corpus"     = ``quantum_intel_entries`` via ``load_inventory()``
                       — historical context (the 1216 frozen rows).

The TL;DR is over today's curated_posts; "implications" cross-
references against the historical corpus. The "quiet day" branch
now correctly fires only when today's curated_posts window is empty
(NOT when quantum_intel_entries is empty, which is the steady state).

Goodhart guardrails
-------------------
The summary LLM call returns structured JSON with a fail-closed
contract:

* If any required key is missing → return ``None`` (caller renders an
  "AI summary unavailable" stub rather than a half-summary).
* If the model emits marketing language flagged in
  ``FORBIDDEN_PHRASES`` → the offending phrase is masked with ``[…]``
  before the summary is shown. This is a soft guard, not a kill — the
  rest of the structured payload is still useful even if a single
  bullet got over-eager.
* If today's window has zero new entries → no LLM call; we return a
  deterministic "no new content" payload so the email still ships.

This file calls the Anthropic SDK directly (same pattern as
``synthesizer.py`` and ``curator.py``).

Public surface
--------------
    build_daily_summary(new_entries, prior_entries=...) -> dict | None
        Returns a dict with keys:
          tldr: list[str]               # 3-5 bullets
          implications: list[str]       # 2-4 bullets — vs prior corpus
          attention: list[str]          # 1-3 bullets — what to look at
          tags: list[str]               # 1-5 short topic tags
          window: dict                  # bookkeeping: n_today, n_prior
        Or ``None`` on hard LLM failure.

        Defaults (when ``new_entries`` / ``prior_entries`` are None):
          new_entries   = today_curated_seeds(days=days)  (curated_posts)
          prior_entries = load_inventory()[:prior_limit]  (historical)
"""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic

from ..config import get_settings
from . import inventory_view
from .synthesizer import _condense_entry, _extract_json


# Marketing language we don't want bleeding into qrater.org / Bluesky.
# Soft-mask, not a kill — see module docstring.
FORBIDDEN_PHRASES = [
    "breakthrough",
    "revolutionary",
    "game-changing",
    "game changing",
    "world-first",
    "industry-leading",
    "groundbreaking",
    "paradigm shift",
]

REQUIRED_KEYS = ("tldr", "implications", "attention", "tags")


SUMMARY_SYSTEM = (
    "You are a quantum technology analyst summarizing one day of new "
    "intelligence for a working researcher. Be precise, technical, and "
    "calibrated. Distinguish proven results from preprints from "
    "company announcements. Never use marketing language. Return ONLY "
    "valid JSON matching the requested schema."
)

SUMMARY_PROMPT = """\
# Today's New Quantum Intel ({today_count} entries)
{todays_entries}

# Prior Corpus ({prior_count} entries, historical context, condensed)
{prior_entries}

# Task
Produce a calibrated daily summary as a single JSON object with these keys:

* "tldr" (3-5 strings): each one short bullet (<= 25 words) capturing a \
  distinct development from today. Lead with the most consequential. \
  Cite specific entry_ids in brackets, e.g. "[#1207]". If today has zero \
  novel content, return a single bullet that says so honestly.

* "implications" (2-4 strings): each one bullet (<= 35 words) on how \
  today's entries shift, confirm, or contradict patterns visible in the \
  prior historical corpus. If nothing in today's entries materially \
  changes the prior picture, say so explicitly (one bullet).

* "attention" (1-3 strings): each one bullet (<= 30 words) recommending \
  what the researcher should actually look at next. Be concrete \
  (entry_id, what to verify, why it matters). Empty list [] is valid \
  if nothing rises to that bar.

* "tags" (1-5 strings): short topic tags (lowercase, no #) summarizing \
  today's dominant themes. Use existing domain_tags where possible.

Rules:
- No marketing language ("breakthrough", "revolutionary", "paradigm \
  shift", etc.).
- Distinguish hardware demonstrations from simulations from theoretical \
  proposals when relevant.
- If you are uncertain about a claim, say "appears to" / "claims to" \
  rather than asserting.
- Return ONLY the JSON object (no markdown fences, no preamble).

Output schema:
{{
  "tldr": ["..."],
  "implications": ["..."],
  "attention": ["..."],
  "tags": ["..."]
}}
"""


def _condense_for_window(entry: dict) -> str:
    return _condense_entry(entry)


def _mask_forbidden(text: str) -> str:
    """Soft-mask marketing phrases. Case-insensitive whole-word match."""
    out = text
    for phrase in FORBIDDEN_PHRASES:
        out = re.sub(
            rf"\b{re.escape(phrase)}\b",
            "[…]",
            out,
            flags=re.IGNORECASE,
        )
    return out


def _scrub_payload(payload: dict) -> dict:
    """Apply forbidden-phrase mask to every string in tldr/implications/attention."""
    for key in ("tldr", "implications", "attention"):
        vals = payload.get(key, [])
        if isinstance(vals, list):
            payload[key] = [_mask_forbidden(str(v)) for v in vals]
    return payload


def _no_new_content_payload(prior_count: int) -> dict:
    """Deterministic payload for the "no new entries" case — no LLM call.

    Phase 5d: "no new entries" now means zero curated_posts in the
    last-N-day window (today_curated_seeds), NOT zero
    quantum_intel_entries (which is frozen at the Phase 1d import).
    """
    return {
        "tldr": ["No new curated posts to summarize in the last 24h."],
        "implications": [
            "Historical corpus has " + str(prior_count) + " entries; no shift today."
        ],
        "attention": [],
        "tags": ["quiet-day"],
        "window": {"n_today": 0, "n_prior": prior_count},
    }


def build_daily_summary(
    new_entries: list[dict] | None = None,
    prior_entries: list[dict] | None = None,
    *,
    model: str = "claude-sonnet-4-5",
    max_tokens: int = 1200,
    temperature: float = 0.3,
    days: int = 1,
    prior_days: int = 7,  # noqa: ARG001 — accepted for backward-compat, see below
    prior_limit: int = 100,
) -> dict | None:
    """Build today's structured Intel summary. Returns None on hard LLM failure.

    Phase 5d (Plan B pivot):
      * Default ``new_entries``   → today_curated_seeds(days=days)
                                    (curated_posts; same intake as Crier/Qrater)
      * Default ``prior_entries`` → most-recent ``prior_limit`` rows from
                                    load_inventory() (historical quantum_intel
                                    _entries, all 1216 frozen rows).
    The ``prior_days`` parameter is preserved in the signature for
    backward-compat with existing CLI callers (``intel-summary``,
    ``share-intel-summary``) but is no longer used: the historical corpus
    is static, not a moving window. We size the prior view by
    ``prior_limit`` (count) instead. Removing ``prior_days`` would break
    the three CLI commands that still pass it via ``click.option``.
    """
    settings = get_settings()
    if not settings.has_anthropic:
        print("[intel.daily_summary] anthropic_api_key not set — skipping")
        return None

    if new_entries is None:
        new_entries = inventory_view.today_curated_seeds(days=days)
    if prior_entries is None:
        # Historical corpus is static (Phase 1d frozen import). Take the
        # most-recent slice by entry_id DESC so the LLM sees the most
        # recently catalogued historical context first.
        historical = inventory_view.load_inventory()[:prior_limit]
        # Today's IDs cannot collide with historical entry_ids (seeds use
        # SEED_ID_OFFSET = 2_000_000+, historical max is ~1215), but keep
        # the defensive filter so a future ID-space change doesn't double
        # count an entry in both windows.
        today_ids = {e.get("entry_id") for e in new_entries}
        prior_entries = [e for e in historical if e.get("entry_id") not in today_ids]

    if not new_entries:
        return _no_new_content_payload(len(prior_entries))

    todays_text = "\n".join(_condense_for_window(e) for e in new_entries)
    prior_text = (
        "\n".join(_condense_for_window(e) for e in prior_entries)
        if prior_entries
        else "(none — empty prior window)"
    )

    prompt = SUMMARY_PROMPT.format(
        today_count=len(new_entries),
        todays_entries=todays_text,
        prior_count=len(prior_entries),
        prior_entries=prior_text,
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=2)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed
        print(f"[intel.daily_summary] LLM call failed: {exc}")
        return None

    raw = response.content[0].text if response.content else ""
    try:
        payload = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"[intel.daily_summary] could not parse JSON reply: {exc}")
        return None

    if not isinstance(payload, dict):
        print(f"[intel.daily_summary] expected object, got {type(payload).__name__}")
        return None

    missing = [k for k in REQUIRED_KEYS if k not in payload]
    if missing:
        print(f"[intel.daily_summary] missing required keys: {missing}")
        return None

    # Type-normalize: every required key must be a list of strings.
    for k in REQUIRED_KEYS:
        if not isinstance(payload.get(k), list):
            payload[k] = []

    payload = _scrub_payload(payload)
    payload["window"] = {"n_today": len(new_entries), "n_prior": len(prior_entries)}
    return payload


# --- Convenience render helpers (used by emailer / Bluesky downstream) ---


def render_text(payload: dict) -> str:
    """Plain-text render for stdout / fallback contexts."""
    if not payload:
        return "(daily summary unavailable)"
    lines = []
    lines.append("TL;DR")
    for b in payload.get("tldr", []):
        lines.append(f"  • {b}")
    if payload.get("implications"):
        lines.append("")
        lines.append("Implications vs prior 7d")
        for b in payload["implications"]:
            lines.append(f"  • {b}")
    if payload.get("attention"):
        lines.append("")
        lines.append("Worth attention")
        for b in payload["attention"]:
            lines.append(f"  • {b}")
    if payload.get("tags"):
        lines.append("")
        lines.append("Tags: " + ", ".join(payload["tags"]))
    win = payload.get("window") or {}
    if win:
        lines.append("")
        lines.append(f"(window: {win.get('n_today', 0)} new, {win.get('n_prior', 0)} prior)")
    return "\n".join(lines)


def render_bluesky(payload: dict, max_chars: int = 280) -> str:
    """One-line summary suitable for the Bluesky daily post (Phase 3).

    Lead bullet + tag chunk + link CTA; truncated to ``max_chars``.
    """
    if not payload:
        return "Quantum Intel: summary unavailable today. https://qrater.org"
    lead = (payload.get("tldr") or ["Quantum Intel daily."])[0]
    tags = " ".join(f"#{t}" for t in (payload.get("tags") or [])[:3])
    cta = "https://qrater.org"
    parts = [lead, tags, cta] if tags else [lead, cta]
    body = " ".join(p for p in parts if p)
    if len(body) <= max_chars:
        return body
    # Truncate the lead, keep tags + cta intact.
    suffix = f" {tags} {cta}".strip() if tags else f" {cta}"
    keep = max_chars - len(suffix) - 1
    if keep < 20:
        return cta  # degrade to just the link
    return lead[:keep].rstrip() + "…" + suffix
