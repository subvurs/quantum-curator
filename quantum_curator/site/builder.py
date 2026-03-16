"""Static site generator for Quantum Curator."""

from __future__ import annotations

import json
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

        # Generate CNAME if custom domain configured
        if self.settings.custom_domain:
            (self.output_dir / "CNAME").write_text(self.settings.custom_domain)

        # Generate .nojekyll for GitHub Pages
        (self.output_dir / ".nojekyll").touch()

        print(f"Site built at: {self.output_dir}")
        return self.output_dir

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
        """Copy CSS and static files to output."""
        static_src = Path(__file__).parent / "static"
        static_dst = self.output_dir / "static"

        if static_src.exists():
            shutil.copytree(static_src, static_dst, dirs_exist_ok=True)

    def _build_index(self, config: SiteConfig):
        """Build the home page."""
        # Get recent posts
        posts = db.list_curated_posts(
            status=PostStatus.PUBLISHED,
            limit=20,
        )

        # Get latest digest
        digests = db.list_daily_digests(limit=1)
        latest_digest = digests[0] if digests else None

        # Get topic counts
        topic_counts = self._get_topic_counts()

        template = self.env.get_template("index.html")
        html = template.render(
            config=config,
            posts=posts,
            digest=latest_digest,
            topic_counts=topic_counts,
            now=datetime.utcnow(),
        )

        (self.output_dir / "index.html").write_text(html)

    def _build_posts(self, config: SiteConfig):
        """Build individual post pages."""
        posts_dir = self.output_dir / "posts"
        posts_dir.mkdir(exist_ok=True)

        posts = db.list_curated_posts(status=PostStatus.PUBLISHED)
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

        # Get all posts
        posts = db.list_curated_posts(status=PostStatus.PUBLISHED)

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

        # Get posts by topic
        posts = db.list_curated_posts(status=PostStatus.PUBLISHED)
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
        posts = db.list_curated_posts(
            status=PostStatus.PUBLISHED,
            limit=50,
        )

        template = self.env.get_template("feed.xml")
        xml = template.render(
            config=config,
            posts=posts,
            now=datetime.utcnow(),
        )
        (self.output_dir / "feed.xml").write_text(xml)

    def _get_topic_counts(self) -> dict[str, int]:
        """Count posts by topic."""
        posts = db.list_curated_posts(status=PostStatus.PUBLISHED)
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


def build_site(output_dir: str | Path | None = None, clean: bool = True) -> Path:
    """Convenience function to build the site."""
    builder = SiteBuilder(output_dir)
    return builder.build(clean=clean)
