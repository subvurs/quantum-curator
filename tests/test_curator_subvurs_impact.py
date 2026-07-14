"""Tests for Phase B Subvurs-impact integration.

Pins three behaviors per proposal §8 / §5.2:

  1. The three new TEXT/REAL columns (`subvurs_impact_score`,
     `subvurs_impact_report`, `subvurs_impact_version`) round-trip
     cleanly through `save_post` / `_row_to_post`, including the
     legacy-row case where the columns may be NULL.

  2. With `subvurs_impact_scoring_enabled=False` the curator path
     leaves the impact fields at their fail-closed defaults (0.0 /
     None / None) — feature flag actually gates work.

  3. With the flag on and a stubbed scorer, `curate_article` writes
     the returned ScoreReport's `score`, `version`, and the
     JSON-serialised report to the new columns. This is the integration
     contract between Curator and `subvurs_impact`.

The shared `subvurs_impact` package is vendored at
`quantum_curator/_vendor/subvurs_impact/` and imported at curator-module
load time. Tests skip the integration cases if the vendored package is
unavailable so they remain runnable in any environment.
"""

from __future__ import annotations

import json as _json
from datetime import datetime
from pathlib import Path

import pytest

from quantum_curator import config, curator as curator_mod, db
from quantum_curator.models import (
    ContentTopic,
    CuratedPost,
    PostStatus,
    RawArticle,
    Source,
    SourceType,
)


# --- Fixtures -----------------------------------------------------

