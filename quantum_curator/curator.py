"""AI-powered curation and commentary generation for Quantum Curator."""

from __future__ import annotations

import asyncio
import json as _json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic

from .config import get_settings
from .models import ContentTopic, CuratedPost, DailyDigest, PostStatus, RawArticle
from . import db

# --- subvurs_impact (Phase B per proposal §8) ---------------------------
# The shared scorer is vendored into `quantum_curator._vendor.subvurs_impact`
# so the Curator stays self-contained — the previous sys.path bootstrap
# pointed at /Users/mvm/Desktop/subvurs/, which is absent on the GitHub
# Actions runner that publishes the site. Provenance + re-vendoring
# procedure: `quantum_curator/_vendor/subvurs_impact/VENDORED.md`.
#
# Fail-closed: any import failure downgrades to "scoring disabled" and
# downstream curation continues without touching the impact fields.
try:
    from ._vendor.subvurs_impact import (  # type: ignore
        SCORER_VERSION as _IMPACT_VERSION,
        ScoreReport as _ImpactScoreReport,
        score_item as _impact_score_item,
    )
    _IMPACT_AVAILABLE = True
except Exception as _impact_err:  # noqa: BLE001 — fail-closed import
    print(f"subvurs_impact unavailable, scoring disabled: {_impact_err}")
    _IMPACT_AVAILABLE = False
    _IMPACT_VERSION = None  # type: ignore[assignment]
    _ImpactScoreReport = None  # type: ignore[assignment,misc]
    _impact_score_item = None  # type: ignore[assignment]


CURATOR_SYSTEM_PROMPT = """You are a quantum computing expert and science communicator who curates and comments on quantum computing news. You write engaging, accessible commentary that:

1. Explains why this article matters to the quantum computing field
2. Puts findings in context with recent developments
3. Highlights practical implications when relevant
4. Uses clear language accessible to tech-savvy readers
5. Shows genuine enthusiasm for breakthroughs while remaining scientifically grounded

Your commentary should be 2-4 sentences, informative yet concise. You are curating for {curator_name}'s quantum news site, so write in third person ("This article..." not "I think...").

Focus on:
- What's genuinely novel or significant
- How it connects to the broader quantum computing landscape
- Why readers should care
- Any caveats or context needed

IMPORTANT: Write in plain text only. Do NOT use any markdown formatting — no bold (**text**), no italics (*text*), no headers (#), no bullet points (- or *), and no code blocks. Your output will be displayed directly on a web page as plain prose."""


