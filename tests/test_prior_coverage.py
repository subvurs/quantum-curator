"""Tests for ``db.find_prior_coverage`` and the router empty-answer retry.

``find_prior_coverage`` feeds the scorer a "this story is already in the
corpus" note so cross-source syndication (five outlets, one result) no
longer scores novelty=1.0 five times. It must match on identical URL,
shared arXiv id, or title similarity, respect the lookback window, and
exclude the article being scored.

``_router_complete`` retries exactly once on an empty router answer and
still raises when both attempts are empty.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from quantum_curator import config, db, llm_client
from quantum_curator.models import CuratedPost, PostStatus, RawArticle, Source, SourceType


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config.get_settings.cache_clear()
    settings = config.get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db.init_db()
    yield tmp_path
    config.get_settings.cache_clear()


def _post(title: str, url: str, source: str, when: datetime, article_id: str) -> CuratedPost:
    # curated_posts.article_id is a FOREIGN KEY into raw_articles (PRAGMA
    # foreign_keys=ON), so the raw row has to exist first.
    src = Source(id=f"src-{source}", name=source, source_type=SourceType.RSS,
                 url="https://example.org")
    db.save_source(src)
    db.save_raw_article(RawArticle(
        id=article_id, source_id=src.id, source_name=source,
        source_type=SourceType.RSS, title=title, url=url, published_at=when,
    ))
    p = CuratedPost(
        article_id=article_id, title=title, original_url=url, source_name=source,
        summary="s", curator_commentary="c", relevance_score=0.8,
        published_at=when, status=PostStatus.PUBLISHED,
    )
    db.save_curated_post(p)
    return p


def test_prior_coverage_matches_url_arxiv_and_title(isolated_db):
    now = datetime.utcnow()
    _post("Sunlight creates quantum entanglement once thought to require lasers",
          "https://phys.org/sunlight", "Phys.org Quantum", now - timedelta(days=2), "art-1")
    _post("Researchers Show Sunlight Can Generate Quantum Entanglement",
          "https://tqi.example/sunlight", "The Quantum Insider", now - timedelta(days=1), "art-2")
    _post("Erasure Conversion in Integer Fluxonium Qubits",
          "https://arxiv.org/abs/2605.12345v1", "arXiv Quantum Physics", now - timedelta(days=3), "art-3")
    _post("A completely unrelated qLDPC decoder paper",
          "https://arxiv.org/abs/2606.00001v1", "arXiv Quantum Physics", now - timedelta(days=3), "art-4")
    _post("Sunlight-powered setup generates quantum entanglement",
          "https://old.example/sunlight", "Science Daily", now - timedelta(days=40), "art-5")

    # same url
    hits = db.find_prior_coverage(title="whatever", url="https://phys.org/sunlight")
    assert [h["reason"] for h in hits] == ["same url"]

    # same arXiv id, version-insensitive
    hits = db.find_prior_coverage(title="Erasure conversion", arxiv_id="2605.12345v2")
    assert hits and hits[0]["reason"] == "same arXiv id"

    # title similarity, window-limited (the 40-day-old post is excluded)
    hits = db.find_prior_coverage(
        title="Sunlight Can Generate Quantum Entanglement, Researchers Show",
        url="https://new.example/sunlight",
    )
    assert hits, "expected a title-similarity hit"
    assert all(h["reason"].startswith("title similarity") for h in hits)
    assert "Science Daily" not in {h["source_name"] for h in hits}
    assert "arXiv Quantum Physics" not in {h["source_name"] for h in hits}


def test_prior_coverage_excludes_self_and_returns_empty_when_none(isolated_db):
    now = datetime.utcnow()
    _post("Self post title about qubits", "https://x/self", "S", now, "self-id")
    assert db.find_prior_coverage(title="Self post title about qubits",
                                  url="https://x/self", exclude_article_id="self-id") == []
    assert db.find_prior_coverage(title="nothing like this exists") == []


# --- router empty-answer retry -----------------------------------------


@dataclass
class _Settings:
    llm_backend: str = "router"
    anthropic_api_key: str = ""
    router_python: str = "python"
    router_cli_cwd: str = "/tmp/router-cwd"
    router_timeout_sec: float = 5.0


def _fake_run_factory(answers: list[str], calls: list[int]):
    def _fake_run(cmd, cwd, capture_output, text, timeout):
        calls.append(1)
        answer = answers.pop(0)
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"answer": answer, "provenance": {"tier": "tier0"}}), stderr=""
        )
    return _fake_run


def test_router_retries_once_on_empty_answer(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(["", "second try"], calls))
    out = llm_client._router_complete(system="s", user="u", allow_escalation=False,
                                      settings=_Settings())
    assert out == "second try"
    assert len(calls) == 2


def test_router_raises_after_two_empty_answers(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(["", "  "], calls))
    with pytest.raises(llm_client.RouterError, match="empty answer"):
        llm_client._router_complete(system="s", user="u", allow_escalation=False,
                                    settings=_Settings())
    assert len(calls) == 2