@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh schema in a temp dir. Same pattern as test_save_article."""
    config.get_settings.cache_clear()
    settings = config.get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db.init_db()
    yield tmp_path
    config.get_settings.cache_clear()


def _make_source() -> Source:
    src = Source(
        name="Phase B Test Source",
        source_type=SourceType.RSS,
        url="https://example.com/feed",
        feed_url="https://example.com/feed.xml",
    )
    db.save_source(src)
    return src


def _make_article(source: Source) -> RawArticle:
    article = RawArticle(
        source_id=source.id,
        source_name=source.name,
        source_type=source.source_type,
        title="Phase B integration test article",
        url="https://example.com/article/phase-b",
        summary="A test article summary for the impact-scoring integration.",
        fetched_at=datetime.utcnow(),
    )
    db.save_raw_article(article)
    return article


# --- 1. DB round-trip of the three new columns --------------------

def test_curated_post_defaults_are_fail_closed(isolated_db):
    """A freshly-constructed CuratedPost has the safe defaults.

    Fail-closed invariant from proposal §3.1: score 0.0, no report,
    no version. Persisting a default post and reading it back must
    not drift to non-default values.
    """
    source = _make_source()
    article = _make_article(source)

    post = CuratedPost(
        article_id=article.id,
        title=article.title,
        original_url=article.url,
        source_name=article.source_name,
        summary=article.summary,
        curated_at=datetime.utcnow(),
        status=PostStatus.DRAFT,
    )

    assert post.subvurs_impact_score == 0.0
    assert post.subvurs_impact_report is None
    assert post.subvurs_impact_version is None

    db.save_post(post)
    fetched = db.get_post(post.id)
    assert fetched is not None
    assert fetched.subvurs_impact_score == 0.0
    assert fetched.subvurs_impact_report is None
    assert fetched.subvurs_impact_version is None


def test_curated_post_impact_fields_round_trip(isolated_db):
    """Writing a populated impact bundle survives db round-trip."""
    source = _make_source()
    article = _make_article(source)

    report_payload = {
        "version": "subvurs_impact_v0.1",
        "score": 0.77,
        "components_pre_gate": {
            "match": 0.7, "evidence": 0.8,
            "novelty": 0.7, "actionability": 1.0,
        },
        "evidence_class": "noisy_sim",
        "band": "HIGH_IMPACT",
    }

    post = CuratedPost(
        article_id=article.id,
        title=article.title,
        original_url=article.url,
        source_name=article.source_name,
        summary=article.summary,
        curated_at=datetime.utcnow(),
        status=PostStatus.DRAFT,
        subvurs_impact_score=0.77,
        subvurs_impact_report=_json.dumps(report_payload),
        subvurs_impact_version="subvurs_impact_v0.1",
    )
    db.save_post(post)

    fetched = db.get_post(post.id)
    assert fetched is not None
    assert fetched.subvurs_impact_score == pytest.approx(0.77)
    assert fetched.subvurs_impact_version == "subvurs_impact_v0.1"
    assert fetched.subvurs_impact_report is not None
    decoded = _json.loads(fetched.subvurs_impact_report)
    assert decoded["score"] == pytest.approx(0.77)
    assert decoded["evidence_class"] == "noisy_sim"


# --- 2. Feature flag actually gates work --------------------------

def test_curate_article_skips_scoring_when_flag_off(
    isolated_db, monkeypatch: pytest.MonkeyPatch
):
    """`subvurs_impact_scoring_enabled=False` MUST leave the impact
    fields at defaults. This is the operator's off-switch for Phase
    B observation (proposal §8 Phase D rollback case)."""
    settings = config.get_settings()
    monkeypatch.setattr(settings, "subvurs_impact_scoring_enabled", False)
    # Ensure the shared scorer is never called even if available.
    monkeypatch.setattr(
        curator_mod, "_impact_score_item", _boom_if_called
    )

    source = _make_source()
    article = _make_article(source)

    cur = curator_mod.Curator()
    # Disable the other LLM-touching paths so the test stays offline.
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "generate_subvurs_notes", False)
    monkeypatch.setattr(settings, "generate_images", False)

    import asyncio

    post = asyncio.run(cur.curate_article(article))

    assert post.subvurs_impact_score == 0.0
    assert post.subvurs_impact_report is None
    assert post.subvurs_impact_version is None


# --- 3. Stubbed-success integration path --------------------------

def test_curate_article_populates_impact_fields_when_enabled(
    isolated_db, monkeypatch: pytest.MonkeyPatch
):
    """With the flag on and a stub `score_item`, `curate_article`
    persists score / report-json / version exactly as returned."""
    if not curator_mod._IMPACT_AVAILABLE:
        pytest.skip("subvurs_impact vendored package unavailable")

    from quantum_curator._vendor.subvurs_impact import ScoreReport  # type: ignore

    fake_report = ScoreReport(
        version="subvurs_impact_v0.1",
        score=0.62,
        components_pre_gate={
            "match": 0.7, "evidence": 0.6,
            "novelty": 0.5, "actionability": 0.7,
        },
        components_post_gate={
            "match": 0.7, "evidence": 0.6,
            "novelty": 0.5, "actionability": 0.7,
        },
        weights={
            "match": 0.40, "evidence": 0.25,
            "novelty": 0.20, "actionability": 0.15,
        },
        evidence_class="noiseless_sim",
        novelty_basis="vs_inventory",
        gates_fired=[],
        scorer_model="stub",
        prompt_template_hash="stub_hash",
        path_catalog_version="v0-stub",
        donotuse_version="v0-stub",
    )

    def fake_score_item(item, **_):
        # Sanity-check the shape passed through the wrapper.
        assert "title" in item and "summary" in item
        return fake_report

    monkeypatch.setattr(curator_mod, "_impact_score_item", fake_score_item)

    settings = config.get_settings()
    monkeypatch.setattr(settings, "subvurs_impact_scoring_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-fake")
    monkeypatch.setattr(settings, "generate_subvurs_notes", False)
    monkeypatch.setattr(settings, "generate_images", False)

    # Block the commentary LLM path so we don't try real network.
    async def fallback_commentary(self, article):
        return "stub commentary"

    monkeypatch.setattr(
        curator_mod.Curator,
        "_generate_commentary",
        fallback_commentary,
    )

    source = _make_source()
    article = _make_article(source)

    cur = curator_mod.Curator()
    import asyncio

    post = asyncio.run(cur.curate_article(article))

    assert post.subvurs_impact_score == pytest.approx(0.62)
    assert post.subvurs_impact_version == "subvurs_impact_v0.1"
    assert post.subvurs_impact_report is not None
    decoded = _json.loads(post.subvurs_impact_report)
    assert decoded["score"] == pytest.approx(0.62)
    assert decoded["evidence_class"] == "noiseless_sim"

    # And it survived the db round-trip.
    fetched = db.get_post(post.id)
    assert fetched is not None
    assert fetched.subvurs_impact_score == pytest.approx(0.62)
    assert fetched.subvurs_impact_version == "subvurs_impact_v0.1"


# --- 4. Fail-closed when scorer crashes ---------------------------

def test_curate_article_handles_scorer_crash_fail_closed(
    isolated_db, monkeypatch: pytest.MonkeyPatch
):
    """If the shared scorer raises (library bug), the wrapper degrades
    to score=0.0 / report=None and curation continues. Curator is NEVER
    blocked by a scorer fault — proposal §3.1 fail-closed invariant."""
    if not curator_mod._IMPACT_AVAILABLE:
        pytest.skip("subvurs_impact vendored package unavailable")

    def crashing_score_item(item, **_):
        raise RuntimeError("simulated library failure")

    monkeypatch.setattr(curator_mod, "_impact_score_item", crashing_score_item)

    settings = config.get_settings()
    monkeypatch.setattr(settings, "subvurs_impact_scoring_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-fake")
    monkeypatch.setattr(settings, "generate_subvurs_notes", False)
    monkeypatch.setattr(settings, "generate_images", False)

    async def fallback_commentary(self, article):
        return "stub commentary"

    monkeypatch.setattr(
        curator_mod.Curator,
        "_generate_commentary",
        fallback_commentary,
    )

    source = _make_source()
    article = _make_article(source)

    cur = curator_mod.Curator()
    import asyncio

    post = asyncio.run(cur.curate_article(article))

    # Curation succeeded; the scorer fault did not propagate.
    assert post.curator_commentary == "stub commentary"
    # And the impact fields collapsed to fail-closed defaults.
    assert post.subvurs_impact_score == 0.0
    assert post.subvurs_impact_report is None
    assert post.subvurs_impact_version is None


# --- 5. Prompt-lock: notes prompt comes from the shared catalog ----

def test_subvurs_notes_prompt_is_built_from_shared_catalog():
    """Lock for the v1.8.0 prompt dedup (2026-07-14).

    The inline ``SUBVURS_NOTES_SYSTEM_PROMPT`` duplicate in curator.py
    was deleted; the prompt must now be composed from the vendored
    ``path_catalog.build_prompt()`` plus the curator output-format
    preamble. This test prevents a silent return of the inline
    duplicate: the catalog-only sections (CROSS-CORPUS INTERSECTIONS,
    the DO-NOT-USE block, the July 2026 historical core-theory
    re-scope) must all be present, alongside the preamble marker.
    """
    if not curator_mod._IMPACT_AVAILABLE:
        pytest.skip("subvurs_impact vendored package unavailable")

    prompt = curator_mod.SUBVURS_NOTES_SYSTEM_PROMPT
    assert prompt is not None, (
        "notes prompt is None despite vendored catalog being importable"
    )
    # Curator-specific preamble.
    assert "OUTPUT FORMAT" in prompt
    # Catalog-only sections — the deleted inline duplicate had none of
    # these, so their presence proves the prompt is catalog-built.
    assert "CROSS-CORPUS INTERSECTIONS" in prompt
    assert "DO NOT USE" in prompt
    assert "HISTORICAL CORE THEORY" in prompt

    # The catalog powering the prompt is the July 2026 re-scope.
    from quantum_curator._vendor.subvurs_impact import path_catalog  # type: ignore

    assert path_catalog.PATH_CATALOG_VERSION == "v0.2.0-20260714"


def test_subvurs_notes_prompt_is_none_when_catalog_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    """Fail-closed: with the vendored catalog unavailable the builder
    returns None (note generation skipped) rather than falling back to
    any inline prompt text."""
    monkeypatch.setattr(curator_mod, "_IMPACT_AVAILABLE", False)
    assert curator_mod._build_subvurs_notes_system_prompt() is None


# --- helpers ------------------------------------------------------

def _boom_if_called(*_args, **_kwargs):
    raise AssertionError(
        "scorer was called despite feature flag being off"
    )
