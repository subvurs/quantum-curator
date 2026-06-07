"""Goodhart gates for Subvurs-impact scoring.

Three gates per proposal §4.2, all fail-closed:

    G_DNU  DoNotUseGate           MatchScore  -> 0.0
    G_EVU  EvidenceUnknownGate    final score -> clamp <= 0.30
    G_NDV  NoveltyDuplicateVeto   final score -> clamp <= 0.30

Design choice: gates operate on a dict-of-components + the
ScoreReport's metadata fields (paths_matched, cited_phrase,
evidence_class, novelty score). They do NOT call back into the LLM —
gate decisions are deterministic given a ScoreReport snapshot, so
they replay exactly under the golden-fixture tests.

Inspiration: gh_eval's static-point gates. Each gate emits a
GateVerdict (recording before/after values and rationale) so the
weekly digest in §7.5 can show gate-fire frequency over time.
"""

from __future__ import annotations

from dataclasses import dataclass

from .donotuse import matches_concept_tag, matches_phrase
from .schema import GateVerdict, PathMatch

# Clamp ceiling for the two non-DNU gates — proposal §4.2 phrasing
# "real connection but we can't safely act on it yet."
SOFT_CLAMP_CEILING = 0.30
NOVELTY_DUPLICATE_THRESHOLD = 0.1   # NoveltyScore <= this triggers G_NDV


@dataclass
class GateInputs:
    """Everything the gates need from a candidate ScoreReport draft.

    Kept as a small dataclass (not a Pydantic model) because gates
    operate on the in-flight scoring state, not the persisted artifact.
    """

    components: dict[str, float]      # mutable: match/evidence/novelty/action
    cited_phrase: str | None
    paths_matched: list[PathMatch]
    evidence_class: str               # "hardware" | "unknown" | ...
    weights: dict[str, float]         # for computing final score
    concept_tags: list[str] | None = None  # optional model-emitted tags


def _final_score(components: dict[str, float],
                 weights: dict[str, float]) -> float:
    """Weighted sum, clamped to [0, 1]."""
    s = sum(components.get(k, 0.0) * weights.get(k, 0.0) for k in weights)
    return max(0.0, min(1.0, s))


class DoNotUseGate:
    """G_DNU: ban-list match -> MatchScore = 0.0.

    Triggers if cited_phrase contains any donotuse.PHRASES substring,
    OR concept_tags references any donotuse.CONCEPT_TAGS slug. Zeros
    MatchScore without killing the other components — a duplicate of
    a falsified finding can still have evidence/novelty signal worth
    recording.
    """

    name = "DoNotUseGate"
    target = "MatchScore"

    def apply(self, inputs: GateInputs) -> GateVerdict:
        before = inputs.components.get("match", 0.0)

        phrase_hit = matches_phrase(inputs.cited_phrase)
        tag_hit = matches_concept_tag(inputs.concept_tags)

        if phrase_hit is None and tag_hit is None:
            return GateVerdict(
                name=self.name,
                target="MatchScore",
                fired=False,
                reason="no DNU phrase or concept-tag match",
                before=before,
                after=before,
            )

        inputs.components["match"] = 0.0
        reason_parts = []
        if phrase_hit is not None:
            reason_parts.append(f"phrase match: {phrase_hit!r}")
        if tag_hit is not None:
            reason_parts.append(f"concept-tag match: {tag_hit!r}")
        return GateVerdict(
            name=self.name,
            target="MatchScore",
            fired=True,
            reason="; ".join(reason_parts),
            before=before,
            after=0.0,
        )


class EvidenceUnknownGate:
    """G_EVU: evidence_class == 'unknown' -> clamp final <= 0.30.

    Distinguished from the legitimate 'theory' class. 'theory' earns
    EvidenceScore=0.2 honestly; 'unknown' means the scorer could not
    determine the evidence class at all (fail-closed default) and is
    not safe to surface above the RELATED band until reclassified.
    """

    name = "EvidenceUnknownGate"
    target = "final_score"

    def apply(self, inputs: GateInputs, current_final: float) -> tuple[GateVerdict, float]:
        if inputs.evidence_class != "unknown":
            return (
                GateVerdict(
                    name=self.name,
                    target="final_score",
                    fired=False,
                    reason=f"evidence_class={inputs.evidence_class}",
                    before=current_final,
                    after=current_final,
                ),
                current_final,
            )
        new_final = min(current_final, SOFT_CLAMP_CEILING)
        return (
            GateVerdict(
                name=self.name,
                target="final_score",
                fired=True,
                reason="evidence class unknown — clamped to RELATED ceiling",
                before=current_final,
                after=new_final,
            ),
            new_final,
        )


class NoveltyDuplicateVeto:
    """G_NDV: NoveltyScore <= 0.1 -> clamp final <= 0.30.

    Catches items that are duplicates of existing findings. The match
    might be legitimate (high MatchScore, real evidence), but if we
    already have it we don't escalate.
    """

    name = "NoveltyDuplicateVeto"
    target = "final_score"

    def apply(self, inputs: GateInputs, current_final: float) -> tuple[GateVerdict, float]:
        novelty = inputs.components.get("novelty", 0.0)
        if novelty > NOVELTY_DUPLICATE_THRESHOLD:
            return (
                GateVerdict(
                    name=self.name,
                    target="final_score",
                    fired=False,
                    reason=f"novelty={novelty:.2f} > {NOVELTY_DUPLICATE_THRESHOLD}",
                    before=current_final,
                    after=current_final,
                ),
                current_final,
            )
        new_final = min(current_final, SOFT_CLAMP_CEILING)
        return (
            GateVerdict(
                name=self.name,
                target="final_score",
                fired=True,
                reason=(
                    f"novelty={novelty:.2f} <= duplicate threshold "
                    f"{NOVELTY_DUPLICATE_THRESHOLD} — clamped to "
                    f"RELATED ceiling"
                ),
                before=current_final,
                after=new_final,
            ),
            new_final,
        )


def apply_gates(inputs: GateInputs) -> tuple[float, list[GateVerdict]]:
    """Run all three gates in proposal §4.2 order, return (final, verdicts).

    Order matters: DNU runs first (it modifies a component), then the
    final score is computed, then the two clamp gates check the
    candidate final score.
    """
    verdicts: list[GateVerdict] = []

    dnu_verdict = DoNotUseGate().apply(inputs)
    verdicts.append(dnu_verdict)

    final = _final_score(inputs.components, inputs.weights)

    evu_verdict, final = EvidenceUnknownGate().apply(inputs, final)
    verdicts.append(evu_verdict)

    ndv_verdict, final = NoveltyDuplicateVeto().apply(inputs, final)
    verdicts.append(ndv_verdict)

    return final, verdicts
