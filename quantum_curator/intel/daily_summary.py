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
import logging
import re
import time
from typing import Any

from ..config import get_settings
from ..llm_client import llm_complete
from . import inventory_view
from .synthesizer import _condense_entry, _extract_json


logger = logging.getLogger(__name__)

# LLM retry policy. The K11 router fails intermittently ("router
# returned empty answer (tier=unavailable)" — observed 2026-07-14 and
# 2026-07-16, killing the TL;DR share for those days), while a second
# call later in the same run succeeds (2026-07-15/17 journals show the
# intel-email attempt failing or succeeding independently of the
# share-intel-summary attempt ~30-40 min later). Retry with backoff
# inside build_daily_summary so a single transient router hiccup no
# longer drops the whole daily summary. ``_sleep`` is module-level so
# tests can stub it out.
LLM_RETRY_ATTEMPTS = 3
LLM_RETRY_WAIT_SEC = 90.0  # doubles per retry: 90s, then 180s
_sleep = time.sleep


# Hallucinated-citation guard. The summary prompt teaches the [#N]
# format by example but the LLM has been observed to invent IDs that
# never appeared in either today's seed batch or the historical
# corpus (e.g. [#2000007] on 2026-06-10 when the seed batch only
# went up to 2000004). _validate_citations() soft-strips invalid
# tokens while preserving the surrounding prose — same posture as
# _mask_forbidden() for marketing phrases.
_CITATION_RE = re.compile(r"\[#(\d+)\]")


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


def _strip_invalid_citations(text: str, valid_ids: set[int]) -> tuple[str, int, int]:
    """Strip [#N] tokens whose N is not in valid_ids; keep valid ones.

    Returns (cleaned_text, kept_count, stripped_count). Tries to be
    cosmetic about whitespace — a stripped token also consumes one
    trailing space if present, and double spaces are collapsed once.
    Leading/trailing whitespace on the bullet is then stripped so a
    bullet that starts/ends with a stripped token reads cleanly.
    """
    kept = 0
    stripped = 0

    def _sub(match: re.Match) -> str:
        nonlocal kept, stripped
        try:
            entry_id = int(match.group(1))
        except (TypeError, ValueError):
            stripped += 1
            return ""
        if entry_id in valid_ids:
            kept += 1
            return match.group(0)
        stripped += 1
        return ""

    if not _CITATION_RE.search(text):
        return text, 0, 0

    # Replace tokens. The post-pass collapses any double spaces or
    # " ." / " ," artifacts the strip leaves behind.
    out = _CITATION_RE.sub(_sub, text)
    # Collapse double whitespace introduced by a token+space removal,
    # then trim space before common punctuation.
    out = re.sub(r"  +", " ", out)
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    out = out.strip()
    return out, kept, stripped


