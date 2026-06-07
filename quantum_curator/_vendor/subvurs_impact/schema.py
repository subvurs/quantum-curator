"""Pydantic schemas for Subvurs-impact scoring.

Persisted artifacts must round-trip JSON cleanly — Quantum Intel
will write `subvurs_impact_reports/<entry_id>.json` (proposal §6.2)
and Curator persists into a TEXT column (§5.2). Fail-closed defaults:
any default value here is the *safe* one (0.0 for scores, unknown for
evidence, None for cited_phrase, fail_reason None unless explicitly
set).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EvidenceClass = Literal[
    "hardware",
    "noisy_sim",
    "noiseless_sim",
    "classical_sim",
    "theory",
    "unknown",
]

NoveltyBasis = Literal[
    "vs_inventory",
    "vs_curator_db",
    "external_search",
    "unknown",
]

GateTarget = Literal["MatchScore", "final_score"]


class RubricWeights(BaseModel):
    """Component weights — must sum to 1.0 ± 1e-9 (proposal §2.3)."""

    model_config = ConfigDict(frozen=True)

    match: float = Field(default=0.40, ge=0.0, le=1.0)
    evidence: float = Field(default=0.25, ge=0.0, le=1.0)
    novelty: float = Field(default=0.20, ge=0.0, le=1.0)
    actionability: float = Field(default=0.15, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        total = self.match + self.evidence + self.novelty + self.actionability
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"RubricWeights must sum to 1.0; got {total:.12f}"
            )
        return self


class PathMatch(BaseModel):
    """One commercial-path (or core-theory) match with rationale."""

    path_key: str           # e.g. "qfabric", "nyxnet", "core_theory"
    strength: float = Field(ge=0.0, le=1.0)  # per §2.4 MatchScore ladder
    reason: str             # 1-sentence why


class GateVerdict(BaseModel):
    """Record of a gate firing (or not).

    Persisted on every ScoreReport so the gate-fire rate is observable
    over time (proposal §7.5 weekly digest).
    """

    name: str               # "DoNotUseGate", "EvidenceUnknownGate", ...
    target: GateTarget      # what was modified
    fired: bool             # True iff the gate condition was met
    reason: str             # human-readable explanation
    before: float | None = None  # value before clamp
    after: float | None = None   # value after clamp


class ScoreReport(BaseModel):
    """The persisted artifact (proposal §3.3).

    Round-trips JSON. Both Curator (TEXT column) and Quantum Intel
    (sidecar `subvurs_impact_reports/<entry_id>.json`) consume the
    same shape.
    """

    model_config = ConfigDict(frozen=False)

    version: str = "subvurs_impact_v0.1"

    score: float = Field(default=0.0, ge=0.0, le=1.0)
    components_pre_gate: dict[str, float] = Field(default_factory=dict)
    components_post_gate: dict[str, float] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)

    paths_matched: list[PathMatch] = Field(default_factory=list)

    evidence_class: EvidenceClass = "unknown"
    novelty_basis: NoveltyBasis = "unknown"

    gates_fired: list[GateVerdict] = Field(default_factory=list)
    cited_phrase: str | None = None

    scorer_model: str = "unknown"
    prompt_template_hash: str = "unset"
    path_catalog_version: str = "unset"
    donotuse_version: str = "unset"

    scored_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    fail_reason: str | None = None  # set iff score==0.0 via fail-closed

    @property
    def band(self) -> str:
        """Interpretive band per proposal §2.2."""
        s = self.score
        if s < 0.10:
            return "NO_CONNECTION"
        if s < 0.30:
            return "TANGENTIAL"
        if s < 0.55:
            return "RELATED"
        if s < 0.75:
            return "PATH-RELEVANT"
        if s < 0.90:
            return "HIGH_IMPACT"
        return "DIRECT_HIT"
