"""Regression tests for credential redaction in the GitHub Pages publisher.

The deploy step is handed a token-embedded clone URL
(``https://x-access-token:<PAT>@github.com/owner/repo.git``). Before the fix,
``publisher.deploy`` printed that URL verbatim on success and echoed git
``stdout``/``stderr`` on failure, leaking the PAT into stdout -> journald on
the K11 box. ``_redact_url_creds`` strips the userinfo before any print.

These tests lock that behavior so a future refactor can't silently re-leak.
"""

from __future__ import annotations

from quantum_curator.publisher import _redact_url_creds


def test_redacts_token_embedded_clone_url():
    url = "https://x-access-token:ghp_SECRETTOKEN12345@github.com/subvurs/quantum-curator.git"
    out = _redact_url_creds(url)
    assert "ghp_SECRETTOKEN12345" not in out
    assert "x-access-token" not in out
    assert out == "https://***@github.com/subvurs/quantum-curator.git"


def test_redacts_userinfo_inside_a_longer_message():
    msg = "Successfully deployed to https://user:pass@github.com/o/r.git (gh-pages)"
    out = _redact_url_creds(msg)
    assert "user:pass" not in out
    assert out == "Successfully deployed to https://***@github.com/o/r.git (gh-pages)"


def test_redacts_token_in_git_error_output():
    # git surfaces the clone URL in fatal: lines on auth/clone failure.
    err = "fatal: could not read from 'https://x-access-token:ghp_ABC@github.com/o/r.git'"
    out = _redact_url_creds(err)
    assert "ghp_ABC" not in out
    assert "https://***@github.com/o/r.git" in out


def test_leaves_credential_free_url_unchanged():
    url = "https://github.com/subvurs/quantum-curator.git"
    assert _redact_url_creds(url) == url


def test_none_and_empty_are_passthrough():
    assert _redact_url_creds("") == ""
    assert _redact_url_creds(None) is None
