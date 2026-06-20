"""Tests for the LLM backend chokepoint (``quantum_curator.llm_client``).

Covers the two backends the curator pipeline can dispatch to plus the
scorer-injection adapter, all without touching the network, the Anthropic
SDK, or the real K11 router subprocess:

  * anthropic backend → ``_anthropic_complete`` is exercised by stubbing the
    ``anthropic`` module's ``Anthropic`` client; text blocks are concatenated.
  * router backend → ``_router_complete`` is exercised by stubbing
    ``subprocess.run`` to return a canned ``{"answer","provenance"}`` JSON
    payload on stdout; the ``--no-escalate`` flag is asserted present/absent
    per ``allow_escalation``.
  * the raise-on-failure contract (no silent degradation) for: empty
    anthropic key, non-zero router exit, non-JSON router stdout, empty router
    answer, and router timeout.
  * ``make_router_llm_call`` returns a 3-arg adapter matching the scorer seam
    and forwards the escalation policy.

The backend dispatch keys off ``settings.llm_backend`` only, so a tiny
``_Settings`` stand-in (no pydantic load, no .env) is sufficient.
"""

from __future__ import annotations

import json
import subprocess
import types
from dataclasses import dataclass, field

import pytest

from quantum_curator import llm_client


# --- Lightweight settings stand-in -------------------------------------------


@dataclass
class _Settings:
    """Minimal duck-typed settings: only the attributes llm_client reads."""

    llm_backend: str = "anthropic"
    anthropic_api_key: str = "sk-test-fake"
    router_python: str = "python"
    router_cli_cwd: str = "/tmp/router-cwd"
    router_timeout_sec: float = 5.0


# --- Anthropic backend -------------------------------------------------------


class _FakeBlock:
    def __init__(self, text: str, type_: str = "text"):
        self.text = text
        self.type = type_


class _FakeMessages:
    def __init__(self, recorder: dict, blocks: list[_FakeBlock]):
        self._recorder = recorder
        self._blocks = blocks

    def create(self, **kwargs):
        self._recorder.update(kwargs)
        return types.SimpleNamespace(content=self._blocks)


class _FakeAnthropic:
    """Stand-in for ``anthropic.Anthropic`` capturing constructor + call args."""

    last_recorder: dict = {}

    def __init__(self, *, api_key: str):
        _FakeAnthropic.last_recorder = {"api_key": api_key}
        self.messages = _FakeMessages(
            _FakeAnthropic.last_recorder,
            [_FakeBlock("Hello "), _FakeBlock("world"), _FakeBlock("!", type_="other")],
        )


@pytest.fixture
def fake_anthropic(monkeypatch: pytest.MonkeyPatch):
    """Inject a fake ``anthropic`` module so no SDK / network is needed.

    ``_anthropic_complete`` does ``import anthropic`` inside the function, so
    patching ``sys.modules['anthropic']`` is enough.
    """
    mod = types.ModuleType("anthropic")
    mod.Anthropic = _FakeAnthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "anthropic", mod)
    yield _FakeAnthropic


def test_anthropic_backend_concatenates_text_blocks(fake_anthropic):
    settings = _Settings(llm_backend="anthropic")
    out = llm_client.llm_complete(
        system="SYS",
        user="USER",
        model="claude-sonnet-4-5",
        max_tokens=123,
        temperature=0.2,
        settings=settings,
    )
    # Only the two type=="text" blocks are joined; the "other" block dropped.
    assert out == "Hello world"
    rec = fake_anthropic.last_recorder
    assert rec["api_key"] == "sk-test-fake"
    assert rec["model"] == "claude-sonnet-4-5"
    assert rec["max_tokens"] == 123
    assert rec["temperature"] == 0.2
    assert rec["system"] == "SYS"
    assert rec["messages"] == [{"role": "user", "content": "USER"}]


def test_anthropic_backend_raises_on_empty_key(fake_anthropic):
    settings = _Settings(llm_backend="anthropic", anthropic_api_key="")
    with pytest.raises(RuntimeError, match="anthropic_api_key is empty"):
        llm_client.llm_complete(
            system="S", user="U", model="m", max_tokens=10, settings=settings
        )


# --- Router backend ----------------------------------------------------------


@dataclass
class _FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class _RunRecorder:
    calls: list = field(default_factory=list)


def _patch_subprocess_run(monkeypatch, *, proc=None, raise_exc=None, recorder=None):
    def _fake_run(cmd, **kwargs):
        if recorder is not None:
            recorder.calls.append({"cmd": cmd, "kwargs": kwargs})
        if raise_exc is not None:
            raise raise_exc
        return proc

    monkeypatch.setattr(llm_client.subprocess, "run", _fake_run)


def test_router_backend_returns_answer_and_omits_no_escalate_when_allowed(
    monkeypatch,
):
    payload = {"answer": "router said this", "provenance": {"tier": "tier0"}}
    rec = _RunRecorder()
    _patch_subprocess_run(
        monkeypatch,
        proc=_FakeProc(returncode=0, stdout=json.dumps(payload)),
        recorder=rec,
    )
    settings = _Settings(llm_backend="router")
    out = llm_client.llm_complete(
        system="SYS PROMPT",
        user="USER PROMPT",
        model="ignored-by-router",
        max_tokens=999,
        allow_escalation=True,
        settings=settings,
    )
    assert out == "router said this"
    cmd = rec.calls[0]["cmd"]
    # Task-mode CLI shape; model/max_tokens NOT forwarded (router owns them).
    assert "--task" in cmd and "--system-file" in cmd and "--json" in cmd
    assert cmd[-1] == "USER PROMPT"
    # allow_escalation=True → no --no-escalate flag.
    assert "--no-escalate" not in cmd
    assert rec.calls[0]["kwargs"]["cwd"] == "/tmp/router-cwd"
    assert rec.calls[0]["kwargs"]["timeout"] == 5.0


