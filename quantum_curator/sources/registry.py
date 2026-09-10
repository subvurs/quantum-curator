"""Source registry with built-in quantum content sources."""

from __future__ import annotations

from typing import Any, Protocol

from ..models import RawArticle, Source, SourceType
from .. import db
from .rss import RSSFetcher
from .arxiv import ArxivFetcher
from .news import NewsAPIFetcher


class Fetcher(Protocol):
    """Protocol for source fetchers."""

    async def fetch(self, source: Source) -> list[RawArticle]:
        ...


# Built-in quantum content sources
BUILTIN_SOURCES: list[dict[str, Any]] = [
    # --- arXiv ---
    {
        "name": "arXiv Quantum Physics",
        "source_type": SourceType.ARXIV,
        "url": "https://arxiv.org",
        "arxiv_categories": ["quant-ph"],
        "fetch_interval_hours": 12,
    },
    # Note (2026-05-25): "arXiv Quantum Information" was previously seeded
    # with arxiv_categories=["cs.QI"]. cs.QI is not a valid arXiv category
    # (the actual cs.* taxonomy has no QI entry); the API silently returns
    # totalResults=0 for invalid categories. The source produced zero
    # articles for the ~70 days it was active. quant-ph already covers
    # quantum information papers via cross-listing. Removed rather than
    # repointed to cs.IT (classical info theory, would dilute relevance).
    # Existing DB rows by this name are NOT auto-pruned by
    # register_builtin_sources — drop manually with:
    #   DELETE FROM sources WHERE name = 'arXiv Quantum Information';
    {
        # Added 2026-06-09 as part of Intel → Curator source consolidation.
        # Intel was pulling cond-mat at the same 48h window as quant-ph
        # (config.py ARXIV_CATEGORIES = ["quant-ph", "cond-mat"]). Hardware
        # / materials-physics papers (superconducting qubits, neutral-atom
        # array physics, topological matter) land in cond-mat, not quant-ph.
        #
        # 2026-09-09: `cat:cond-mat` matches NOTHING on the arXiv API —
        # papers carry subcategory terms (cond-mat.mes-hall, ...), and the
        # parent archive name is not a category. Verified live: 0 entries
        # for cat:cond-mat on 2026-09-08 vs 28 for cat:cond-mat.mes-hall
        # alone. This source therefore returned zero articles on every
        # daily run since it was added ("Sources: ... 2 empty" in the
        # journal). Re-pointed at the five quantum-relevant subarchives.
        "name": "arXiv Condensed Matter",
        "source_type": SourceType.ARXIV,
        "url": "https://arxiv.org",
        "arxiv_categories": [
            "cond-mat.mes-hall",   # mesoscopic / nanoscale: qubit devices
            "cond-mat.supr-con",   # superconductivity: transmon materials
            "cond-mat.str-el",     # strongly correlated: simulation targets
            "cond-mat.quant-gas",  # quantum gases: neutral-atom platforms
            "cond-mat.mtrl-sci",   # materials for qubits / sensors
        ],
        "fetch_interval_hours": 12,
    },

    # --- Major Quantum Companies ---
    {
        "name": "Qiskit Blog (IBM)",
        "source_type": SourceType.RSS,
        "url": "https://medium.com/qiskit",
        "feed_url": "https://medium.com/feed/qiskit",
        "fetch_interval_hours": 6,
    },
    {
        "name": "Google Research Blog",
        "source_type": SourceType.RSS,
        "url": "https://blog.google/technology/research/",
        "feed_url": "https://blog.google/technology/research/rss/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "Microsoft Quantum Blog",
        "source_type": SourceType.RSS,
        "url": "https://cloudblogs.microsoft.com/quantum/",
        "feed_url": "https://cloudblogs.microsoft.com/quantum/feed/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "AWS Quantum Computing Blog",
        "source_type": SourceType.RSS,
        "url": "https://aws.amazon.com/blogs/quantum-computing/",
        "feed_url": "https://aws.amazon.com/blogs/quantum-computing/feed/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "IonQ Blog",
        "source_type": SourceType.RSS,
        "url": "https://ionq.com/news",
        "feed_url": "https://ionq.com/news/rss.xml",
        "fetch_interval_hours": 12,
    },
    {
        # Added 2026-06-09. Intel was scraping Quantinuum via DDG
        # ("Quantinuum quantum 2026") because Curator's vendor blog set
        # didn't include it. They publish hardware (H-Series ion trap),
        # logical-qubit demos, and QEC results — all in scope.
        # Feed verified to exist at /resources/rss; if it 404s the
        # RSSFetcher's existing error-classification path (per 2026-05-25
        # patch) will surface it rather than silently degrade.
        #
        # 2026-09-09: /resources/rss has returned 404 on every daily run
        # since at least Aug 16 (journal). Probed /blog/rss.xml, /rss.xml,
        # /feed, /blog/feed, /news/rss.xml, /news/blog/rss.xml,
        # /news/blog/feed(.xml), /newsroom/rss — all 404 — and the blog
        # page at /news/blog carries no <link rel="alternate"> feed tag.
        # Quantinuum currently publishes no syndication feed. Disabled
        # (not deleted) so it stops counting as an errored source each
        # run; re-enable with a working feed_url or an HTML fetcher.
        "name": "Quantinuum Blog",
        "source_type": SourceType.RSS,
        "url": "https://www.quantinuum.com/news/blog",
        "feed_url": "https://www.quantinuum.com/resources/rss",
        "fetch_interval_hours": 12,
        "enabled": False,
    },

    # --- Quantum News Sites ---
    {
        "name": "Quantum Computing Report",
        "source_type": SourceType.RSS,
        "url": "https://quantumcomputingreport.com",
        "feed_url": "https://quantumcomputingreport.com/feed/",
        "fetch_interval_hours": 4,
    },
    {
        "name": "The Quantum Insider",
        "source_type": SourceType.RSS,
        "url": "https://thequantuminsider.com",
        "feed_url": "https://thequantuminsider.com/feed/",
        "fetch_interval_hours": 6,
    },

    # --- Science Publications ---
    {
        "name": "Quanta Magazine",
        "source_type": SourceType.RSS,
        "url": "https://www.quantamagazine.org",
        "feed_url": "https://www.quantamagazine.org/feed/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "Phys.org Quantum",
        "source_type": SourceType.RSS,
        "url": "https://phys.org/physics-news/quantum-physics/",
        "feed_url": "https://phys.org/rss-feed/breaking/physics-news/quantum-physics/",
        "fetch_interval_hours": 4,
    },
    {
        "name": "Nature Physics",
        "source_type": SourceType.RSS,
        "url": "https://www.nature.com/nphys/",
        "feed_url": "https://www.nature.com/nphys.rss",
        "fetch_interval_hours": 12,
    },
    {
        # Added 2026-06-09. Intel was scraping APS via DDG
        # ("journals.aps.org quantum 2026"); replacing with a direct
        # feed for the highest-signal APS journal. PRX Quantum is
        # quantum-focused, peer-reviewed, lower volume than PRL.
        # Deliberately NOT adding PRL — too high-volume / noisy
        # for a daily intake. Reassess if a gap surfaces.
        "name": "PRX Quantum",
        "source_type": SourceType.RSS,
        "url": "https://journals.aps.org/prxquantum/",
        "feed_url": "http://feeds.aps.org/rss/recent/prxquantum.xml",
        "fetch_interval_hours": 12,
    },
    {
        "name": "Science Daily - Quantum",
        "source_type": SourceType.RSS,
        "url": "https://www.sciencedaily.com/news/matter_energy/quantum_physics/",
        "feed_url": "https://www.sciencedaily.com/rss/matter_energy/quantum_physics.xml",
        "fetch_interval_hours": 6,
    },

    # --- Tech News ---
    {
        "name": "Ars Technica - Science",
        "source_type": SourceType.RSS,
        "url": "https://arstechnica.com/science/",
        "feed_url": "https://feeds.arstechnica.com/arstechnica/science",
        "fetch_interval_hours": 6,
    },
    {
        "name": "MIT Technology Review",
        "source_type": SourceType.RSS,
        "url": "https://www.technologyreview.com",
        "feed_url": "https://www.technologyreview.com/feed/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "Wired Science",
        "source_type": SourceType.RSS,
        "url": "https://www.wired.com/category/science/",
        "feed_url": "https://www.wired.com/feed/category/science/latest/rss",
        "fetch_interval_hours": 6,
    },

    # --- Additional Science Sources ---
    {
        "name": "Physics World - Quantum",
        "source_type": SourceType.RSS,
        "url": "https://physicsworld.com/c/quantum/",
        "feed_url": "https://physicsworld.com/c/quantum/feed/",
        "fetch_interval_hours": 6,
    },
    {
        "name": "New Scientist - Physics",
        "source_type": SourceType.RSS,
        "url": "https://www.newscientist.com/subject/physics/",
        "feed_url": "https://www.newscientist.com/subject/physics/feed/",
        "fetch_interval_hours": 6,
    },

    # --- NewsAPI (if configured) ---
    {
        "name": "Quantum News (NewsAPI)",
        "source_type": SourceType.NEWS_API,
        "url": "https://newsapi.org",
        "news_query": '"quantum computing" OR "quantum computer" OR "qubit"',
        "fetch_interval_hours": 6,
    },
]


