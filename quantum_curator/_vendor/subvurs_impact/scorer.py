"""Subvurs-impact scorer — one LLM call, JSON output, gated.

Two entry points:

    score_components(...)   deterministic, takes pre-decided
                            components + metadata. Used by golden-
                            replay tests so the LLM is not in the
                            loop. Validates gates + final assembly.

    score_item(...)         production path. Calls Anthropic Claude
                            (Sonnet 4.5) with the path_catalog +
                            DO-NOT-USE prompt block, parses the
                            structured JSON block, then routes
                            through score_components.

Fail-closed: if the LLM call errors, JSON parsing fails, or any
component is out of range, score_item returns a ScoreReport with
score=0.0 and fail_reason set. Never raises.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from .donotuse import DONOTUSE_VERSION, build_donotuse_block
from .gates import GateInputs, apply_gates
from .path_catalog import PATH_CATALOG_VERSION, build_prompt, path_keys
from .schema import (
    EvidenceClass,
    GateVerdict,
    NoveltyBasis,
    PathMatch,
    RubricWeights,
    ScoreReport,
)

SCORER_VERSION = "subvurs_impact_v0.1"
DEFAULT_SCORER_MODEL = "claude-sonnet-4-5"

DEFAULT_WEIGHTS = RubricWeights()


# --- Evidence and Novelty ladder lookups (proposal §2.4) ------------

_EVIDENCE_LADDER: dict[str, float] = {
    "hardware":      1.0,
    "noisy_sim":     0.8,
    "noiseless_sim": 0.6,
    "classical_sim": 0.4,
    "theory":        0.2,
    "unknown":       0.0,
}


def evidence_score(evidence_class: str) -> float:
    """Map evidence_class string to its ladder value. Unknown -> 0.0."""
    return _EVIDENCE_LADDER.get(evidence_class, 0.0)


# --- Component assembly --------------------------------------------

def score_components(
    *,
    match: float,
    evidence_class: EvidenceClass,
    novelty: float,
    actionability: float,
    paths_matched: list[PathMatch] | None = None,
    cited_phrase: str | None = None,
    concept_tags: list[str] | None = None,
    novelty_basis: NoveltyBasis = "unknown",
    weights: RubricWeights | None = None,
    scorer_model: str = "deterministic",
    prompt_template_hash: str = "n/a",
) -> ScoreReport:
    """Build a ScoreReport from pre-decided components.

    The LLM-free path. Validates inputs, runs gates, returns the
    fully-populated report. Used by tests + by callers that already
    know the components (e.g. backfill scripts that consume an
    existing structured rationale).

    Raises ValueError on out-of-range inputs (the caller's fault) —
    score_item() catches everything and converts to fail-closed.
    """
    if not 0.0 <= match <= 1.0:
        raise ValueError(f"match out of range: {match}")
    if not 0.0 <= novelty <= 1.0:
        raise ValueError(f"novelty out of range: {novelty}")
    if not 0.0 <= actionability <= 1.0:
        raise ValueError(f"actionability out of range: {actionability}")

    w = weights or DEFAULT_WEIGHTS
    e_val = evidence_score(evidence_class)

    components = {
        "match":         match,
        "evidence":      e_val,
        "novelty":       novelty,
        "actionability": actionability,
    }
    components_pre = dict(components)

    weights_dict = {
        "match":         w.match,
        "evidence":      w.evidence,
        "novelty":       w.novelty,
        "actionability": w.actionability,
    }

    gate_inputs = GateInputs(
        components=components,
        cited_phrase=cited_phrase,
        paths_matched=paths_matched or [],
        evidence_class=evidence_class,
        weights=weights_dict,
        concept_tags=concept_tags,
    )
    final, verdicts = apply_gates(gate_inputs)

    return ScoreReport(
        version=SCORER_VERSION,
        score=final,
        components_pre_gate=components_pre,
        components_post_gate=dict(components),
        weights=weights_dict,
        paths_matched=paths_matched or [],
        evidence_class=evidence_class,
        novelty_basis=novelty_basis,
        gates_fired=verdicts,
        cited_phrase=cited_phrase,
        scorer_model=scorer_model,
        prompt_template_hash=prompt_template_hash,
        path_catalog_version=PATH_CATALOG_VERSION,
        donotuse_version=DONOTUSE_VERSION,
    )


# --- LLM scorer ---------------------------------------------------

_SCORER_USER_PROMPT_TEMPLATE = """\
Score the following item for Subvurs-impact per the rubric below.

# ITEM
Title: {title}
Source: {source}
Summary: {summary}

# RUBRIC
Return ONLY a single JSON object with EXACTLY these keys:

{{
  "match": float in [0.0, 1.0],
  "evidence_class": one of "hardware" | "noisy_sim" | "noiseless_sim" \
| "classical_sim" | "theory" | "unknown",
  "novelty": float in [0.0, 1.0],
  "actionability": float in [0.0, 1.0],
  "paths_matched": [
    {{"path_key": "<one of {path_keys}>",
      "strength": float in [0.0, 1.0],
      "reason": "<one sentence>"}}
  ],
  "cited_phrase": "<~80 chars from the item that drove the match, or null>",
  "concept_tags": ["<short slugs labeling why you matched>"],
  "novelty_basis": "vs_inventory" | "vs_curator_db" | "external_search" \
| "unknown"
}}

# RUBRIC LADDERS
- match (per §2.4 MatchScore):
  1.0 = same exact problem AND technique as one path's current sprint
  0.7 = same problem class as a path
  0.4 = touches a historical/falsified core-theory topic (retracted
        July 2026); score the intersection, not the claim
  0.2 = domain-adjacent but no specific path
  0.0 = no match
- evidence_class: pick the highest-tier evidence the item supports.
  Unknown is fail-closed; only pick it if you genuinely cannot tell.
- novelty:
  1.0 = result not previously seen in Subvurs corpus
  0.7 = adjacent to existing finding but new angle
  0.4 = confirms existing Subvurs result independently
  0.1 = duplicative of work already in corpus
- actionability:
  1.0 = drop-in technique to reproduce now
  0.7 = citation candidate for active whitepaper
  0.4 = backlog candidate; informs future v0.x roadmap
  0.1 = awareness-only

Output JSON ONLY. No prose, no markdown fences.
"""


def _build_system_prompt() -> str:
    return build_prompt()


def _prompt_hash(system_prompt: str, user_template: str) -> str:
    """Hash the combined prompt so score drift triggers replay failure."""
    h = hashlib.sha256()
    h.update(system_prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(user_template.encode("utf-8"))
    return h.hexdigest()[:16]


def _fail_closed(reason: str,
                 cited_phrase: str | None = None) -> ScoreReport:
    """Build a fail-closed ScoreReport — score 0.0 with reason recorded."""
    return ScoreReport(
        version=SCORER_VERSION,
        score=0.0,
        components_pre_gate={
            "match": 0.0, "evidence": 0.0,
            "novelty": 0.0, "actionability": 0.0,
        },
        components_post_gate={
            "match": 0.0, "evidence": 0.0,
            "novelty": 0.0, "actionability": 0.0,
        },
        weights={
            "match":         DEFAULT_WEIGHTS.match,
            "evidence":      DEFAULT_WEIGHTS.evidence,
            "novelty":       DEFAULT_WEIGHTS.novelty,
            "actionability": DEFAULT_WEIGHTS.actionability,
        },
        paths_matched=[],
        evidence_class="unknown",
        novelty_basis="unknown",
        gates_fired=[],
        cited_phrase=cited_phrase,
        scorer_model=DEFAULT_SCORER_MODEL,
        prompt_template_hash="fail_closed",
        path_catalog_version=PATH_CATALOG_VERSION,
        donotuse_version=DONOTUSE_VERSION,
        fail_reason=reason,
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort: pull the first {...} JSON object out of LLM output."""
    # Strip leading/trailing code fences if any.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        # Greedy match outermost braces.
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        candidate = text[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _validate_paths(raw: list[dict] | None) -> list[PathMatch]:
    if not raw:
        return []
    valid_keys = set(path_keys()) | {"core_theory"}
    out: list[PathMatch] = []
    for r in raw:
        key = r.get("path_key", "")
        if key not in valid_keys:
            continue
        try:
            out.append(PathMatch(
                path_key=key,
                strength=float(r.get("strength", 0.0)),
                reason=str(r.get("reason", "")),
            ))
        except (TypeError, ValueError):
            continue
    return out


def score_item(
    item: dict[str, Any],
    *,
    weights: RubricWeights | None = None,
    llm_call=None,
    scorer_model: str = DEFAULT_SCORER_MODEL,
) -> ScoreReport:
    """Score a single inventory item / curated article. Fail-closed.

    `item` is expected to have `title`, `source`, `summary` keys at
    minimum (matches both Curator's RawArticle and Quantum Intel's
    inventory entry shape).

    `llm_call` is an injectable callable for tests/back-ends. Signature:
        llm_call(system_prompt: str, user_prompt: str, model: str) -> str
    Returns the raw model text. If None, uses the default Anthropic
    client (lazy-imported so the module loads without anthropic
    installed, useful for the deterministic test path).
    """
    system_prompt = _build_system_prompt()
    user_prompt = _SCORER_USER_PROMPT_TEMPLATE.format(
        title=item.get("title", ""),
        source=item.get("source", ""),
        summary=item.get("summary", ""),
        path_keys=", ".join(path_keys()),
    )
    template_hash = _prompt_hash(system_prompt,
                                 _SCORER_USER_PROMPT_TEMPLATE)

    if llm_call is None:
        try:
            llm_call = _default_llm_call
        except Exception as exc:  # pragma: no cover
            return _fail_closed(f"no llm available: {exc!r}")

    try:
        raw_text = llm_call(system_prompt, user_prompt, scorer_model)
    except Exception as exc:
        return _fail_closed(f"llm call error: {type(exc).__name__}: {exc}")

    parsed = _extract_json(raw_text or "")
    if parsed is None:
        return _fail_closed("llm output did not parse as JSON")

    try:
        match = float(parsed.get("match", 0.0))
        evidence_class = parsed.get("evidence_class", "unknown")
        novelty = float(parsed.get("novelty", 0.0))
        actionability = float(parsed.get("actionability", 0.0))
    except (TypeError, ValueError) as exc:
        return _fail_closed(f"component parse error: {exc}")

    paths_matched = _validate_paths(parsed.get("paths_matched"))
    cited_phrase = parsed.get("cited_phrase") or None
    concept_tags = parsed.get("concept_tags") or []
    novelty_basis_raw = parsed.get("novelty_basis", "unknown")
    if novelty_basis_raw not in (
        "vs_inventory", "vs_curator_db", "external_search", "unknown"
    ):
        novelty_basis_raw = "unknown"

    if evidence_class not in _EVIDENCE_LADDER:
        evidence_class = "unknown"

    # Clamp components into [0, 1] before handing to score_components
    # so a model going slightly out of range fails to a clamp, not a
    # fail-closed (component bugs should not zero out the whole score).
    match = max(0.0, min(1.0, match))
    novelty = max(0.0, min(1.0, novelty))
    actionability = max(0.0, min(1.0, actionability))

    try:
        report = score_components(
            match=match,
            evidence_class=evidence_class,
            novelty=novelty,
            actionability=actionability,
            paths_matched=paths_matched,
            cited_phrase=cited_phrase,
            concept_tags=concept_tags,
            novelty_basis=novelty_basis_raw,
            weights=weights,
            scorer_model=scorer_model,
            prompt_template_hash=template_hash,
        )
    except Exception as exc:  # final safety net
        return _fail_closed(f"score assembly error: {exc}", cited_phrase)

    return report


def _default_llm_call(system_prompt: str, user_prompt: str,
                      model: str) -> str:  # pragma: no cover
    """Lazy Anthropic client. Imported only when actually called."""
    import anthropic  # type: ignore

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    parts = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)
