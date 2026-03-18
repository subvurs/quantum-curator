"""Static site generator for the Qrater interactive dashboard."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import get_settings
from ..models import CuratedPost, PostStatus
from .. import db


class QraterBuilder:
    """Build the Qrater single-page dashboard site."""

    def __init__(self, output_dir: str | Path | None = None):
        self.settings = get_settings()
        self.output_dir = Path(output_dir or self.settings.qrater_output_dir)

        template_dir = Path(__file__).parent / "templates" / "qrater"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html"]),
        )

    def build(self, clean: bool = True) -> Path:
        """Build the Qrater site.

        Returns:
            Path to output directory.
        """
        if clean and self.output_dir.exists():
            shutil.rmtree(self.output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Copy static assets
        self._copy_static_assets()

        # Generate articles data
        articles_data = self._generate_articles_json()
        data_dir = self.output_dir / "data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "articles.json").write_text(
            json.dumps(articles_data, ensure_ascii=False)
        )

        # Render index.html
        self._build_index(articles_data)

        # GitHub Pages support
        (self.output_dir / ".nojekyll").touch()

        print(f"Qrater built at: {self.output_dir}")
        return self.output_dir

    def _copy_static_assets(self):
        """Copy Qrater CSS and JS to output."""
        static_src = Path(__file__).parent / "static" / "qrater"
        static_dst = self.output_dir / "static" / "qrater"

        if static_src.exists():
            shutil.copytree(static_src, static_dst, dirs_exist_ok=True)

    def _generate_articles_json(self) -> list[dict]:
        """Generate the articles data for the client-side dashboard."""
        posts = db.list_curated_posts(status=PostStatus.PUBLISHED)
        curator_base = self.settings.site_url.rstrip("/")

        articles = []
        for post in posts:
            date_display = ""
            date_iso = ""
            if post.published_at:
                date_display = post.published_at.strftime("%B %d, %Y")
                date_iso = post.published_at.isoformat()
            elif post.curated_at:
                date_display = post.curated_at.strftime("%B %d, %Y")
                date_iso = post.curated_at.isoformat()

            articles.append({
                "id": post.id[:8],
                "title": post.title,
                "summary": post.summary or "",
                "source": post.source_name,
                "topics": [t.value for t in post.topics],
                "date": date_display,
                "date_iso": date_iso,
                "relevance_score": round(post.relevance_score, 3),
                "image_url": post.image_url or "",
                "commentary": post.curator_commentary or "",
                "original_url": post.original_url,
                "curator_post_url": f"{curator_base}/posts/{post.id[:8]}.html",
            })

        return articles

    def _build_index(self, articles_data: list[dict]):
        """Render the main dashboard page."""
        # Compute topic counts
        topic_counts: dict[str, int] = {}
        sources: set[str] = set()
        for article in articles_data:
            for topic in article["topics"]:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            sources.add(article["source"])

        template = self.env.get_template("index.html")
        html = template.render(
            qrater_url=self.settings.qrater_site_url,
            curator_url=self.settings.site_url,
            curator_name=self.settings.curator_name,
            buttondown_username=self.settings.buttondown_username,
            article_count=len(articles_data),
            topic_counts=dict(sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)),
            sources=sorted(sources),
            build_time=datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC"),
        )

        (self.output_dir / "index.html").write_text(html)


def build_qrater(output_dir: str | Path | None = None, clean: bool = True) -> Path:
    """Convenience function to build the Qrater site."""
    builder = QraterBuilder(output_dir)
    return builder.build(clean=clean)
