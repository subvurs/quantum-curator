"""Subvurs-impact scoring shared module.

A single, comparable, sortable, Goodhart-resistant numerical
Subvurs-impact score for items observed by the Quantum Curator and
Quantum Intel pipelines.

Design: SUBVURS_IMPACT_SCORING_PROPOSAL_20260602.txt
Status: v0.1 — Phase A (this module + tests, no pipeline integration).

Public API:
    from subvurs_impact import score_item, ScoreReport
    from subvurs_impact.path_catalog import PATHS, build_prompt
    from subvurs_impact.donotuse import PHRASES, CONCEPT_TAGS

Per the proposal, fail-closed is the invariant: any failure path
returns score=0.0 with fail_reason set, never 1.0.
"""

from .schema import (
    GateVerdict,
    PathMatch,
    RubricWeights,
    ScoreReport,
)
from .gates import (
    DoNotUseGate,
    EvidenceUnknownGate,
    NoveltyDuplicateVeto,
    apply_gates,
)
from .scorer import (
    DEFAULT_WEIGHTS,
    SCORER_VERSION,
    score_components,
    score_item,
)

__all__ = [
    "DEFAULT_WEIGHTS",
    "DoNotUseGate",
    "EvidenceUnknownGate",
    "GateVerdict",
    "NoveltyDuplicateVeto",
    "PathMatch",
    "RubricWeights",
    "SCORER_VERSION",
    "ScoreReport",
    "apply_gates",
    "score_components",
    "score_item",
]