def _validate_citations(payload: dict, valid_ids: set[int]) -> tuple[dict, dict]:
    """Soft-mask any [#N] token whose N is not in valid_ids.

    Mirrors _scrub_payload()'s traversal so every string in tldr,
    implications, and attention gets scanned. Returns the modified
    payload (mutated in place for consistency with _scrub_payload) plus
    a {"kept": k, "stripped": s} counter for logging. Fast path: if no
    tokens at all appear in any string, the payload is returned
    unchanged.
    """
    total_kept = 0
    total_stripped = 0
    for key in ("tldr", "implications", "attention"):
        vals = payload.get(key, [])
        if not isinstance(vals, list):
            continue
        cleaned: list[str] = []
        for v in vals:
            text = str(v)
            new_text, kept, stripped = _strip_invalid_citations(text, valid_ids)
            total_kept += kept
            total_stripped += stripped
            cleaned.append(new_text)
        payload[key] = cleaned
    return payload, {"kept": total_kept, "stripped": total_stripped}


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
    if not settings.llm_available:
        print("[intel.daily_summary] no LLM backend configured — skipping")
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

    # Retry loop: covers transient router failures AND malformed/
    # incomplete LLM replies (a fresh completion usually parses).
    # Fail-closed contract preserved — return None only after the
    # final attempt fails.
    payload: dict | None = None
    for attempt in range(1, LLM_RETRY_ATTEMPTS + 1):
        if attempt > 1:
            wait = LLM_RETRY_WAIT_SEC * (2 ** (attempt - 2))
            print(
                f"[intel.daily_summary] retrying in {wait:.0f}s "
                f"(attempt {attempt}/{LLM_RETRY_ATTEMPTS})"
            )
            _sleep(wait)
        try:
            raw = llm_complete(
                system=SUMMARY_SYSTEM,
                user=prompt,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                allow_escalation=True,
                settings=settings,
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed
            print(f"[intel.daily_summary] LLM call failed: {exc}")
            continue
        try:
            candidate = _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"[intel.daily_summary] could not parse JSON reply: {exc}")
            continue
        if not isinstance(candidate, dict):
            print(
                "[intel.daily_summary] expected object, got "
                f"{type(candidate).__name__}"
            )
            continue
        missing = [k for k in REQUIRED_KEYS if k not in candidate]
        if missing:
            print(f"[intel.daily_summary] missing required keys: {missing}")
            continue
        payload = candidate
        break

    if payload is None:
        print(
            f"[intel.daily_summary] giving up after {LLM_RETRY_ATTEMPTS} attempts"
        )
        return None

    # Type-normalize: every required key must be a list of strings.
    for k in REQUIRED_KEYS:
        if not isinstance(payload.get(k), list):
            payload[k] = []

    payload = _scrub_payload(payload)

    # Hallucinated-citation guard. Build the set of entry_ids the LLM
    # was actually shown (both windows) and strip any [#N] token that
    # falls outside it. Decision: strip-and-keep — the bullet prose is
    # still factually useful even when the attribution was invented.
    valid_ids: set[int] = set()
    for e in new_entries:
        eid = e.get("entry_id")
        if isinstance(eid, int):
            valid_ids.add(eid)
    for e in prior_entries:
        eid = e.get("entry_id")
        if isinstance(eid, int):
            valid_ids.add(eid)
    payload, citation_counts = _validate_citations(payload, valid_ids)
    if citation_counts["stripped"]:
        logger.info(
            "daily_summary: stripped %d hallucinated citation(s); kept %d valid",
            citation_counts["stripped"],
            citation_counts["kept"],
        )

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


def render_bluesky(payload: dict, max_chars: int = 300) -> str:
    """Multi-bullet summary suitable for the Bluesky daily post.

    Packs as many full TL;DR bullets as fit before the tag+CTA suffix.
    The image card (see ``intel.image_card.render_summary_card``)
    carries any overflow — Bluesky's hard limit is 300 graphemes, so
    this just gets the most into the text post for screen-reader and
    quote-preview surfaces.

    Falls back to truncated ``tldr[0]`` + suffix when not even one full
    bullet fits inside the budget.
    """
    if not payload:
        return "Quantum Intel: summary unavailable today. https://qrater.org"

    bullets = [str(b) for b in (payload.get("tldr") or []) if b]
    tags = " ".join(f"#{t}" for t in (payload.get("tags") or [])[:3])
    cta = "https://qrater.org"

    suffix = ""
    if tags:
        suffix = f"\n\n{tags} {cta}"
    else:
        suffix = f"\n\n{cta}"
    budget = max_chars - len(suffix)

    # Pack as many full bullets as fit.
    body = ""
    packed = 0
    for b in bullets:
        candidate_line = f"• {b}"
        candidate_body = candidate_line if not body else f"{body}\n{candidate_line}"
        if len(candidate_body) <= budget:
            body = candidate_body
            packed += 1
        else:
            break

    if packed >= 1:
        return body + suffix

    # Fallback: truncate the lead bullet to fit within budget.
    lead = bullets[0] if bullets else "Quantum Intel daily."
    # Reserve room for "• " prefix + ellipsis.
    keep = budget - len("• ") - 1
    if keep < 20:
        return cta  # degrade to just the link
    truncated = lead[:keep].rstrip() + "…"
    return f"• {truncated}{suffix}"


