"""Single source of truth for the Subvurs path catalog.

Ported from quantum-curator/quantum_curator/curator.py:37-86
(SUBVURS_NOTES_SYSTEM_PROMPT) on 2026-06-05. Both pipelines
(Quantum Curator and Quantum Intel) read from here; updates land
in one place.

Structure: each path is a dict with a stable `key` (slug), a `name`,
the `version` / status snapshot, the `summary` block, and the
`relevant` tag-line that the scorer LLM uses to decide MatchScore.

The CORE_THEORY block stays distinct from commercial paths because
matching the core-theory section earns MatchScore = 0.4 (per §2.4)
not 0.7 / 1.0. As of v0.2.0 the block is HISTORICAL: the July 2026
falsification series (out-of-sample landmark test, CV_MAX audit,
matched-noise re-run, Impax mechanism reattribution) retired the
headline claims. Core-theory matches now score the *intersection*
(shared problem domain / methodology), never the claim itself.
"""

from __future__ import annotations

from typing import Iterable

PATH_CATALOG_VERSION = "v0.2.0-20260714"


# HISTORICAL CORE THEORY — falsified / retracted, do not cite as findings.
# Retained so the scorer can recognize when an external item touches the
# same problem space; the 0.4 match tier scores that intersection, not
# the (retired) claim. Every entry names its falsification record.
CORE_THEORY: dict[str, str] = {
    "nyx_equation": (
        "Ψ(c,p,n) = 100c² × [(1-p) + p×exp(-50(d-0.504)²)] × Ψ_n(n), "
        "with d = p/(c+ε). HISTORICAL: the d=0.504 peak is a chosen "
        "Gaussian centre in the equation, not a discovered landmark — "
        "the Jul 9, 2026 out-of-sample landmark test (BUILT_IN_CONFIRMED, "
        "OUT_OF_SAMPLE_LANDMARK_FINDINGS.md) found zero of eight "
        "classifier-independent observables peaking near d≈0.5."
    ),
    "chaos_valley_band": (
        "HISTORICAL: the Apr 25, 2026 117k-trial 'structured-emergence "
        "band' claim is retracted/reduced. Cross-c uniformity retracted "
        "Jun 16, 2026 (matched-noise re-run, LOOPHOLE_CONFIRMED: c=0.5 "
        "band 70.5%→0.0%). The strict classifier's coherence/attractor "
        "gates are decorative (Jul 9, 2026 CV_MAX audit, "
        "DECORATIVE_GATE_CONFIRMED: cond 5 fires on 0.13% of "
        "rejections). The d=0.6 'cliff' is tautological in static "
        "dynamics (d_eff ≡ p/c is constant per trial). Do not cite the "
        "band, the 0.504 peak, or the cliff as discovered findings."
    ),
    "time_symmetry": (
        "T = 0.857 time-symmetry constant (73.4% deterministic + 26.6% "
        "stochastic). Retained as an operating parameter / context "
        "only — not a validated physical constant."
    ),
    "inverse_scaling": (
        "HISTORICAL framing: 'Nyx-class optimizers avoid barren "
        "plateaus via non-gradient construction.' NyxSolver is NOT "
        "competitive vs classical baselines (Gurobi) on knapsack; "
        "treat inverse-scaling as a per-benchmark observation, not a "
        "general property."
    ),
    "pattern_51_126": (
        "HISTORICAL: Pattern 51 'zero-point-energy extraction "
        "signatures' are unsupported — do not cite. Pattern 126's "
        "46.1% coherence stands only as a raw hardware measurement. "
        "The 67-69-76 triad error-correction hypothesis was disproved "
        "Mar 2026."
    ),
    "impax_sensing": (
        "HISTORICAL: the Impax '43x vs quantum sensing' figure is NOT "
        "a sensing advantage (mixed evidence class; denominator ≈ NISQ "
        "decoherence noise floor). Jul 2026 mechanism finding: the real "
        "sensing primitive is the tanh saturating nonlinearity in "
        "impulsive/non-Gaussian noise (textbook robust detection, "
        "Kassam 1988); the consensus-coupling architecture is "
        "statistically null for detection. Robust-detection "
        "intersections are live; the 43x claim is not."
    ),
    "bidirectional_coupling": (
        "~21% error-mitigation gain via forward+reverse feedback "
        "(general framing only — problem-specific, not a universal "
        "constant)."
    ),
}


