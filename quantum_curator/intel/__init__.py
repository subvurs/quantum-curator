"""Quantum Intel synthesis pipeline, migrated into Curator backend.

Originally lived at ``~/Library/Application Support/quantum_intel/``.
Migrated in June 2026 because Intel's pipeline kept stalling on
PEP 475 EINTR-restart-defeating SIGALRM deadlines, multi-provider
fallback chains (Ollama Cloud slow-drip), and duplicate scoring
infra.

Sub-modules
-----------
    import_inventory  — one-time inventory.json → quantum_intel_entries
                        (Phase 1, complete; 1216+38 rows imported)
    inventory_view    — SQLite read-side, mirrors inventory.json shape
    brief_history     — anti-recurrence: recently-cited entry counter
    synthesizer       — combinatorial-product synthesis (Phase 2)
    daily_summary     — TL;DR + implications + attention rec (Phase 2)
    emailer           — separate SMTP path for Intel briefs (Phase 2)
"""
