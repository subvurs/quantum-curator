"""Falsified / stale framings — Goodhart-gate source of truth.

Ported from quantum-curator/quantum_curator/curator.py:71-79 on
2026-06-05. The MQTE incident (May 26, 2026) showed that the LLM
will reach for these framings even when explicitly told not to —
"noise-enhanced computation as a Subvurs concept" surfaced despite
the rule, and that's the exact Goodhart leak the gate is designed
to catch.

Two flavors of match:

1. PHRASES: substring-match against the cited_phrase the scorer
   extracts. Case-insensitive, whitespace-collapsed. These are the
   actual surface-form strings that have leaked through before.

2. CONCEPT_TAGS: short slugs the scorer LLM uses to label why it
   matched a path. If the model emits one of these tags, the gate
   fires regardless of the surface phrasing.

The gate zeros MatchScore (per proposal §4.2 G_DNU) — Evidence,
Novelty, Actionability all retain their original values, because
a duplicate-of-falsified-framing finding can still be useful as
"do not re-investigate" data.
"""

from __future__ import annotations

DONOTUSE_VERSION = "v0.2.0-20260714"


PHRASES: list[str] = [
    # 67-69-76 triad as error-correction cycle — DISPROVED Mar 2026
    "67-69-76 triad",
    "67/69/76 triad",
    "triad error correction",
    "triad as error correction",
    "information coherence state machine",
    "triad cycle as error correction",
    # Noise-enhanced computation reattribution — May 2026
    "noise-enhanced computation as a subvurs",
    "noise enhanced computation as a subvurs",
    "pattern 76 noise resilience as a pattern property",
    "pattern 76's noise resilience",  # explicit MQTE leak surface
    "noise resilience driven by pattern identity",
    # Superseded codenames
    "dmc3",  # internal codename, superseded by NyxSolver/qstruct/NyxChem
    # Speculative composition numbers
    "144.9q×",
    "144.9q combined speedup",
    "iqas 144.9q",
    # Old VQE-speedup claim, superseded by 0.01% H2O vs PySCF
    "62× on h2o vs vqe",
    "62x on h2o vs vqe",
    # Bidirectional coupling fixed-number claim
    "21.3% improvement from bidirectional coupling",
    "21.3 percent improvement from bidirectional coupling",
    # NyxSolver-as-SOTA framing — NOT competitive vs Gurobi
    "nyxsolver as a sota optimizer",
    "nyxsolver state of the art optimizer",
    "nyxsolver beats gurobi",
    # July 2026 falsification series — chaos valley / cliff / band
    "chaos valley discovered",
    "d=0.504 discovered",
    "0.504 landmark discovered",
    "emergence peak at 0.504",
    "death threshold cliff confirmed",
    "structured emergence band across c",
    # Impax 43x sensing claim — NOT a sensing advantage (Jul 2026)
    "43x sensing",
    "43x quantum sensing advantage",
    "impax beats quantum sensing",
    # Pattern 51 zero-point energy — unsupported
    "zero-point energy extraction",
    "pattern 51 energy extraction",
    # Consensus coupling — statistically null for detection (Jul 2026)
    "consensus coupling advantage",
]


CONCEPT_TAGS: list[str] = [
    "triad_error_correction",
    "noise_enhanced_computation",
    "dmc3",
    "iqas_speedup",
    "h2o_vqe_speedup",
    "bidirectional_21_3",
    "nyxsolver_sota",
    # July 2026 additions
    "chaos_valley_discovered",
    "death_cliff_static",
    "impax_43x_sensing",
    "p51_zpe",
    "emergence_classifier_validated",
]


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())


def matches_phrase(text: str | None) -> str | None:
    """Return the first matching DNU phrase, or None.

    Substring match on whitespace-collapsed, lowercased text. The
    return value is the matched phrase (for GateVerdict.reason),
    not the surface span — verdicts cite the rule, then the
    original cited_phrase is preserved on ScoreReport.
    """
    if not text:
        return None
    norm = _normalize(text)
    for phrase in PHRASES:
        if _normalize(phrase) in norm:
            return phrase
    return None


def matches_concept_tag(tags: list[str] | None) -> str | None:
    """Return the first matching DNU concept tag from a list, or None."""
    if not tags:
        return None
    tag_set = {t.strip().lower() for t in tags if t}
    for forbidden in CONCEPT_TAGS:
        if forbidden in tag_set:
            return forbidden
    return None


def build_donotuse_block() -> str:
    """Render the DO-NOT-USE list for inclusion in the system prompt.

    Mirrors curator.py:71-79 phrasing closely enough that the LLM
    still recognizes the existing in-context guardrail.
    """
    return (
        "DO NOT USE — falsified or stale framings (March–July 2026 "
        "disproofs)\n"
        "- 67-69-76 triad as an \"error-correction cycle\" or "
        "\"information coherence state machine\" — DISPROVED on IBM "
        "Torino, March 2026. Recovery operators give ~0% fidelity; "
        "pattern labels reflect circuit complexity, not intrinsic "
        "quantum properties. Do NOT cite the triad as error correction.\n"
        "- \"Noise-enhanced computation\" / \"Pattern 76 noise "
        "resilience as a pattern property\" — REATTRIBUTED to circuit "
        "simplicity, not pattern identity. Pattern 0 matches or exceeds "
        "P76 noise resilience.\n"
        "- DMC3 — superseded internal codename. Use NyxSolver / qstruct "
        "/ NyxChem as appropriate.\n"
        "- IQAS \"144.9Q× combined speedup\" — speculative composition "
        "number, do not cite.\n"
        "- \"62× on H2O vs VQE\" — superseded by NyxChem's actual 0.01% "
        "H2O error against PySCF CCSD(T) reference; reframe as "
        "\"near-FCI ground-state accuracy\" not a VQE speedup.\n"
        "- \"21.3% improvement from bidirectional coupling\" — keep "
        "general framing only; the specific number was problem-specific, "
        "not a universal constant.\n"
        "- NyxSolver as a SOTA optimizer — it is NOT competitive vs "
        "Gurobi on knapsack; ridge tuning is an internal-best "
        "improvement only.\n"
        "- Chaos Valley d=0.504 as a \"discovered\" landmark — the peak "
        "is BUILT IN (a chosen Gaussian centre in the Master Equation), "
        "per the Jul 9, 2026 out-of-sample landmark test. Do NOT frame "
        "0.504 as discovered or the d=0.6 cliff as \"confirmed\" (it is "
        "tautological in static dynamics).\n"
        "- \"Structured emergence band across c\" — cross-c uniformity "
        "RETRACTED Jun 16, 2026 (matched-noise re-run); the strict "
        "classifier's coherence/attractor gates are decorative (CV_MAX "
        "audit, Jul 9, 2026).\n"
        "- Impax \"43x sensing\" / \"beats quantum sensing\" — NOT a "
        "sensing advantage (mixed evidence class; NISQ-decoherence "
        "denominator). The real primitive is the tanh nonlinearity in "
        "impulsive noise (Kassam 1988); consensus coupling is null for "
        "detection.\n"
        "- Pattern 51 \"zero-point energy extraction\" — unsupported; "
        "do not cite."
    )
