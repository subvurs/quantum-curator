"""Tests for ``build_daily_summary`` LLM retry behavior.

Locks the fix for the intermittent K11 router failure ("router
returned empty answer (tier=unavailable)", observed 2026-07-14 and
2026-07-16) that dropped the daily TL;DR Bluesky post for those days.
The fix retries the LLM call (and reply parse) up to
``LLM_RETRY_ATTEMPTS`` times with backoff before returning None.

Contract:

  * Transient llm_complete exception → retried; success on a later
    attempt returns a normal payload
  * Malformed JSON reply → retried (fresh completion usually parses)
  * All attempts failing → None (fail-closed contract preserved)
  * Backoff sleeps happen between attempts, never before the first
  * The "no new entries" branch makes zero LLM calls (unchanged)
"""

from __future__ import annotations

import json

import pytest

from quantum_curator.intel import daily_summary


VALID_REPLY = json.dumps(
    {
        "tldr": ["Bullet one.", "Bullet two."],
        "implications": ["Implication."],
        "attention": ["Watch this."],
        "tags": ["hardware"],
    }
)

NEW_ENTRIES = [
    {"entry_id": 2000001, "summary": "Test seed article.", "domain_tags": ["hw"]}
]
PRIOR_ENTRIES = [
    {"entry_id": 5, "summary": "Historical entry.", "domain_tags": ["hw"]}
]


class _Settings:
    llm_available = True


@pytest.fixture()
def patched(monkeypatch):
    """Patch settings + sleep; return a mutable call log."""
    log = {"sleeps": [], "calls": 0}
    monkeypatch.setattr(daily_summary, "get_settings", lambda: _Settings())
    monkeypatch.setattr(daily_summary, "_sleep", lambda s: log["sleeps"].append(s))
    return log


def _build(monkeypatch, log, replies):
    """Run build_daily_summary with llm_complete yielding ``replies``.

    Each item is either a string (returned) or an Exception (raised).
    """
    seq = list(replies)

    def fake_llm(**_kwargs):
        log["calls"] += 1
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(daily_summary, "llm_complete", fake_llm)
    return daily_summary.build_daily_summary(
        new_entries=NEW_ENTRIES, prior_entries=PRIOR_ENTRIES
    )


def test_first_attempt_success_no_sleep(monkeypatch, patched):
    payload = _build(monkeypatch, patched, [VALID_REPLY])
    assert payload is not None
    assert payload["tldr"] == ["Bullet one.", "Bullet two."]
    assert patched["calls"] == 1
    assert patched["sleeps"] == []


def test_transient_router_failure_then_success(monkeypatch, patched):
    """The 2026-07-16 failure mode: empty router answer on attempt 1."""
    payload = _build(
        monkeypatch,
        patched,
        [RuntimeError("router returned empty answer (tier=unavailable)"), VALID_REPLY],
    )
    assert payload is not None
    assert payload["window"] == {"n_today": 1, "n_prior": 1}
    assert patched["calls"] == 2
    assert patched["sleeps"] == [daily_summary.LLM_RETRY_WAIT_SEC]


def test_malformed_json_then_success(monkeypatch, patched):
    payload = _build(monkeypatch, patched, ["not json at all {{{", VALID_REPLY])
    assert payload is not None
    assert patched["calls"] == 2


def test_missing_keys_then_success(monkeypatch, patched):
    incomplete = json.dumps({"tldr": ["only bullet"]})
    payload = _build(monkeypatch, patched, [incomplete, VALID_REPLY])
    assert payload is not None
    assert patched["calls"] == 2


def test_all_attempts_fail_returns_none(monkeypatch, patched):
    n = daily_summary.LLM_RETRY_ATTEMPTS
    payload = _build(
        monkeypatch, patched, [RuntimeError("router unavailable")] * n
    )
    assert payload is None
    assert patched["calls"] == n
    # Backoff doubles: 90, 180 for the default 3 attempts.
    assert patched["sleeps"] == [
        daily_summary.LLM_RETRY_WAIT_SEC * (2**i) for i in range(n - 1)
    ]


def test_no_new_entries_makes_zero_llm_calls(monkeypatch, patched):
    def boom(**_kwargs):  # pragma: no cover — must not be reached
        raise AssertionError("llm_complete must not be called")

    monkeypatch.setattr(daily_summary, "llm_complete", boom)
    payload = daily_summary.build_daily_summary(
        new_entries=[], prior_entries=PRIOR_ENTRIES
    )
    assert payload is not None
    assert payload["tags"] == ["quiet-day"]
    assert patched["calls"] == 0
