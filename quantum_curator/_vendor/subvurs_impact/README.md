# subvurs_impact

Shared, deterministic, gated scoring of external research items against
the Subvurs commercialization portfolio. Single source of truth consumed
by Quantum Curator and Quantum Intel so both pipelines apply the same
rubric, the same DO-NOT-USE list, and the same Goodhart gates.

Implements Phase A of
[`SUBVURS_IMPACT_SCORING_PROPOSAL_20260602.txt`](../../../SUBVURS_IMPACT_SCORING_PROPOSAL_20260602.txt)
— scorer + gates + golden-replay tests only, no pipeline integration
(Phases B/C land in separate PRs).

---

## Why this exists

Both pipelines were independently deciding what "relevant to Subvurs"
means. Drift was already happening: Quantum Intel rejected a NyxFiber
anchor paper as "off-topic"; the MQTE article surfaced a falsified
framing ("noise-enhanced computation as a Subvurs concept") despite an
explicit DO-NOT-USE rule. Front-end rejection lists would suppress
useful primitives. A back-end, decomposed score with gates lets a
high-MatchScore-but-falsified item still surface its evidence/novelty
signal as `RELATED` data instead of being deleted.

---

## Score shape

```
S = 0.40·MatchScore + 0.25·EvidenceScore + 0.20·NoveltyScore + 0.15·ActionabilityScore
```

`RubricWeights` is frozen and validated to sum to 1.0 ± 1e-9.

### Evidence ladder
| class           | value |
|-----------------|-------|
| `hardware`      | 1.0   |
| `noisy_sim`     | 0.8   |
| `noiseless_sim` | 0.6   |
| `classical_sim` | 0.4   |
| `theory`        | 0.2   |
| `unknown`       | 0.0   |

### Bands
| band            | range          |
|-----------------|----------------|
| NO_CONNECTION   | [0.00, 0.10)   |
| TANGENTIAL      | [0.10, 0.30)   |
| RELATED         | [0.30, 0.55)   |
| PATH-RELEVANT   | [0.55, 0.75)   |
| HIGH_IMPACT     | [0.75, 0.90)   |
| DIRECT_HIT      | [0.90, 1.00]   |

---

## Gates (proposal §4.2, all fail-closed)

| Gate                 | Trigger                          | Effect                          |
|----------------------|----------------------------------|---------------------------------|
| `DoNotUseGate`       | phrase/concept-tag in DNU list   | MatchScore → 0.0                |
| `EvidenceUnknownGate`| `evidence_class == "unknown"`    | final → clamp ≤ 0.30            |
| `NoveltyDuplicateVeto`| `novelty ≤ 0.1`                 | final → clamp ≤ 0.30            |

Gates run in §4.2 order: DNU first (mutates components), then the
weighted sum, then the two clamp gates. Every `ScoreReport` records
all three verdicts (fired or not) so the proposal §7.5 weekly digest
can show gate-fire frequency over time.

The DNU list is **inclusive of past leaks**: triad-as-error-correction
(disproved Mar 2026), "noise-enhanced computation as a Subvurs"
(reattributed May 2026 — the MQTE leak surface),
"NyxSolver as SOTA" framing, "62× on H2O vs VQE", DMC3 codename,
"144.9Q× speedup", and the "21.3% bidirectional" fixed number.

---

## Quick start

### Deterministic (no LLM)

```python
from subvurs_impact import score_components, PathMatch

report = score_components(
    match=0.7,
    evidence_class="noisy_sim",
    novelty=0.7,
    actionability=1.0,
    paths_matched=[
        PathMatch(path_key="qfabric", strength=0.4,
                  reason="magic-aware = per-partition T-count metadata"),
        PathMatch(path_key="qcert", strength=0.7,
                  reason="QML backdoor catalog feeds QCert v0.2 threat model"),
    ],
    cited_phrase="formal verification of QML adversarial robustness via QIBP",
    concept_tags=["formal_verification", "qml_certification"],
    novelty_basis="vs_inventory",
)
print(report.score, report.band)
# 0.77 HIGH_IMPACT
```

