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
from .llm_client import llm_complete, make_router_llm_call
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
    from ._vendor.subvurs_impact.path_catalog import (  # type: ignore
        build_prompt as _catalog_build_prompt,
    )
    _IMPACT_AVAILABLE = True
except Exception as _impact_err:  # noqa: BLE001 — fail-closed import
    print(f"subvurs_impact unavailable, scoring disabled: {_impact_err}")
    _IMPACT_AVAILABLE = False
    _IMPACT_VERSION = None  # type: ignore[assignment]
    _ImpactScoreReport = None  # type: ignore[assignment,misc]
    _impact_score_item = None  # type: ignore[assignment]
    _catalog_build_prompt = None  # type: ignore[assignment]


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


# --- Subvurs notes system prompt (single source of truth) ----------------
# v1.8.0 (2026-07-14): the inline SUBVURS_NOTES_SYSTEM_PROMPT duplicate is
# deleted. It had drifted from the shared catalog (May 15 path snapshots)
# and still presented pre-July-2026 core-theory claims (0.504 as interior
# maximum, P51 zero-point-energy signatures) as live findings. The prompt
# is now built from the vendored path_catalog.build_prompt() — the same
# catalog, DO-NOT-USE block, and July 2026 historical re-scope the impact
# scorer uses — plus this curator-specific output-format preamble.
# Fail-closed: if the vendored import above failed, the prompt is None and
# note generation is skipped (no notes rather than stale-theory notes).

_SUBVURS_NOTES_FORMAT_PREAMBLE = """OUTPUT FORMAT (Quantum Curator internal research notes)
- Plain text only: no markdown, no bullets, no headers.
- Reply with 1-3 sentences identifying a specific connection, or exactly "None".

"""


def _build_subvurs_notes_system_prompt() -> str | None:
    """Compose the notes prompt from the vendored shared catalog."""
    if not _IMPACT_AVAILABLE or _catalog_build_prompt is None:
        return None
    return _SUBVURS_NOTES_FORMAT_PREAMBLE + _catalog_build_prompt()


