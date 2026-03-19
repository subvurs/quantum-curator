"""AI-powered curation and commentary generation for Quantum Curator."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic

from .config import get_settings
from .models import ContentTopic, CuratedPost, DailyDigest, PostStatus, RawArticle
from . import db


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


SUBVURS_NOTES_SYSTEM_PROMPT = """You are a research assistant identifying connections between quantum computing news and the Subvurs/Quasmology research program. Key concepts to look for:

- Nyx equation: Ψ(c,p,n) = 100c² × [(1-p) + p×exp(-50(d-0.504)²)] × Ψ_n(n) — a framework for emergence from quantum vacuum
- Chaos Valley (d=0.504): optimal emergence point, maps to quantum phase transition / critical point
- Inverse scaling: Nyx performance improves with problem size (avoids barren plateaus)
- Bidirectional coupling: error mitigation via feedback loops (21.3% improvement)
- T=0.857 time symmetry: 73.4% deterministic + 26.6% stochastic split
- Pattern 51/69/76 triad: quantum coherence state machine (entropy → topological transition → stable coherence)
- DMC3: quantum-enhanced optimization showing inverse scaling with problem size
- IQAS: integrated quantum acceleration pipeline (6-stage, 144.9Q× combined speedup)
- VQE/QAOA outperformance: 62x on H2O vs VQE, 2-6x on MaxCut vs QAOA
- Noise-enhanced computation: structured noise improves rather than degrades results
- Impax: classical sensing beats quantum sensing 43x for coherence detection
- Barren plateau avoidance via non-gradient, non-variational optimization
- Quasmology: unified mathematical framework for structure emergence, 17 modes

RULES:
- Return 1-3 sentences ONLY if a genuine, actionable connection exists to a specific concept above
- Return exactly "None" if no clear connection exists
- Be specific: name which Subvurs concept connects and how it relates
- Never force or speculate — only surface connections that could advance the research
- This is for internal research notes, not public display"""


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
                model="claude-haiku-4-20250514",
                max_tokens=200,
                system=SUBVURS_NOTES_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            notes = response.content[0].text.strip()
            if notes.lower() == "none":
                return ""
            return notes
        except Exception as e:
            print(f"Subvurs notes generation error: {e}")
            return ""

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
