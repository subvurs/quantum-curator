"""AI-powered curation and commentary generation for Quantum Curator."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
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

        # Create curated post
        post = CuratedPost(
            article_id=article.id,
            title=article.title,
            original_url=article.url,
            source_name=article.source_name,
            summary=article.summary,
            image_url=image_url,
            curator_commentary=commentary,
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
