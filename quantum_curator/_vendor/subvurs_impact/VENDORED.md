# subvurs_impact (vendored)

Verbatim copy of the shared Subvurs-impact scorer from the Subvurs
research tree. This package is intentionally re-housed inside
`quantum_curator._vendor` so the Curator runs self-contained on
GitHub Actions Linux runners (and any other host that does not have
`/Users/mvm/Desktop/subvurs/blackbox/shared/` on disk).

## Source

| Field | Value |
|-------|-------|
| Upstream repo | `subvurs` (private) |
| Upstream path | `blackbox/shared/subvurs_impact/` |
| Upstream commit | `8b106f8706f07f4612746c952bfdf186b205dce7` |
| Vendored at | 2026-06-06 |
| Vendored version | `subvurs_impact_v0.1` (see `scorer.SCORER_VERSION`) |
| Vendored by | Mark Eatherly |

## Design reference

`SUBVURS_IMPACT_SCORING_PROPOSAL_20260602.txt` in the Subvurs tree.
Status: v0.1 (Phase A shipped; Phase B integration into Curator is
this directory's reason for existing).

## Files vendored

- `__init__.py` — public API re-exports
- `schema.py` — Pydantic `ScoreReport`, `RubricWeights`, `PathMatch`,
  `GateVerdict`
- `path_catalog.py` — the 11 commercialization paths + core-theory
  hooks used by the LLM rubric
- `donotuse.py` — concept tags + cited-phrase deny-list that powers
  the `DoNotUseGate`
- `gates.py` — `apply_gates` + the three gate implementations
  (`DoNotUseGate`, `EvidenceUnknownGate`, `NoveltyDuplicateVeto`)
- `scorer.py` — `score_item` (LLM entry point), `score_components`
  (deterministic entry point), fail-closed plumbing
- `README.md` — upstream README, preserved as documentation

## What was NOT vendored

- `tests/` — upstream test suite stays in the source tree; this
  vendor copy is exercised by `tests/test_curator_subvurs_impact.py`
  in the Curator repo
- `__pycache__/` — bytecode never travels in vendored copies

## Policy

Treat this directory as **read-only**. Do not edit vendored files
in-place; if the upstream module needs a change, edit it in
`subvurs/blackbox/shared/subvurs_impact/`, ship a new
`SCORER_VERSION`, and re-run the vendoring step (see below).

## Re-vendoring procedure

When upstream ships a new version:

```bash
# from the quantum-curator repo root
rm -rf quantum_curator/_vendor/subvurs_impact
cp -R /Users/mvm/Desktop/subvurs/blackbox/shared/subvurs_impact \
      quantum_curator/_vendor/
rm -rf quantum_curator/_vendor/subvurs_impact/__pycache__
rm -rf quantum_curator/_vendor/subvurs_impact/tests
# Then update this file's Source table (commit + date) and bump
# the Vendored version row to match the new SCORER_VERSION.
```

After re-vendoring, run the integration test:

```bash
pytest tests/test_curator_subvurs_impact.py -v
```

The `prompt_template_hash` baked into each `ScoreReport` is the
on-disk drift detector — if the upstream prompt changes, the test
suite's golden replays will fail and force an explicit acknowledgment.