SUBVURS_NOTES_SYSTEM_PROMPT = """You are a research assistant identifying connections between quantum computing news and the Subvurs research program. Surface connections to any of the following — core theory OR active commercial paths.

CORE THEORY (Quasmology / Nyx)
- Nyx equation: Ψ(c,p,n) = 100c² × [(1-p) + p×exp(-50(d-0.504)²)] × Ψ_n(n), with d = p/(c+ε). Framework for structured emergence from quantum vacuum.
- Chaos Valley band: d ∈ [0.4, 0.6] is the structured-emergence band; d = 0.504 is the interior maximum; d = 0.6 is a hard cliff (117k-trial sweep, Apr 25, 2026). Maps to quantum phase-transition / critical-point physics.
- T = 0.857 time-symmetry constant (73.4% deterministic + 26.6% stochastic).
- Inverse scaling: Nyx-class optimizers' relative error decreases as problem size grows (avoids barren plateaus via non-gradient construction).
- Pattern 51 (0b110011): quantum-bridge pattern, demonstrated zero-point-energy extraction signatures; Pattern 126: highest measured coherence (46.1%).
- Bidirectional coupling: ~21% error-mitigation gain via forward+reverse feedback.

ACTIVE COMMERCIAL PATHS (only surface if the article touches the same problem)

- Qfabric (path_a): vendor-neutral cross-vendor quantum compute fabric. v0.3.0-dev (May 15, 2026). 14-gate IR + Qiskit/Cirq frontends + Piveteau-Sutter CX gate-cut + wire-cut LCU. Hardware validated: 2-Bell-pair split across IBM Fez + IBM Kingston, TVD 0.0894 at 4096 shots. Option B cross-CZ routing via two wire-cuts (γ²=25/CX) shipping; cross-SWAP (γ⁶=15625) infeasible without stratified per-site sampling, deferred to v0.4. Tests: 250 passed / 1 xfailed. Relevant articles: circuit knitting, distributed quantum computing, quasi-probability decomposition, gate cutting, wire cutting, LCU, IBM/IonQ/Quantinuum/Rigetti multi-backend orchestration.

- NyxChem (path_b): commercial wrap of nyx_chem_service. Hartree–Fock/CCSD/CCSD(T) ground-state energies on 7 molecules (H2, LiH, H2O, BeH2, HCOOH, Pyrrole, Benzene) against PySCF, median 0.07% error; inverse-scaling visible (60q Benzene < 2q H2). Relevant: quantum chemistry benchmarks, VQE-replacement claims, electronic structure, basis-set sweeps, PySCF/Qiskit-Nature/PennyLane-Chem.

- NyxNet (path_c): distributed quantum networking control plane (planner, scheduler, repeater, distillation, Werner-state memory). Anchor: arXiv:2604.13964v1 (paper-136 reference benchmarked). 66/66 tests green; ~50-node MVP cap. No NetSquid/SeQUeNCe integration. Aliro comparison qualitative only. Relevant: quantum repeaters, entanglement distillation, QKD network routing, memory dimensioning, paper-136-style memory-aware planning.

- Questimator (path_c): classical-Nyx γ (decoherence-rate) estimator for NyxNet. Werner F(t) = 1/4 + (F₀-1/4)·exp(-γt). 9000-trial benchmark wins every (k, N_shot) cell vs MLE/log-linear LS/EKF/Bayes-MCMC; 45% global median-log-error reduction vs Bayes-MCMC. Hardware pilot trail: ibm_marrakesh 6q (Apr 22 — initial inverse-scaling gate failed +0.886 due to γ-grid mismatch; QuestimatorConfig.hardware() restored to -0.35); ibm_fez 10q (Apr 27 — correlation -0.63, 9/10 per-qubit win). Relevant: T1/T2 fitting, channel tomography, fidelity decay estimation, MLE/EKF/Bayes-MCMC γ recovery.

- QCert (path_d): Nyx-FREE classical info-theoretic certification auditor for QKD deployments. BB84 decoy-state + MDI-QKD; one-shot audit pipeline (calibration → DEM → EAT finite-key bound → leftover hash → Ed25519-signed artifact, RFC 8785 canonical JSON). 59/59 tests passing; benchmark within 7–30% of infinite-decoy references at loss < 20 dB (structural three-intensity gap). References: arXiv:2604.21791v1 (EAT), Lo-Ma-Chen 2005, Curty et al. 2014. Dev signing key only. Relevant: QKD certification, finite-key analysis, entropy accumulation, BB84/MDI/decoy-state, regulatory compliance for quantum-secure deployments.

- Qalyx (path_e): vendor-neutral qLDPC decoder library. v0.9.3 (May 13, 2026). 550+/550+ tests. Rust BP+OSD kernel (byte-identical since v0.2.0); BB-code circuit-level noise via depth-7 Bravyi schedule; PyMatching MWPM cross-check; QHAL v0.1.1 latency vocabulary adopted (Qalyx self-IDs L3 batch/offline). Multi-vendor calibration loaders (IBM, IonQ, Quantinuum, QuEra, Pasqal, Oratomic, Atom Computing, Infleqtion); per-qubit/per-pair DEM priors; VF2 topology-aware placement fail-closed. HERALDED_ERASE wired into DEM (LER 2.00% → 0.70% at p=1.5e-2 + atom_loss=5e-2). Hardware honesty: two prior live LER ≈ 0.5 results reclassified as off-roadmap (BB codes need degree-6, plain Heron is degree-3 heavy-hex). Relevant: qLDPC, BB codes, BP+OSD, decoder benchmarks, neutral-atom erasure, Riverlane/Deltaflow QHAL, fault-tolerance overhead, IBM Quantum System Two, IBM Loon long-range coupler.

- QJobLake (path_f): vendor-neutral quantum job + result lake. v0.3.0-dev (May 8, 2026). 96 tests. IBM Runtime / AWS Braket / Azure Quantum adapters (IonQ + Quantinuum reachable via Braket+Azure). Capture-at-submit via `autocapture` context manager; SQLite + JSON; three exit-code categories for adapter failure. Explicitly Nyx-FREE. Relevant: provenance, FAIR data for quantum, reproducibility tooling, multi-cloud quantum job tracking, vendor SDK signature drift.

- bioreg (path_g): anonymous biometric ownership registry (pre-alpha, v0.0.3, May 11, 2026; "bioreg" working name, ViNIL Nashville occupies the adjacent celebrity-licensing acronym). Layer 1 complete: 236 pytest cases green; voice MFCC-128 extractor; Merkle-SHA256 commitments; Ed25519 signed append-only log; fuzzy extractor rs255-223-code-offset-v1 wired through ERROR_CAPACITY = 16 byte errors (with explicit cryptographic-soundness caveat: ~256 bits helper leakage vs ~30–80 bits voice min-entropy). Layer 2 ZK proof system (stark-fuzzy-v1) is a stub. PQ-ready signing dispatch. Relevant: NIST FIPS 203/204/205 PQC migration, ELVIS Act, NO FAKES Act, Denmark likeness law, voice cloning, ZK proof of biometric possession, fuzzy extractors, biometric data marketplaces, Worldcoin/Veridas/Vermillio/Loti.

- NyxFiber (path_h): QKD-classical coexistence opportunistic time-slot scheduler for shared fiber. v0.0.3 literature-pass (May 15, 2026 — planning artifacts only, no code yet). Anchor paper: arXiv:2604.12982v1 (Chaudhary et al., Apr 14, 2026) — 80-channel WDM Monte Carlo, 45–65% unused-spectrum recovery, 3σ Reliability Horizon on Werner key reservoir, Bihill first-passage transition. Raman-physics anchor: Chapuran et al., NJP 11, 105001 (2009) — 96-DWDM, anti-Stokes spontaneous Raman dominance, optimal quantum λ at position 88 (1533.4 nm) / 96 (1530.2 nm). SKR formula set from Lo-Ma-Chen 2005 + Ma-Qi-Zhao-Lo 2005 (GLLP decoy-state, GYS regime μ≈0.48, η_detector≈1e-3, 140 km reach). Closest academic competitor: arXiv:2505.05351 Ware & Lourdiane — planning-time only, complementary not competing. Commercial whitespace: no vendor ships an opportunistic time-slot QKD-classical scheduler as of May 2026 (Toshiba/IDQ/QuintessenceLabs all wavelength-domain). Open competitive risk: KDDI+Toshiba OFC 2025 Tu3D.2 static O/C-band split (33.4 Tb/s + QKD over 80 km) could eat the market if industry converges on dedicated-band separation. Relevant: QKD-classical coexistence, opportunistic spectrum, Raman crosstalk, FWM in QKD, MCF field deployments (Nature L:SA 2025 25.2 km 110.8 Tb/s), hollow-core QKD, CV-QKD over 120 km, FMF Raman models, OFC/ECOC coexistence papers, anything from Toshiba QKD / ID Quantique / QuintessenceLabs / KDDI quantum-network division.

- Qwashed (public_interest/qwashed, NOT a commercial path): free Apache-2.0 post-quantum hygiene platform for civil society (journalism, healthcare, legal aid, NGOs). v0.1.0 alpha. Two tools: (1) `qwashed audit` — HNDL exposure scoring + signed migration roadmap (NativeTlsProbe, PGP/S-MIME §3.4 + §3.2 + §3.5 added v0.2); (2) `qwashed vault` — local-only X25519 ‖ ML-KEM-768 KEM + Ed25519 ‖ ML-DSA-65 signatures. NIST FIPS 203 / 204 standards-track only — no Nyx, no Chaos Valley. 417 tests + 1 sslyze skip. Relevant: HNDL ("harvest now, decrypt later"), NIST PQC standards, civil-society security, TLS posture scanning, X25519/Kyber/Dilithium hybrid migration, OpenPGP / S-MIME modernization.

- Hive Keyboard / Qstruct (blackbox/hive-keyboard): deterministic quantum-state addressing. 256/256 patterns at 100% fidelity (simulator); 1,175× vs QAOA on MaxCut at equal depth; hardware validation P51 65.75% raw / 99.50% mitigated, P126 59.12% / 97.02%. Relevant: deterministic state preparation, addressing schemes, classical-to-quantum encoding alternatives to amplitude/angle/QRAM, qstruct-style spectral pipelines.

DO NOT USE — falsified or stale framings (March–May 2026 disproofs)
- 67-69-76 triad as an "error-correction cycle" or "information coherence state machine" — DISPROVED on IBM Torino, March 2026. Recovery operators give ~0% fidelity; pattern labels reflect circuit complexity, not intrinsic quantum properties. Do NOT cite the triad as error correction.
- "Noise-enhanced computation" / "Pattern 76 noise resilience as a pattern property" — REATTRIBUTED to circuit simplicity, not pattern identity. Pattern 0 matches or exceeds P76 noise resilience.
- DMC3 — superseded internal codename. Use NyxSolver / qstruct / NyxChem as appropriate.
- IQAS "144.9Q× combined speedup" — speculative composition number, do not cite.
- "62× on H2O vs VQE" — superseded by NyxChem's actual 0.01% H2O error against PySCF CCSD(T) reference; reframe as "near-FCI ground-state accuracy" not a VQE speedup.
- "21.3% improvement from bidirectional coupling" — keep general framing only; the specific number was problem-specific, not a universal constant.
- NyxSolver as a SOTA optimizer — it is NOT competitive vs Gurobi on knapsack; ridge tuning is an internal-best improvement only.

RULES
- Return 1-3 sentences ONLY if a genuine, specific connection exists to a concept above.
- Return exactly "None" if no clear connection exists. Default to None; do not force connections.
- Be specific: name the Subvurs concept AND the article's element that links to it.
- Never invoke a "DO NOT USE" framing even if the article seems to invite it.
- Prefer commercial-path connections (Qfabric/NyxChem/NyxNet/Questimator/QCert/Qalyx/QJobLake/bioreg/NyxFiber/Qwashed/Hive) over pure-theory connections — commercial paths are the live product surface.
- This is for internal research notes, not public display."""