SUBVURS_NOTES_SYSTEM_PROMPT = _build_subvurs_notes_system_prompt()


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
        # Anthropic client is constructed lazily and only for the anthropic
        # backend. Under the router backend the box has no ANTHROPIC_API_KEY
        # (all cloud spend flows through the router's capped Tier 2), so eager
        # construction would be wasteful and could mislead. All LLM calls now
        # flow through `llm_complete(...)`; `self.client` is retained only for
        # any anthropic-backend code path that still references it directly.
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> "anthropic.Anthropic":
        """Lazily construct the direct Anthropic client (anthropic backend)."""
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

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

    async def recurate_post(self, post: CuratedPost) -> tuple[str, CuratedPost]:
        """Regenerate AI commentary + Subvurs notes for an existing post.

        Repairs posts saved on the template-fallback path (e.g. a Claude
        API outage). Loads the post's source RawArticle and re-runs the
        same generation the curate path uses, mutating ONLY the
        LLM-derived fields. Identity and lifecycle fields (id, status,
        published_to_site_at, slug, curated_at, article_id) are preserved
        so the post keeps its place and publish history on the site.

        Returns ``(outcome, post)`` where outcome is one of:
          - ``"regenerated"``  — real commentary produced and saved
          - ``"no_article"``   — source raw_articles row missing
          - ``"still_fallback"`` — regeneration returned the template again
            (API still down); NOT saved, so a failed repair never
            overwrites the post with the same degraded text.
        """
        article = db.get_article(post.article_id)
        if article is None:
            return "no_article", post

        commentary = await self._generate_commentary(article)

        # Fail-loud: if the API is still unavailable, _generate_commentary
        # returns the template. Refuse to "repair" with the same degraded
        # text rather than silently re-saving the fallback.
        if db.FALLBACK_COMMENTARY_SIGNATURE in commentary:
            return "still_fallback", post

        subvurs_notes = ""
        if self.settings.generate_subvurs_notes:
            subvurs_notes = await self._generate_subvurs_notes(article)
            if subvurs_notes:
                self._save_subvurs_notes_file(article, subvurs_notes)

        # Refresh the deterministic impact score too — it was very likely
        # fail-closed to 0.0 during the same outage that triggered the
        # commentary fallback. Only reached once commentary succeeded, so
        # the API is back up and this call should resolve cleanly.
        if (
            self.settings.subvurs_impact_scoring_enabled
            and _IMPACT_AVAILABLE
        ):
            report = await self._score_subvurs_impact(article)
            if report is not None:
                post.subvurs_impact_score = float(report.score)
                post.subvurs_impact_report = report.model_dump_json()
                post.subvurs_impact_version = report.version

        post.curator_commentary = commentary
        post.subvurs_notes = subvurs_notes
        db.save_curated_post(post)
        return "regenerated", post

    async def recurate_batch(
        self,
        posts: list[CuratedPost],
        max_concurrent: int = 3,
    ) -> dict[str, list[CuratedPost]]:
        """Recurate multiple posts with rate limiting.

        Mirrors ``curate_batch``'s semaphore-bounded concurrency. Returns
        the posts bucketed by outcome: ``{"regenerated": [...],
        "still_fallback": [...], "no_article": [...], "error": [...]}``.
        """
        buckets: dict[str, list[CuratedPost]] = {
            "regenerated": [],
            "still_fallback": [],
            "no_article": [],
            "error": [],
        }
        semaphore = asyncio.Semaphore(max_concurrent)

        async def recurate_with_limit(post: CuratedPost) -> tuple[str, CuratedPost]:
            async with semaphore:
                try:
                    return await self.recurate_post(post)
                except Exception as e:  # noqa: BLE001 — report, don't abort batch
                    print(f"Error recurating '{post.title}': {e}")
                    return "error", post

        results = await asyncio.gather(
            *(recurate_with_limit(p) for p in posts)
        )
        for outcome, post in results:
            buckets[outcome].append(post)
        return buckets

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
        if not self.settings.llm_available:
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
            # Public-content path: escalation to capped cloud allowed on local
            # failure (router backend) / direct API (anthropic backend). Offload
            # the (sync) llm_complete to a thread so batch curation's event loop
            # isn't blocked by the router subprocess / API round-trip.
            text = await asyncio.to_thread(
                llm_complete,
                system=system_prompt,
                user=user_prompt,
                model=self.settings.claude_model,
                max_tokens=300,
                allow_escalation=True,
                settings=self.settings,
            )
            return _strip_markdown(text.strip())
        except Exception as e:
            print(f"Commentary generation error: {e}")
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
        if not self.settings.llm_available:
            return ""
        if SUBVURS_NOTES_SYSTEM_PROMPT is None:
            # Vendored catalog import failed → no prompt. Fail closed:
            # skip notes rather than generate against a stale framing.
            return ""

        user_prompt = f"""Analyze this quantum computing article for connections to Subvurs/Quasmology research:

Title: {article.title}
Source: {article.source_name}
Topics: {', '.join(t.value for t in article.topics)}

Summary:
{article.summary[:1500]}

Return 1-3 sentences identifying a specific connection, or exactly "None" if no genuine connection exists."""

        try:
            # Model stays hardcoded to "claude-sonnet-4-5" to preserve prior
            # behavior (anthropic backend); the router backend ignores `model`.
            notes = await asyncio.to_thread(
                llm_complete,
                system=SUBVURS_NOTES_SYSTEM_PROMPT,
                user=user_prompt,
                model="claude-sonnet-4-5",
                max_tokens=200,
                allow_escalation=True,
                settings=self.settings,
            )
            notes = notes.strip()
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
        if not self.settings.llm_available:
            return None

        # Match the shape score_item expects (proposal §3.2 / §5.2).
        item = {
            "title": article.title,
            "source": article.source_name,
            "summary": article.summary[:1500],
        }

        # Scorer is the highest-volume, local-only / fail-closed call: on the
        # router backend inject a NON-escalating router llm_call so a local
        # failure yields the documented degraded 0.0 (never cloud spend). On the
        # anthropic backend leave llm_call=None → score_item's _default_llm_call
        # (direct Anthropic API), preserving prior behavior byte-for-byte.
        score_kwargs: dict[str, Any] = {}
        if self.settings.uses_router:
            score_kwargs["llm_call"] = make_router_llm_call(
                self.settings, allow_escalation=False
            )

        # score_item is sync (single LLM call); offload to thread to
        # avoid blocking the event loop in batch curation.
        try:
            return await asyncio.to_thread(
                lambda: _impact_score_item(item, **score_kwargs)
            )
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

        if not self.settings.llm_available:
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
            text = await asyncio.to_thread(
                llm_complete,
                system=system_prompt,
                user=user_prompt,
                model=self.settings.claude_model,
                max_tokens=500,
                allow_escalation=True,
                settings=self.settings,
            )
            return _strip_markdown(text.strip())
        except Exception as e:
            print(f"Digest summary generation error: {e}")
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