# Cross-corpus intersection surfaces — the LIVE way to connect an
# external item to Subvurs beyond a single commercial path. When an item
# touches one of these, the note should state what the intersection
# OPENS UP (an experiment to run, a claim to audit, a transferable
# technique) against the 310k+ document corpus — never what it
# "validates".
CROSS_CORPUS_INTERSECTIONS: dict[str, str] = {
    "wirecut_variance_reduction": (
        "wire-cutting / quasi-probability variance reduction (Qfabric "
        "v0.4-v0.5: stratified sampling, control variates, "
        "Rao-Blackwellization; γ⁶ realization-weight floor is the open "
        "bottleneck) — new estimator or IS techniques are directly "
        "transferable."
    ),
    "qkd_finite_key_coexistence": (
        "QKD finite-key analysis and classical coexistence (QCert EAT "
        "pipeline; NyxFiber SKR-gated scheduling on shared fiber) — "
        "new finite-key bounds, Raman/FWM models, or coexistence field "
        "data feed both audits and schedulers."
    ),
    "gamma_estimation": (
        "decoherence-rate (γ) / T1-T2 estimation under shot noise "
        "(Questimator: 9000-trial benchmark + ibm_marrakesh/ibm_fez "
        "pilots) — new estimators are benchmarkable against the "
        "existing (k, N_shot) grid."
    ),
    "qldpc_decoding": (
        "qLDPC / BB-code decoding and erasure conversion (Qalyx BP+OSD "
        "kernel, HERALDED_ERASE DEM wiring) — decoder or noise-model "
        "advances are testable in the existing harness."
    ),
    "robust_detection": (
        "robust detection in non-Gaussian / impulsive noise (the real "
        "Impax primitive: tanh saturating nonlinearity, Kassam 1988 "
        "lineage) — locally-optimal detector literature and ε-mixture "
        "noise models extend the Jul 2026 mechanism finding."
    ),
    "goodhart_evaluation": (
        "Goodhart-resistant evaluation of optimizers/agents (gh_eval: "
        "fail-closed gates, static-point/stiffness/saturation guards, "
        "judge-veto patterns in nyx_discovery) — new reward-hacking or "
        "eval-gaming results map onto the gate catalog."
    ),
    "benchmark_classifier_audit": (
        "benchmark / classifier-audit methodology (the July 2026 "
        "falsification series: fail_reason decomposition, out-of-sample "
        "landmark tests, matched-noise controls, decorative-gate "
        "detection) — auditing techniques from external work are "
        "reusable on Subvurs classifiers, and vice versa."
    ),
}