DIGEST_SYSTEM_PROMPT = """You are creating a daily digest summary for {curator_name}'s quantum computing news site. Write a compelling 2-3 paragraph summary of today's quantum news highlights.

Structure your writing as flowing prose paragraphs:
- First paragraph: Opening hook — what is the most significant development today?
- Second paragraph: Key themes — what patterns or trends emerge from today's news?
- Third paragraph: Looking ahead — what should readers watch for?

Be engaging, informative, and accessible to tech-savvy readers interested in quantum computing.

IMPORTANT: Write in plain text only. Do NOT use any markdown formatting — no bold (**text**), no italics (*text*), no headers (#), no bullet points (- or *), and no code blocks. Write clean, professional prose paragraphs only. Your output will be displayed directly on a web page."""


def _strip_markdown(text: str) -> str:
    """Remove common markdown formatting from text.

    Safety net to ensure AI output renders as clean prose on the site,
    even if the model slips in markdown syntax despite prompt instructions.
    """
    # Remove bold: **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    # Remove italic: *text* or _text_ (but not underscores in words)
    text = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'\1', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)
    # Remove headers: # Header
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove bullet points at line start: - item or * item
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
    # Remove numbered list markers: 1. item
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Remove inline code: `code`
    text = re.sub(r'`(.+?)`', r'\1', text)
    # Remove code blocks: ```...```
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Clean up excess whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class Curator:
    """Generate AI commentary and curate articles."""

    def __init__(self):
        self.settings = get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    async def curate_article(self, article: RawArticle) -> CuratedPost:
        """Generate commentary for an article and create a curated post.

        Args:
            article: Raw article to curate

        Returns:
            CuratedPost with AI-generated commentary
        """
        # Generate commentary
        commentary = await self._generate_commentary(article)

        # Auto-generate image if missing and feature is enabled
        image_url = article.image_url
        if not image_url and self.settings.generate_images:
            from .image_generator import ensure_article_image

            image_url = await ensure_article_image(
                article,
                data_dir=self.settings.data_dir,
                base_url=self.settings.site_url,
            )

        # Generate Subvurs research connection notes
        subvurs_notes = ""
        if self.settings.generate_subvurs_notes:
            subvurs_notes = await self._generate_subvurs_notes(article)
            if subvurs_notes:
                self._save_subvurs_notes_file(article, subvurs_notes)

        # Phase B: deterministic Subvurs-impact score via shared scorer.
        # Independent of notes generation — even when notes is empty the
        # rubric still produces an interpretive band ("RELATED" data is
        # exactly the case proposal §1 says must not be silently dropped).
        impact_score = 0.0
        impact_report_json: str | None = None
        impact_version: str | None = None
        if (
            self.settings.subvurs_impact_scoring_enabled
            and _IMPACT_AVAILABLE
        ):
            report = await self._score_subvurs_impact(article)
            if report is not None:
                impact_score = float(report.score)
                # Pydantic v2 model_dump_json handles datetime + nested models.
                impact_report_json = report.model_dump_json()
                impact_version = report.version

        # Create curated post
        post = CuratedPost(
            article_id=article.id,
            title=article.title,
            original_url=article.url,
            source_name=article.source_name,
            summary=article.summary,
            image_url=image_url,
            curator_commentary=commentary,
            subvurs_notes=subvurs_notes,
            subvurs_impact_score=impact_score,
            subvurs_impact_report=impact_report_json,
            subvurs_impact_version=impact_version,
            topics=article.topics,
            relevance_score=article.relevance_score,
            curator_name=self.settings.curator_name,
            published_at=article.published_at,
            curated_at=datetime.utcnow(),
            status=PostStatus.DRAFT,
        )

        # Save to database
        db.save_curated_post(post)

        # Mark article as curated
        article.curated = True
        db.save_raw_article(article)

        return post

    async def curate_batch(
        self,
        articles: list[RawArticle],
        max_concurrent: int = 3,
    ) -> list[CuratedPost]:
        """Curate multiple articles with rate limiting.

        Args:
            articles: List of articles to curate
            max_concurrent: Maximum concurrent API calls

        Returns:
            List of curated posts
        """
        posts = []
        semaphore = asyncio.Semaphore(max_concurrent)

        async def curate_with_limit(article: RawArticle) -> CuratedPost | None:
            async with semaphore:
                try:
                    return await self.curate_article(article)
                except Exception as e:
                    print(f"Error curating '{article.title}': {e}")
                    return None

        tasks = [curate_with_limit(a) for a in articles]
        results = await asyncio.gather(*tasks)

        for result in results:
            if result:
                posts.append(result)

        return posts

    async def _generate_commentary(self, article: RawArticle) -> str:
        """Generate AI commentary for an article."""
        if not self.settings.anthropic_api_key:
            return self._generate_fallback_commentary(article)

        system_prompt = CURATOR_SYSTEM_PROMPT.format(
            curator_name=self.settings.curator_name
        )

        user_prompt = f"""Please write curator commentary for this quantum computing article:

Title: {article.title}
Source: {article.source_name}
Topics: {', '.join(t.value for t in article.topics)}

Summary:
{article.summary[:1500]}

Write 2-4 sentences of engaging commentary explaining why this matters."""

        try:
            # Use sync client in async context (anthropic handles this)
            response = self.client.messages.create(
                model=self.settings.claude_model,
                max_tokens=300,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return _strip_markdown(response.content[0].text.strip())
        except Exception as e:
            print(f"Claude API error: {e}")
            return self._generate_fallback_commentary(article)

    def _generate_fallback_commentary(self, article: RawArticle) -> str:
        """Generate simple commentary when AI is unavailable."""
        topic_str = article.topics[0].value if article.topics else "quantum computing"
        return (
            f"An interesting development in {topic_str}. "
            f"This article from {article.source_name} covers recent progress "
            f"that may have implications for the broader quantum computing field."
        )

    async def _generate_subvurs_notes(self, article: RawArticle) -> str:
        """Generate internal Subvurs research connection notes for an article."""
        if not self.settings.anthropic_api_key:
            return ""

        user_prompt = f"""Analyze this quantum computing article for connections to Subvurs/Quasmology research:

Title: {article.title}
Source: {article.source_name}
Topics: {', '.join(t.value for t in article.topics)}

Summary:
{article.summary[:1500]}

Return 1-3 sentences identifying a specific connection, or exactly "None" if no genuine connection exists."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=200,
                system=SUBVURS_NOTES_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            notes = response.content[0].text.strip()
            if notes.lower().startswith("none"):
                return ""
            return notes
        except Exception as e:
            print(f"Subvurs notes generation error: {e}")
            return ""

    async def _score_subvurs_impact(self, article: RawArticle):
        """Run the shared subvurs_impact scorer on an article.

        Returns the ScoreReport or None if scoring is unavailable.
        score_item() is already fail-closed (any failure returns a
        ScoreReport with score=0.0 + fail_reason set), so this wrapper
        only has to handle the "module not loaded" / "no API key" case.
        """
        if not _IMPACT_AVAILABLE or _impact_score_item is None:
            return None
        if not self.settings.anthropic_api_key:
            return None

        # Match the shape score_item expects (proposal §3.2 / §5.2).
        item = {
            "title": article.title,
            "source": article.source_name,
            "summary": article.summary[:1500],
        }

        # score_item is sync (single LLM call); offload to thread to
        # avoid blocking the event loop in batch curation.
        try:
            return await asyncio.to_thread(_impact_score_item, item)
        except Exception as exc:  # noqa: BLE001 — final safety net
            # score_item is fail-closed internally; anything reaching
            # here is a library-level bug. Log and degrade gracefully.
            print(f"subvurs_impact scoring crashed: {exc!r}")
            return None

    def _save_subvurs_notes_file(self, article: RawArticle, notes: str) -> Path:
        """Save subvurs notes to a text file in data/subvurs_notes/."""
        notes_dir = self.settings.data_dir / "subvurs_notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        date_str = (article.published_at or datetime.utcnow()).strftime("%Y-%m-%d")
        # Build a filename-safe slug from the title
        slug = re.sub(r"[^\w\s-]", "", article.title.lower())
        slug = re.sub(r"[\s_]+", "-", slug).strip("-")[:60]
        filename = f"{date_str}_{slug}.md"

        filepath = notes_dir / filename
        filepath.write_text(
            f"# {article.title}\n\n"
            f"**Source:** {article.source_name}\n"
            f"**URL:** {article.url}\n"
            f"**Date:** {date_str}\n\n"
            f"## Subvurs Connection\n\n"
            f"{notes}\n",
            encoding="utf-8",
        )
        return filepath

    async def create_daily_digest(
        self,
        date: datetime | None = None,
        posts: list[CuratedPost] | None = None,
    ) -> DailyDigest:
        """Create a daily digest from curated posts.

        Args:
            date: Date for the digest (default: today)
            posts: Posts to include (default: fetch from DB)

        Returns:
            DailyDigest object
        """
        if date is None:
            date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        if posts is None:
            posts = db.list_curated_posts(
                since=date,
                status=PostStatus.PUBLISHED,
            )

        if not posts:
            posts = db.list_curated_posts(since=date, limit=20)

        # Generate digest summary
        summary = await self._generate_digest_summary(posts, date)

        # Collect all topics
        all_topics = set()
        for post in posts:
            all_topics.update(post.topics)

        digest = DailyDigest(
            date=date,
            title=f"Quantum News Digest - {date.strftime('%B %d, %Y')}",
            summary=summary,
            post_ids=[p.id for p in posts],
            topics=list(all_topics),
            curator_name=self.settings.curator_name,
        )

        db.save_daily_digest(digest)
        return digest

    async def _generate_digest_summary(
        self,
        posts: list[CuratedPost],
        date: datetime,
    ) -> str:
        """Generate AI summary for daily digest."""
        if not posts:
            return "No quantum computing news to report today."

        if not self.settings.anthropic_api_key:
            return self._generate_fallback_digest(posts, date)

        system_prompt = DIGEST_SYSTEM_PROMPT.format(
            curator_name=self.settings.curator_name
        )

        # Build article summaries
        article_list = "\n\n".join([
            f"**{p.title}** ({p.source_name})\n{p.summary[:300]}..."
            for p in posts[:10]  # Top 10 for context
        ])

        user_prompt = f"""Create a daily digest summary for {date.strftime('%B %d, %Y')}.

Today's quantum computing articles:

{article_list}

Write a 2-3 paragraph digest summary highlighting the key developments."""

        try:
            response = self.client.messages.create(
                model=self.settings.claude_model,
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return _strip_markdown(response.content[0].text.strip())
        except Exception as e:
            print(f"Claude API error for digest: {e}")
            return self._generate_fallback_digest(posts, date)

    def _generate_fallback_digest(
        self,
        posts: list[CuratedPost],
        date: datetime,
    ) -> str:
        """Generate fallback digest when AI is unavailable."""
        topic_counts = {}
        for post in posts:
            for topic in post.topics:
                topic_counts[topic.value] = topic_counts.get(topic.value, 0) + 1

        top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        topic_str = ", ".join(t[0] for t in top_topics)

        return (
            f"Today's quantum computing news features {len(posts)} articles "
            f"covering {topic_str}. "
            f"Browse the full collection below for the latest developments "
            f"in quantum technology and research."
        )

    async def auto_publish(
        self,
        posts: list[CuratedPost] | None = None,
        min_score: float = 0.5,
    ) -> list[CuratedPost]:
        """Auto-publish high-quality curated posts.

        Args:
            posts: Posts to consider (default: all drafts)
            min_score: Minimum relevance score to auto-publish

        Returns:
            List of published posts
        """
        if posts is None:
            posts = db.list_curated_posts(status=PostStatus.DRAFT)

        published = []
        for post in posts:
            if post.relevance_score >= min_score:
                post.status = PostStatus.PUBLISHED
                db.save_curated_post(post)
                published.append(post)

        return published


async def curate_today(
    limit: int = 20,
    auto_publish: bool = True,
) -> tuple[list[CuratedPost], DailyDigest | None]:
    """Convenience function to curate today's top articles.

    Args:
        limit: Maximum articles to curate
        auto_publish: Auto-publish high-quality posts

    Returns:
        Tuple of (curated posts, daily digest)
    """
    from .aggregator import Aggregator

    # Get top articles
    aggregator = Aggregator()
    articles = await aggregator.get_top_articles(limit=limit)

    if not articles:
        return [], None

    # Curate articles
    curator = Curator()
    posts = await curator.curate_batch(articles)

    # Auto-publish if enabled
    if auto_publish:
        await curator.auto_publish(posts)

    # Create daily digest
    digest = await curator.create_daily_digest(posts=posts)

    return posts, digest