def register_builtin_sources() -> list[Source]:
    """Register all built-in sources in the database.

    Uses source name as a stable key to avoid duplicates on repeated init.
    Existing sources are updated with current feed URLs; new sources are added.
    """
    existing = {s.name: s for s in db.list_sources()}
    sources = []
    for source_data in BUILTIN_SOURCES:
        if source_data["name"] in existing:
            # Update existing source with current config (e.g. fixed feed URL)
            source = existing[source_data["name"]]
            source.feed_url = source_data.get("feed_url", source.feed_url)
            source.url = source_data.get("url", source.url)
            source.news_query = source_data.get("news_query", source.news_query)
            source.arxiv_categories = source_data.get("arxiv_categories", source.arxiv_categories)
            # An explicit `enabled` in the builtin entry wins over the DB row
            # so a source retired in code (e.g. a feed that no longer exists)
            # is actually switched off on the next `init`, not just in the
            # registry listing.
            if "enabled" in source_data:
                source.enabled = bool(source_data["enabled"])
        else:
            source = Source(**source_data)
        db.save_source(source)
        sources.append(source)
    return sources


def get_source_fetcher(source: Source) -> Fetcher:
    """Get the appropriate fetcher for a source type."""
    fetchers = {
        SourceType.RSS: RSSFetcher(),
        SourceType.ARXIV: ArxivFetcher(),
        SourceType.NEWS_API: NewsAPIFetcher(),
    }
    return fetchers.get(source.source_type, RSSFetcher())