PATHS: dict[str, dict] = {
    "qfabric": {
        "key": "qfabric",
        "name": "Qfabric",
        "track": "path_a",
        "version": "v0.4.0 (May 25, 2026)",
        "summary": (
            "vendor-neutral cross-vendor quantum compute fabric. 14-gate "
            "IR + Qiskit/Cirq frontends + Piveteau-Sutter CX gate-cut + "
            "wire-cut LCU. Hardware validated: 2-Bell-pair split across "
            "IBM Fez + IBM Kingston, TVD 0.0894 at 4096 shots. Option B "
            "cross-CZ routing via two wire-cuts (γ²=25/CX) shipping; "
            "cross-SWAP (γ⁶=15625) deferred to v0.5 with "
            "Rao-Blackwellization. v0.4 adds variance-reduction toolkit "
            "(stratified per-site sampling, antithetic prep-branch, "
            "handler-product control variate)."
        ),
        "relevant": (
            "circuit knitting, distributed quantum computing, "
            "quasi-probability decomposition, gate cutting, wire cutting, "
            "LCU, IBM/IonQ/Quantinuum/Rigetti multi-backend orchestration, "
            "magic resource accounting, variance reduction for "
            "quasi-probability estimators."
        ),
    },
    "nyxchem": {
        "key": "nyxchem",
        "name": "NyxChem",
        "track": "path_b",
        "version": "commercial wrap of nyx_chem_service",
        "summary": (
            "Hartree–Fock/CCSD/CCSD(T) ground-state energies on 7 "
            "molecules (H2, LiH, H2O, BeH2, HCOOH, Pyrrole, Benzene) "
            "against PySCF, median 0.07% error; inverse-scaling visible "
            "(60q Benzene < 2q H2)."
        ),
        "relevant": (
            "quantum chemistry benchmarks, VQE-replacement claims, "
            "electronic structure, basis-set sweeps, PySCF/Qiskit-Nature/"
            "PennyLane-Chem, molecular dynamics circuits, Langevin "
            "thermostats."
        ),
    },
    "nyxnet": {
        "key": "nyxnet",
        "name": "NyxNet",
        "track": "path_c",
        "version": "66/66 tests; ~50-node MVP cap",
        "summary": (
            "distributed quantum networking control plane (planner, "
            "scheduler, repeater, distillation, Werner-state memory). "
            "Anchor: arXiv:2604.13964v1 (paper-136 reference "
            "benchmarked). No NetSquid/SeQUeNCe integration. Aliro "
            "comparison qualitative only."
        ),
        "relevant": (
            "quantum repeaters, entanglement distillation, QKD network "
            "routing, memory dimensioning, paper-136-style memory-aware "
            "planning, fidelity-aware routing primitives, "
            "store-and-forward quantum networks."
        ),
    },
    "questimator": {
        "key": "questimator",
        "name": "Questimator",
        "track": "path_c",
        "version": "hardware pilots ibm_marrakesh + ibm_fez",
        "summary": (
            "classical-Nyx γ (decoherence-rate) estimator for NyxNet. "
            "Werner F(t) = 1/4 + (F₀-1/4)·exp(-γt). 9000-trial "
            "benchmark wins every (k, N_shot) cell vs MLE/log-linear "
            "LS/EKF/Bayes-MCMC; 45% global median-log-error reduction "
            "vs Bayes-MCMC. Hardware pilot trail: ibm_marrakesh 6q "
            "(Apr 22 — initial inverse-scaling gate failed +0.886 due "
            "to γ-grid mismatch; QuestimatorConfig.hardware() restored "
            "to -0.35); ibm_fez 10q (Apr 27 — correlation -0.63, 9/10 "
            "per-qubit win)."
        ),
        "relevant": (
            "T1/T2 fitting, channel tomography, fidelity decay "
            "estimation, MLE/EKF/Bayes-MCMC γ recovery, ML-augmented "
            "rate inference, small-shot biased-MLE regime."
        ),
    },
    "qcert": {
        "key": "qcert",
        "name": "QCert",
        "track": "path_d",
        "version": "v0.1.0 (Apr 24, 2026); 59/59 tests; dev signing key",
        "summary": (
            "Nyx-FREE classical info-theoretic certification auditor for "
            "QKD deployments. BB84 decoy-state + MDI-QKD; one-shot audit "
            "pipeline (calibration → DEM → EAT finite-key bound → "
            "leftover hash → Ed25519-signed artifact, RFC 8785 canonical "
            "JSON). Benchmark within 7–30% of infinite-decoy references "
            "at loss < 20 dB (structural three-intensity gap). "
            "References: arXiv:2604.21791v1 (EAT), Lo-Ma-Chen 2005, "
            "Curty et al. 2014."
        ),
        "relevant": (
            "QKD certification, finite-key analysis, entropy "
            "accumulation, BB84/MDI/decoy-state, regulatory compliance "
            "for quantum-secure deployments, formal verification of "
            "quantum protocols, QML attack-surface catalogs."
        ),
    },
    "qalyx": {
        "key": "qalyx",
        "name": "Qalyx",
        "track": "path_e",
        "version": "v0.9.3 (May 13, 2026); 550+/550+ tests",
        "summary": (
            "vendor-neutral qLDPC decoder library. Rust BP+OSD kernel "
            "(byte-identical since v0.2.0); BB-code circuit-level noise "
            "via depth-7 Bravyi schedule; PyMatching MWPM cross-check; "
            "QHAL v0.1.1 latency vocabulary adopted (Qalyx self-IDs L3 "
            "batch/offline). Multi-vendor calibration loaders (IBM, "
            "IonQ, Quantinuum, QuEra, Pasqal, Oratomic, Atom Computing, "
            "Infleqtion); per-qubit/per-pair DEM priors; VF2 "
            "topology-aware placement fail-closed. HERALDED_ERASE wired "
            "into DEM (LER 2.00% → 0.70% at p=1.5e-2 + atom_loss=5e-2). "
            "Hardware honesty: two prior live LER ≈ 0.5 results "
            "reclassified as off-roadmap (BB codes need degree-6, plain "
            "Heron is degree-3 heavy-hex)."
        ),
        "relevant": (
            "qLDPC, BB codes, BP+OSD, decoder benchmarks, neutral-atom "
            "erasure, Riverlane/Deltaflow QHAL, fault-tolerance "
            "overhead, IBM Quantum System Two, IBM Loon long-range "
            "coupler."
        ),
    },
    "qjoblake": {
        "key": "qjoblake",
        "name": "QJobLake",
        "track": "path_f",
        "version": "v0.3.0-dev (May 8, 2026); 96 tests",
        "summary": (
            "vendor-neutral quantum job + result lake. IBM Runtime / AWS "
            "Braket / Azure Quantum adapters (IonQ + Quantinuum "
            "reachable via Braket+Azure). Capture-at-submit via "
            "`autocapture` context manager; SQLite + JSON; three "
            "exit-code categories for adapter failure. Explicitly "
            "Nyx-FREE."
        ),
        "relevant": (
            "provenance, FAIR data for quantum, reproducibility tooling, "
            "multi-cloud quantum job tracking, vendor SDK signature "
            "drift."
        ),
    },
    "bioreg": {
        "key": "bioreg",
        "name": "bioreg",
        "track": "path_g",
        "version": "pre-alpha v0.0.3 (May 11, 2026)",
        "summary": (
            "anonymous biometric ownership registry. Layer 1 complete: "
            "236 pytest cases green; voice MFCC-128 extractor; "
            "Merkle-SHA256 commitments; Ed25519 signed append-only log; "
            "fuzzy extractor rs255-223-code-offset-v1 wired through "
            "ERROR_CAPACITY = 16 byte errors (with explicit "
            "cryptographic-soundness caveat: ~256 bits helper leakage "
            "vs ~30–80 bits voice min-entropy). Layer 2 ZK proof system "
            "(stark-fuzzy-v1) is a stub. PQ-ready signing dispatch."
        ),
        "relevant": (
            "NIST FIPS 203/204/205 PQC migration, ELVIS Act, NO FAKES "
            "Act, Denmark likeness law, voice cloning, ZK proof of "
            "biometric possession, fuzzy extractors, biometric data "
            "marketplaces, Worldcoin/Veridas/Vermillio/Loti."
        ),
    },
    "nyxfiber": {
        "key": "nyxfiber",
        "name": "NyxFiber",
        "track": "path_h",
        "version": "v0.0.3 literature-pass (May 15, 2026); planning only",
        "summary": (
            "QKD-classical coexistence opportunistic time-slot scheduler "
            "for shared fiber. Anchor paper: arXiv:2604.12982v1 "
            "(Chaudhary et al., Apr 14, 2026) — 80-channel WDM Monte "
            "Carlo, 45–65% unused-spectrum recovery, 3σ Reliability "
            "Horizon on Werner key reservoir, Bihill first-passage "
            "transition. Raman-physics anchor: Chapuran et al., NJP 11, "
            "105001 (2009). SKR formula set from Lo-Ma-Chen 2005 + "
            "Ma-Qi-Zhao-Lo 2005."
        ),
        "relevant": (
            "QKD-classical coexistence, opportunistic spectrum, Raman "
            "crosstalk, FWM in QKD, MCF field deployments, hollow-core "
            "QKD, CV-QKD over 120 km, FMF Raman models, OFC/ECOC "
            "coexistence papers, Toshiba QKD, ID Quantique, "
            "QuintessenceLabs, KDDI."
        ),
    },
    "qwashed": {
        "key": "qwashed",
        "name": "Qwashed",
        "track": "public_interest (NOT a commercial path)",
        "version": "v0.2 (post-§3.4 + §3.2 + §3.5 expansion)",
        "summary": (
            "free Apache-2.0 post-quantum hygiene platform for civil "
            "society. Two tools: (1) `qwashed audit` — HNDL exposure "
            "scoring + signed migration roadmap (NativeTlsProbe, "
            "PGP/S-MIME); (2) `qwashed vault` — local-only X25519 ‖ "
            "ML-KEM-768 KEM + Ed25519 ‖ ML-DSA-65 signatures. NIST FIPS "
            "203 / 204 standards-track only — no Nyx, no Chaos Valley. "
            "417 tests + 1 sslyze skip."
        ),
        "relevant": (
            "HNDL (harvest now, decrypt later), NIST PQC standards, "
            "civil-society security, TLS posture scanning, "
            "X25519/Kyber/Dilithium hybrid migration, OpenPGP / S-MIME "
            "modernization."
        ),
    },
    "hive_qstruct": {
        "key": "hive_qstruct",
        "name": "Hive Keyboard / Qstruct",
        "track": "blackbox/hive-keyboard",
        "version": "256/256 patterns at 100% fidelity (simulator)",
        "summary": (
            "deterministic quantum-state addressing. 1,175× vs QAOA on "
            "MaxCut at equal depth; hardware validation P51 65.75% raw "
            "/ 99.50% mitigated, P126 59.12% / 97.02%."
        ),
        "relevant": (
            "deterministic state preparation, addressing schemes, "
            "classical-to-quantum encoding alternatives to "
            "amplitude/angle/QRAM, qstruct-style spectral pipelines, "
            "neural QUBO embedders, unit-disk graph mappers."
        ),
    },
}