def render_bluesky_thread(
    payload: dict, link: str = "https://qrater.org", max_chars: int = 300
) -> list[str]:
    """Render the daily summary as a list of Bluesky post texts.

    Returns a single-element list when everything fits in one post —
    byte-identical to ``render_bluesky(payload, max_chars)`` for the
    short path so the fast case stays observable.

    Returns 2-3 posts when overflow:

    - Post 1: TL;DR header + as many tldr bullets as fit
    - Post 2: Implications header + bullets that fit
    - Post 3: Attention bullets + tags + link

    The link goes on the LAST post only. Posts 2+ get a "(N/M)" suffix
    so readers see the thread structure even if Bluesky's client
    collapses replies.

    The short-path branch calls render_bluesky() directly to preserve
    byte-identity; do not duplicate its logic here.
    """
    if not payload:
        return [f"Quantum Intel: summary unavailable today. {link}"]

    # Fast path: try the single-post renderer first. If the result
    # already contains every TL;DR bullet, every implication that fits,
    # and every attention bullet, we're done.
    single = render_bluesky(payload, max_chars=max_chars)

    tldr = [str(b) for b in (payload.get("tldr") or []) if b]
    implications = [str(b) for b in (payload.get("implications") or []) if b]
    attention = [str(b) for b in (payload.get("attention") or []) if b]
    tags_list = list((payload.get("tags") or [])[:3])

    # If no overflow content (no implications, no attention) AND every
    # tldr bullet made it into the single-post render, return single.
    all_tldr_fit = all((f"• {b}" in single) or (b in single) for b in tldr)
    has_overflow = bool(implications or attention)
    if not has_overflow and all_tldr_fit:
        return [single]
    if not has_overflow and not tldr:
        return [single]

    # Threaded path. Build 2-3 posts, link only on the last.
    posts: list[str] = []
    tags_str = " ".join(f"#{t}" for t in tags_list)

    # Post 1: TL;DR header + tldr bullets that fit (no link, no tags).
    # Reserve room for the "(1/M)" suffix added at the end; we don't
    # know M yet, so reserve 6 chars conservatively ("(1/3) ").
    reserve = 8
    p1_budget = max_chars - reserve
    p1_lines = ["TL;DR"]
    p1_text = "TL;DR"
    for b in tldr:
        candidate = p1_text + f"\n• {b}"
        if len(candidate) <= p1_budget:
            p1_text = candidate
            p1_lines.append(f"• {b}")
        else:
            # Carry the rest to the implications post.
            implications = [b] + implications
            # And every subsequent tldr bullet too.
            idx = tldr.index(b) + 1
            implications = tldr[idx:] + implications
            break
    posts.append(p1_text)

    # Post 2: Implications header + bullets that fit (no link, no tags).
    if implications:
        p2_budget = max_chars - reserve
        p2_text = "Implications"
        for b in implications:
            candidate = p2_text + f"\n• {b}"
            if len(candidate) <= p2_budget:
                p2_text = candidate
            else:
                break
        posts.append(p2_text)

    # Final post: Attention bullets (if any) + tags + link.
    final_suffix = f"\n\n{tags_str} {link}" if tags_str else f"\n\n{link}"
    final_budget = max_chars - reserve - len(final_suffix)
    if attention:
        p_final_text = "Worth attention"
        for b in attention:
            candidate = p_final_text + f"\n• {b}"
            if len(candidate) <= final_budget:
                p_final_text = candidate
            else:
                break
        p_final_text += final_suffix
    else:
        # No attention bullets — final post is just link + tags.
        # If there's only post 1 so far and no implications, no need to
        # ship a 2nd post for just a link; instead, attach link to post 1.
        if len(posts) == 1:
            attached = posts[0] + f"\n\n{tags_str} {link}" if tags_str else posts[0] + f"\n\n{link}"
            if len(attached) <= max_chars:
                posts[0] = attached
                # Add (1/1) suffix below? No — single post means no suffix.
                return [posts[0]]
        p_final_text = (tags_str + " " + link).strip() if tags_str else link
    posts.append(p_final_text)

    # Append (N/M) position suffixes to posts 2..M.
    M = len(posts)
    if M == 1:
        return posts
    finalized: list[str] = []
    for i, body in enumerate(posts, start=1):
        if i == 1:
            finalized.append(body)
        else:
            tag = f"({i}/{M})"
            candidate = f"{body}\n{tag}"
            if len(candidate) > max_chars:
                # Trim body to fit the position tag.
                keep = max_chars - len(tag) - 1
                candidate = body[:keep].rstrip() + "\n" + tag
            finalized.append(candidate)
    return finalized