def test_router_backend_adds_no_escalate_when_disallowed(monkeypatch):
    payload = {"answer": "local only", "provenance": {"tier": "tier0"}}
    rec = _RunRecorder()
    _patch_subprocess_run(
        monkeypatch,
        proc=_FakeProc(returncode=0, stdout=json.dumps(payload)),
        recorder=rec,
    )
    settings = _Settings(llm_backend="router")
    out = llm_client.llm_complete(
        system="S",
        user="U",
        model="m",
        max_tokens=1,
        allow_escalation=False,
        settings=settings,
    )
    assert out == "local only"
    assert "--no-escalate" in rec.calls[0]["cmd"]


def test_router_backend_raises_on_nonzero_exit(monkeypatch):
    _patch_subprocess_run(
        monkeypatch, proc=_FakeProc(returncode=2, stdout="", stderr="boom")
    )
    settings = _Settings(llm_backend="router")
    with pytest.raises(llm_client.RouterError, match="router exited 2"):
        llm_client.llm_complete(
            system="S", user="U", model="m", max_tokens=1, settings=settings
        )


def test_router_backend_raises_on_non_json(monkeypatch):
    _patch_subprocess_run(
        monkeypatch, proc=_FakeProc(returncode=0, stdout="not json at all")
    )
    settings = _Settings(llm_backend="router")
    with pytest.raises(llm_client.RouterError, match="non-JSON"):
        llm_client.llm_complete(
            system="S", user="U", model="m", max_tokens=1, settings=settings
        )


def test_router_backend_raises_on_empty_answer(monkeypatch):
    payload = {"answer": "   ", "provenance": {"tier": "tier1"}}
    _patch_subprocess_run(
        monkeypatch, proc=_FakeProc(returncode=0, stdout=json.dumps(payload))
    )
    settings = _Settings(llm_backend="router")
    with pytest.raises(llm_client.RouterError, match="empty answer"):
        llm_client.llm_complete(
            system="S", user="U", model="m", max_tokens=1, settings=settings
        )


def test_router_backend_raises_on_timeout(monkeypatch):
    _patch_subprocess_run(
        monkeypatch,
        raise_exc=subprocess.TimeoutExpired(cmd="router", timeout=5.0),
    )
    settings = _Settings(llm_backend="router")
    with pytest.raises(llm_client.RouterError, match="timed out"):
        llm_client.llm_complete(
            system="S", user="U", model="m", max_tokens=1, settings=settings
        )


# --- Scorer-injection adapter ------------------------------------------------


def test_make_router_llm_call_returns_three_arg_adapter(monkeypatch):
    payload = {"answer": "scorer json blob", "provenance": {"tier": "tier0"}}
    rec = _RunRecorder()
    _patch_subprocess_run(
        monkeypatch,
        proc=_FakeProc(returncode=0, stdout=json.dumps(payload)),
        recorder=rec,
    )
    settings = _Settings(llm_backend="router")
    adapter = llm_client.make_router_llm_call(settings, allow_escalation=False)
    # Scorer seam signature: llm_call(system_prompt, user_prompt, model) -> str.
    out = adapter("SCORER SYS", "SCORER USER", "scorer-model")
    assert out == "scorer json blob"
    cmd = rec.calls[0]["cmd"]
    assert "--no-escalate" in cmd  # local-only / fail-closed bulk
    assert cmd[-1] == "SCORER USER"


def test_make_router_llm_call_propagates_escalation_true(monkeypatch):
    payload = {"answer": "x", "provenance": {"tier": "tier0"}}
    rec = _RunRecorder()
    _patch_subprocess_run(
        monkeypatch,
        proc=_FakeProc(returncode=0, stdout=json.dumps(payload)),
        recorder=rec,
    )
    settings = _Settings(llm_backend="router")
    adapter = llm_client.make_router_llm_call(settings, allow_escalation=True)
    adapter("S", "U", "m")
    assert "--no-escalate" not in rec.calls[0]["cmd"]


# --- Config backend-toggle semantics -----------------------------------------


def test_config_uses_router_and_llm_available():
    """The real pydantic Settings expose the backend-toggle helpers the
    chokepoint + curator guards rely on."""
    from quantum_curator.config import Settings

    # Default backend: anthropic. llm_available iff a key is present.
    anth = Settings(llm_backend="anthropic", anthropic_api_key="sk-x")
    assert anth.uses_router is False
    assert anth.llm_available is True

    anth_nokey = Settings(llm_backend="anthropic", anthropic_api_key="")
    assert anth_nokey.uses_router is False
    assert anth_nokey.llm_available is False  # anthropic + no key → unusable

    # Router backend: usable without an anthropic key (router owns its creds).
    router = Settings(llm_backend="router", anthropic_api_key="")
    assert router.uses_router is True
    assert router.llm_available is True
