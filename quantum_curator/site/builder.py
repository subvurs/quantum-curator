"""Static site generator for Quantum Curator."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import get_settings
from ..models import ContentTopic, CuratedPost, DailyDigest, PostStatus, SiteConfig
from .. import db


class SiteBuilder:
    """Build static HTML site from curated content."""

    def __init__(self, output_dir: str | Path | None = None):
        self.settings = get_settings()
        self.output_dir = Path(output_dir or self.settings.output_dir)

        # Content freshness cutoff — only include posts newer than this
        from datetime import timedelta
        self.freshness_cutoff = datetime.utcnow() - timedelta(
            days=self.settings.max_article_age_days
        )

        # Set up Jinja2 environment
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

        # Register custom filters
        self.env.filters["date"] = self._format_date
        self.env.filters["datetime"] = self._format_datetime
        self.env.filters["topic_class"] = self._topic_class
        self.env.filters["has_image"] = lambda post: bool(post.image_url)
        self.env.filters["clean_text"] = self._clean_text
        self.env.tests["has_image"] = lambda post: bool(post.image_url)

        # Extract base path from site URL for internal links
        from urllib.parse import urlparse
        parsed = urlparse(self.settings.site_url)
        self.env.globals["base_path"] = parsed.path.rstrip("/")

    def build(self, clean: bool = True) -> Path:
        """Build the complete static site.

        Args:
            clean: Remove existing output directory first

        Returns:
            Path to output directory
        """
        if clean and self.output_dir.exists():
            shutil.rmtree(self.output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Copy static assets
        self._copy_static_assets()

        # Build site config
        site_config = self._get_site_config()

        # Build pages
        self._build_index(site_config)
        self._build_posts(site_config)
        self._build_archive(site_config)
        self._build_topics(site_config)
        self._build_about(site_config)
        self._build_rss_feed(site_config)
        self._build_search(site_config)

        # Generate CNAME if custom domain configured
        if self.settings.custom_domain:
            (self.output_dir / "CNAME").write_text(self.settings.custom_domain)

        # Generate .nojekyll for GitHub Pages
        (self.output_dir / ".nojekyll").touch()

        print(f"Site built at: {self.output_dir}")
        return self.output_dir

    def _get_fresh_posts(self, limit: int = 100) -> list[CuratedPost]:
        """Return published posts within the freshness window."""
        return db.list_curated_posts(
            status=PostStatus.PUBLISHED,
            since=self.freshness_cutoff,
            limit=limit,
        )

    def _get_site_config(self) -> SiteConfig:
        """Get site configuration."""
        return SiteConfig(
            site_name=self.settings.site_name,
            site_description=self.settings.site_description,
            base_url=self.settings.site_url,
            curator_name=self.settings.curator_name,
            curator_bio=self.settings.curator_bio,
            social_links=self.settings.social_links,
        )

    def _copy_static_assets(self):
        """Copy CSS, static files, and generated images to output."""
        static_src = Path(__file__).parent / "static"
        static_dst = self.output_dir / "static"

        if static_src.exists():
            shutil.copytree(static_src, static_dst, dirs_exist_ok=True)

        # Copy generated images from data/images/ into the build output
        generated_src = self.settings.data_dir / "images"
        if generated_src.exists() and any(generated_src.iterdir()):
            generated_dst = static_dst / "images" / "generated"
            generated_dst.mkdir(parents=True, exist_ok=True)
            for img_file in generated_src.iterdir():
                if img_file.is_file():
                    shutil.copy2(img_file, generated_dst / img_file.name)

    def _build_index(self, config: SiteConfig):
        """Build the home page with magazine-style layout."""
        # Get recent posts (within freshness window only)
        posts = self._get_fresh_posts(limit=30)

        # Get latest digest
        digests = db.list_daily_digests(limit=1)
        latest_digest = digests[0] if digests else None

        # Get topic counts
        topic_counts = self._get_topic_counts()

        # Tier splitting for magazine layout
        hero_post = posts[0] if posts else None
        remaining = posts[1:] if posts else []

        # Prefer posts with images for featured slots
        with_images = [p for p in remaining if p.image_url]
        without_images = [p for p in remaining if not p.image_url]
        featured_candidates = with_images + without_images
        featured_posts = featured_candidates[:3]

        # Group the rest by primary topic
        rest_posts = featured_candidates[3:]
        topic_sections: dict[str, list[CuratedPost]] = {}
        for post in rest_posts:
            primary_topic = post.topics[0].value if post.topics else "general"
            if primary_topic not in topic_sections:
                topic_sections[primary_topic] = []
            topic_sections[primary_topic].append(post)
        topic_sections = dict(
            sorted(topic_sections.items(), key=lambda x: len(x[1]), reverse=True)
        )

        template = self.env.get_template("index.html")
        html = template.render(
            config=config,
            posts=posts,
            hero_post=hero_post,
            featured_posts=featured_posts,
            topic_sections=topic_sections,
            digest=latest_digest,
            topic_counts=topic_counts,
            now=datetime.utcnow(),
        )

        (self.output_dir / "index.html").write_text(html)

    def _build_posts(self, config: SiteConfig):
        """Build individual post pages."""
        posts_dir = self.output_dir / "posts"
        posts_dir.mkdir(exist_ok=True)

        posts = self._get_fresh_posts(limit=500)
        template = self.env.get_template("post.html")

        for post in posts:
            # Create slug from ID (first 8 chars)
            slug = post.id[:8]
            html = template.render(
                config=config,
                post=post,
                now=datetime.utcnow(),
            )
            (posts_dir / f"{slug}.html").write_text(html)

    def _build_archive(self, config: SiteConfig):
        """Build archive pages organized by month."""
        archive_dir = self.output_dir / "archive"
        archive_dir.mkdir(exist_ok=True)

        # Get posts within freshness window
        posts = self._get_fresh_posts(limit=500)

        # Group by month
        months: dict[str, list[CuratedPost]] = {}
        for post in posts:
            if post.published_at:
                key = post.published_at.strftime("%Y-%m")
                if key not in months:
                    months[key] = []
                months[key].append(post)

        # Build archive index
        template = self.env.get_template("archive.html")
        html = template.render(
            config=config,
            months=sorted(months.keys(), reverse=True),
            month_posts=months,
            now=datetime.utcnow(),
        )
        (archive_dir / "index.html").write_text(html)

        # Build monthly pages
        month_template = self.env.get_template("archive_month.html")
        for month_key, month_posts in months.items():
            month_date = datetime.strptime(month_key, "%Y-%m")
            html = month_template.render(
                config=config,
                month=month_date,
                posts=month_posts,
                now=datetime.utcnow(),
            )
            (archive_dir / f"{month_key}.html").write_text(html)

    def _build_topics(self, config: SiteConfig):
        """Build topic pages."""
        topics_dir = self.output_dir / "topics"
        topics_dir.mkdir(exist_ok=True)

        # Get posts by topic (within freshness window)
        posts = self._get_fresh_posts(limit=500)
        topic_posts: dict[str, list[CuratedPost]] = {}

        for post in posts:
            for topic in post.topics:
                key = topic.value
                if key not in topic_posts:
                    topic_posts[key] = []
                topic_posts[key].append(post)

        # Build topic index
        template = self.env.get_template("topics.html")
        html = template.render(
            config=config,
            topic_posts=topic_posts,
            now=datetime.utcnow(),
        )
        (topics_dir / "index.html").write_text(html)

        # Build individual topic pages
        topic_template = self.env.get_template("topic.html")
        for topic_name, topic_list in topic_posts.items():
            slug = topic_name.lower().replace(" ", "-")
            html = topic_template.render(
                config=config,
                topic=topic_name,
                posts=topic_list,
                featured_post=topic_list[0] if topic_list else None,
                remaining_posts=topic_list[1:] if topic_list else [],
                now=datetime.utcnow(),
            )
            (topics_dir / f"{slug}.html").write_text(html)

    def _build_about(self, config: SiteConfig):
        """Build the about page."""
        template = self.env.get_template("about.html")
        html = template.render(
            config=config,
            now=datetime.utcnow(),
        )
        (self.output_dir / "about.html").write_text(html)

    def _build_rss_feed(self, config: SiteConfig):
        """Build RSS feed."""
        posts = self._get_fresh_posts(limit=50)

        template = self.env.get_template("feed.xml")
        xml = template.render(
            config=config,
            posts=posts,
            now=datetime.utcnow(),
        )
        (self.output_dir / "feed.xml").write_text(xml)

    def _build_search(self, config: SiteConfig):
        """Build search index JSON and search page."""
        posts = self._get_fresh_posts(limit=500)

        # Build search index
        index = []
        for post in posts:
            summary = post.summary or ""
            commentary = post.curator_commentary or ""
            index.append({
                "id": post.id[:8],
                "title": post.title,
                "summary": summary[:300] + ("..." if len(summary) > 300 else ""),
                "source": post.source_name,
                "topics": [t.value for t in post.topics],
                "date": self._format_date(post.published_at),
                "image_url": post.image_url or "",
                "commentary": commentary[:200] + ("..." if len(commentary) > 200 else ""),
            })

        # Write search index
        data_dir = self.output_dir / "data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "search-index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=None)
        )

        # Render search page
        template = self.env.get_template("search.html")
        html = template.render(
            config=config,
            now=datetime.utcnow(),
        )
        (self.output_dir / "search.html").write_text(html)

    def _get_topic_counts(self) -> dict[str, int]:
        """Count posts by topic."""
        posts = self._get_fresh_posts(limit=500)
        counts: dict[str, int] = {}

        for post in posts:
            for topic in post.topics:
                key = topic.value
                counts[key] = counts.get(key, 0) + 1

        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    @staticmethod
    def _format_date(value: datetime | None) -> str:
        """Format date for display."""
        if not value:
            return ""
        return value.strftime("%B %d, %Y")

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        """Format datetime for RSS."""
        if not value:
            return ""
        return value.strftime("%a, %d %b %Y %H:%M:%S +0000")

    @staticmethod
    def _topic_class(topic: str) -> str:
        """Convert topic to CSS class name."""
        return topic.lower().replace(" ", "-")

    @staticmethod
    def _clean_text(text: str) -> str:
        """Strip markdown formatting and render as clean HTML paragraphs.

        Converts plain text with paragraph breaks into proper <p> tags
        while removing any markdown syntax from AI-generated content.
        """
        if not text:
            return ""
        # Remove bold
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        # Remove italic
        text = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'\1', text)
        text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)
        # Remove headers
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # Remove bullet points
        text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
        # Remove numbered lists
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        # Remove inline code
        text = re.sub(r'`(.+?)`', r'\1', text)
        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', '', text)
        # Split into paragraphs and wrap in <p> tags
        paragraphs = [p.strip() for p in text.strip().split('\n\n') if p.strip()]
        if not paragraphs:
            return text.strip()
        return '\n'.join(f'<p>{p}</p>' for p in paragraphs)


def build_site(output_dir: str | Path | None = None, clean: bool = True) -> Path:
    """Convenience function to build the site."""
    builder = SiteBuilder(output_dir)
    return builder.build(clean=clean)
