"""LLM backend chokepoint for Quantum Curator.

A single place every LLM completion in the pipeline flows through, so the
backend can be switched between:

  * ``"anthropic"`` (default) — a direct Anthropic Messages API call, byte
    equivalent to the inline ``self.client.messages.create(...)`` calls the
    curator used before this module existed. Off-box behavior is unchanged.
  * ``"router"`` — shell out to the K11 local-first router
    (``python -m router.cli --task ...``), which runs local gpt-oss:120b first
    and only escalates to a capped cloud model (Claude Max ``claude -p`` /
    NVIDIA NIM) on local failure when ``allow_escalation`` is True.

The function deliberately RAISES on any backend failure rather than returning a
degraded value. Every caller in the curator already wraps its LLM call in a
try/except that falls back (to template text, ``""``, ``[]``, or ``None``), so
raising here preserves each site's existing degradation contract instead of
inventing a new one.

The router backend is invoked as a subprocess (not an in-process import) on
purpose: the router lives in a separate deploy bundle / venv with its own heavy
deps (claude_patterns, chromadb, ollama client) that the curator venv does not
and should not carry. The CLI's ``--json`` contract (``{"answer","provenance"}``)
is the integration surface.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any, Callable, Optional


class RouterError(RuntimeError):
    """Raised when the router subprocess fails or returns an unusable result."""


def _anthropic_complete(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    temperature: float,
    api_key: str,
) -> str:
    """Direct Anthropic Messages API call. Byte-equivalent to the curator's
    historical inline calls (same args: model, max_tokens, system, single user
    message). Concatenates text blocks of the response."""
    import anthropic  # type: ignore

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts: list[str] = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


# Total attempts for a router call whose only defect was an empty ``answer``
# (see the retry note inside ``_router_complete``). 2 = one retry.
ROUTER_EMPTY_ANSWER_ATTEMPTS = 2


def _router_complete(
    *,
    system: str,
    user: str,
    allow_escalation: bool,
    settings: Any,
) -> str:
    """Run one completion through the K11 router CLI in task-mode.

    Writes BOTH ``system`` and ``user`` to temp files (``--system-file`` /
    ``--task-file``), invokes ``python -m router.cli --task --system-file <f>
    --task-file <g> [--no-escalate] --json``, parses the JSON, and returns the
    ``answer`` field. Passing the user message via a file (rather than inline on
    argv) is required: the bulk-inventory synthesizer prompt packs >1000
    catalogue entries into a single user message that overflows ARG_MAX
    (``OSError: [Errno 7] Argument list too long``) when passed as a CLI arg.
    Raises RouterError on any failure so the caller's existing fallback fires.
    """
    router_python = os.path.expanduser(settings.router_python)
    router_cwd = os.path.expanduser(settings.router_cli_cwd)
    timeout = float(settings.router_timeout_sec)

    sys_fd, sys_path = tempfile.mkstemp(prefix="curator_sys_", suffix=".txt")
    usr_fd, usr_path = tempfile.mkstemp(prefix="curator_usr_", suffix=".txt")
    try:
        with os.fdopen(sys_fd, "w", encoding="utf-8") as f:
            f.write(system)
        with os.fdopen(usr_fd, "w", encoding="utf-8") as f:
            f.write(user)

        cmd = [
            router_python,
            "-m",
            "router.cli",
            "--task",
            "--system-file",
            sys_path,
            "--task-file",
            usr_path,
        ]
        if not allow_escalation:
            cmd.append("--no-escalate")
        cmd.append("--json")

        # An empty answer is the one router outcome that is usually
        # transient (gpt-oss emitting only its hidden reasoning channel and
        # running out of generation budget before the final channel). It is
        # retried once; every other failure mode raises on the first attempt
        # so a real outage still fails closed immediately.
        attempt = 0
        while True:
            attempt += 1
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=router_cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise RouterError(f"router timed out after {timeout}s") from exc
            except OSError as exc:
                raise RouterError(f"router launch failed: {exc}") from exc

            if proc.returncode != 0:
                raise RouterError(
                    f"router exited {proc.returncode}: {proc.stderr.strip()[:500]}"
                )

            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                raise RouterError(
                    f"router emitted non-JSON: {proc.stdout.strip()[:500]}"
                ) from exc

            answer = payload.get("answer", "")
            if isinstance(answer, str) and answer.strip():
                return answer

            tier = (payload.get("provenance") or {}).get("tier", "?")
            if attempt < ROUTER_EMPTY_ANSWER_ATTEMPTS:
                print(
                    f"[llm_client] router returned empty answer (tier={tier}); "
                    f"retrying ({attempt}/{ROUTER_EMPTY_ANSWER_ATTEMPTS})"
                )
                continue
            raise RouterError(
                f"router returned empty answer (tier={tier}) "
                f"after {attempt} attempts"
            )
    finally:
        for path in (sys_path, usr_path):
            try:
                os.unlink(path)
            except OSError:
                # Temp file already gone / unlinkable — nothing actionable; the
                # tempdir is cleaned by the OS regardless.
                pass


def llm_complete(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    temperature: float = 0.0,
    allow_escalation: bool = True,
    settings: Any,
) -> str:
    """Single LLM-completion entry point for the curator pipeline.

    Dispatches on ``settings.llm_backend``:
      * ``"router"`` → :func:`_router_complete` (local-first, capped cloud
        fallback gated by ``allow_escalation``). ``model``/``max_tokens``/
        ``temperature`` are not forwarded — the router owns its own model
        selection and budgets.
      * anything else (default ``"anthropic"``) → :func:`_anthropic_complete`,
        byte-equivalent to the curator's prior inline calls.

    Raises on any failure (no silent degradation); callers wrap with their own
    fallback.
    """
    if getattr(settings, "llm_backend", "anthropic") == "router":
        return _router_complete(
            system=system,
            user=user,
            allow_escalation=allow_escalation,
            settings=settings,
        )

    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("anthropic backend selected but anthropic_api_key is empty")
    return _anthropic_complete(
        system=system,
        user=user,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        api_key=api_key,
    )


def make_router_llm_call(
    settings: Any,
    *,
    allow_escalation: bool,
) -> Callable[[str, str, str], str]:
    """Build an ``llm_call(system_prompt, user_prompt, model) -> str`` adapter
    for the subvurs_impact scorer's injectable seam.

    The scorer calls ``llm_call(system_prompt, user_prompt, model)`` and expects
    a plain string back (or an exception, which it converts to a fail-closed
    0.0 ScoreReport). This adapter routes that call through the K11 router with
    the supplied escalation policy (the per-article scorer uses
    ``allow_escalation=False`` — local-only, fail-closed bulk).
    """

    def _llm_call(system_prompt: str, user_prompt: str, model: str) -> str:
        # ``model`` is accepted to match the scorer's seam signature but is not
        # forwarded: the router owns model selection in task-mode.
        return _router_complete(
            system=system_prompt,
            user=user_prompt,
            allow_escalation=allow_escalation,
            settings=settings,
        )

    return _llm_call