### LLM-backed (fail-closed)

```python
from subvurs_impact import score_item

report = score_item({
    "title":   "Adversarially robust QML certification via QIBP",
    "source":  "arXiv:2606.04321",
    "summary": "Formal interval-bound propagation for parameterized "
               "quantum circuits; demonstrates magic-aware "
               "transformations and a QML backdoor catalog.",
})
# Uses ANTHROPIC_API_KEY. On any failure (network, JSON parse, schema
# violation) returns score=0.0 with fail_reason set — never raises.
```

For tests, pass an `llm_call=` callable returning a JSON string so
no network access is required.

---

## Files

| File                | Purpose                                              |
|---------------------|------------------------------------------------------|
| `path_catalog.py`   | 11 commercial paths + CORE_THEORY block, `build_prompt()` |
| `donotuse.py`       | falsified-framing phrases + concept tags             |
| `schema.py`         | `RubricWeights`, `PathMatch`, `GateVerdict`, `ScoreReport` |
| `gates.py`          | 3 gates + `apply_gates()` pipeline                    |
| `scorer.py`         | `score_components()` (deterministic) + `score_item()` (LLM) |
| `tests/golden/fixtures.json` | 10 hand-scored fixtures, all bands + gate-fires |

---

## Reproducibility

Every persisted `ScoreReport` records:

- `version` — `subvurs_impact_v0.1`
- `path_catalog_version` — bumped when paths/summaries change
- `donotuse_version` — bumped when DNU phrases/tags change
- `prompt_template_hash` — SHA256[:16] of system + user prompt
- `scorer_model` — `claude-sonnet-4-5` by default
- `scored_at` — UTC timestamp
- `gates_fired` — all three verdicts with before/after values
- `fail_reason` — set iff score == 0.0 via fail-closed path

Any version bump should trigger a fresh golden-replay run.

---

## Tests

```bash
cd /Users/mvm/Desktop/subvurs/blackbox/shared
python3 -m pytest subvurs_impact/tests/ -v
```

**64 passing** (catalog validity 17, gates 19, scorer replay 28).

Golden-replay tolerance is 0.10 with a minimum of 8/10 fixtures within
tolerance. All 10 currently land in the correct band and 9 of 10 are
within tolerance of the hand-scored value.

---

## Roadmap (per proposal §8)

- **Phase A (this PR)**: scorer + gates + golden-replay tests, no
  pipeline integration. ✓
- **Phase B**: Quantum Curator integration — `SubvursImpactScorer`
  pluggable downstream of the dedup pass; writes `subvurs_impact_score`
  + `subvurs_impact_report` TEXT columns. Separate PR.
- **Phase C**: Quantum Intel cataloger integration —
  `subvurs_impact_reports/<entry_id>.json` sidecars on every catalog
  entry; brief synthesizer filters on `band >= RELATED`. Separate PR.
- **Phase D**: one-week observation. No action layer. Daily replay
  digest counts gate fires, band distribution, top-10 by score.
- **Phase E**: action layer — band-aware behavior in both pipelines
  (PATH-RELEVANT+ surface to briefs, RELATED files to backlog,
  TANGENTIAL/NO_CONNECTION drop silently).

---

## Non-goals

- This module **does not** filter, drop, or reject items. Bands are
  interpretive; the action layer is Phase E.
- This module **does not** call back into the LLM from gates. Gate
  decisions are deterministic given a `ScoreReport` snapshot so the
  golden replay is reproducible.
- No Nyx terminology, Chaos Valley constants, or Quasmology framing
  inside `subvurs_impact/`. The MatchScore ladder references paths by
  key, not by physics. Core theory lives in `path_catalog.CORE_THEORY`
  as a single match hook, not as the scoring axis.