def all_paths() -> Iterable[dict]:
    """Iterate over the 11 commercial-path entries (excludes core theory)."""
    return PATHS.values()


def path_keys() -> list[str]:
    """Stable list of path keys for schema validation."""
    return list(PATHS.keys())


def build_prompt() -> str:
    """Build the SUBVURS_NOTES_SYSTEM_PROMPT-equivalent string.

    Curator's existing inline prompt is replaced by a call to this
    function so Quantum Intel doesn't have to maintain a separate copy.
    Output is byte-comparable in intent (not in exact whitespace) to
    curator.py:37-86 as of 2026-06-05.
    """
    lines = [
        "You are a research assistant identifying connections between "
        "quantum computing news and the Subvurs research program. "
        "Surface connections to active commercial paths first, "
        "cross-corpus intersections second. Core theory below is "
        "HISTORICAL context only.",
        "",
        "HISTORICAL CORE THEORY (Quasmology / Nyx) — falsified or "
        "retracted July 2026; do NOT cite these as findings. Use only "
        "to recognize when an article touches the same problem space:",
    ]
    for label, body in CORE_THEORY.items():
        lines.append(f"- {label}: {body}")
    lines.append("")
    lines.append(
        "ACTIVE COMMERCIAL PATHS (only surface if the article touches "
        "the same problem)"
    )
    lines.append("")
    for path in PATHS.values():
        lines.append(
            f"- {path['name']} ({path['track']}, {path['version']}): "
            f"{path['summary']} Relevant: {path['relevant']}"
        )
    lines.append("")
    lines.append(
        "CROSS-CORPUS INTERSECTIONS (when an article touches one of "
        "these, connect it to the 310k+ document corpus and state what "
        "the intersection OPENS UP — an experiment to run, a claim to "
        "audit, a transferable technique — never what it \"validates\")"
    )
    lines.append("")
    for label, body in CROSS_CORPUS_INTERSECTIONS.items():
        lines.append(f"- {label}: {body}")
    lines.append("")
    # DO-NOT-USE block is injected at prompt-build time from donotuse.py
    # to keep a single source of truth. Imported lazily to avoid a
    # circular import at module load.
    from .donotuse import build_donotuse_block
    lines.append(build_donotuse_block())
    lines.append("")
    lines.extend([
        "RULES",
        "- Connect to a commercial path FIRST when one applies; a "
        "cross-corpus intersection angle SECOND.",
        "- Core theory may be referenced only as falsified/historical "
        "context (e.g. \"same problem space as the retired chaos-valley "
        "band\"), never as a live finding.",
        "- State the evidence class of the article's claim where "
        "discernible (theory / simulation / hardware).",
        "- Return 1-3 sentences ONLY if a genuine, specific connection "
        "exists to a concept above.",
        "- Return exactly \"None\" if no clear connection exists. "
        "Default to None; do not force connections.",
        "- Be specific: name the Subvurs concept AND the article's "
        "element that links to it.",
        "- Never invoke a \"DO NOT USE\" framing even if the article "
        "seems to invite it.",
        "- This is for internal research notes, not public display.",
    ])
    return "\n".join(lines)
