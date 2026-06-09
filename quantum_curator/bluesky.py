"""Bluesky social sharing for Quantum Curator."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .config import get_settings
from .db import get_connection
from .models import CuratedPost

logger = logging.getLogger(__name__)

# Topic -> hashtag mapping
TOPIC_HASHTAGS: dict[str, str] = {
    "hardware": "#QuantumHardware",
    "algorithms": "#QuantumAlgorithms",
    "error_correction": "#QuantumErrorCorrection",
    "cryptography": "#QuantumCryptography",
    "machine_learning": "#QuantumML",
    "simulation": "#QuantumSimulation",
    "sensing": "#QuantumSensing",
    "industry": "#QuantumIndustry",
    "research": "#QuantumResearch",
    "policy": "#QuantumPolicy",
    "general": "#QuantumComputing",
}


class BlueskySharer:
    """Share curated posts to Bluesky."""

    def __init__(self) -> None:
        settings = get_settings()
        self._handle = settings.bluesky_handle
        self._app_password = settings.bluesky_app_password
        self._session: dict | None = None

    @property
    def is_configured(self) -> bool:
        """Check if Bluesky credentials are set."""
        return bool(self._handle and self._app_password)

    def _login(self, client: httpx.Client) -> bool:
        """Authenticate with Bluesky and store session."""
        if self._session:
            return True
        try:
            resp = client.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": self._handle, "password": self._app_password},
            )
            resp.raise_for_status()
            self._session = resp.json()
            return True
        except httpx.HTTPError:
            logger.exception("Bluesky login failed")
            return False

    def _auth_headers(self) -> dict[str, str]:
        """Return authorization header using current session."""
        if not self._session:
            return {}
        return {"Authorization": f"Bearer {self._session['accessJwt']}"}

    def share_post(self, post: CuratedPost) -> bool:
        """Share a single curated post to Bluesky.

        Returns True on success, False on failure.
        """
        if not self.is_configured:
            logger.warning("Bluesky not configured, skipping share")
            return False

        text = self._build_post_text(post)
        embed = self._build_embed(post)

        with httpx.Client(timeout=30) as client:
            if not self._login(client):
                return False

            record: dict = {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
            if embed:
                record["embed"] = embed

            # Detect link facet so the URL is clickable
            if post.original_url and post.original_url in text:
                start = text.index(post.original_url)
                record["facets"] = [{
                    "index": {
                        "byteStart": len(text[:start].encode("utf-8")),
                        "byteEnd": len(text[:start].encode("utf-8")) + len(post.original_url.encode("utf-8")),
                    },
                    "features": [{
                        "$type": "app.bsky.richtext.facet#link",
                        "uri": post.original_url,
                    }],
                }]

            try:
                resp = client.post(
                    "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                    headers=self._auth_headers(),
                    json={
                        "repo": self._session["did"],
                        "collection": "app.bsky.feed.post",
                        "record": record,
                    },
                )
                resp.raise_for_status()
                result = resp.json()
                bsky_uri = result.get("uri", "")
                bsky_cid = result.get("cid", "")
                record_bluesky_share(post.id, bsky_uri, bsky_cid)
                logger.info("Shared to Bluesky: %s", post.title)
                return True
            except httpx.HTTPError:
                logger.exception("Failed to share post to Bluesky: %s", post.title)
                return False

    def share_daily_summary(
        self,
        text: str,
        link: str = "https://qrater.org",
        *,
        summary_date: str | None = None,
    ) -> bool:
        """Share the daily Quantum Intel summary as a single Bluesky post.

        Distinct from ``share_post`` (which pushes individual CuratedPost
        rows). This is the once-per-day Intel digest path: the post text
        comes from ``intel.daily_summary.render_bluesky`` and the link
        is a single CTA (default qrater.org). Idempotent via the
        ``bluesky_daily_summaries`` table — the UNIQUE constraint on
        ``summary_date`` means re-running on the same date is a no-op
        after the first successful share.

        Mark called out the Quantum Crier per-post format as too long
        for a daily digest; this path uses pre-rendered short text
        (<= 280 chars from ``render_bluesky``) and skips embeds.

        Returns True on success, False on failure (including the
        "already shared today" idempotency case).
        """
        if not self.is_configured:
            logger.warning("Bluesky not configured, skipping daily summary")
            return False

        date_key = summary_date or datetime.utcnow().strftime("%Y-%m-%d")
        if is_daily_summary_shared(date_key):
            logger.info("Daily summary for %s already shared, skipping", date_key)
            return False

        # Append the link if not already in the text (render_bluesky already
        # appends qrater.org; this guards custom callers).
        if link and link not in text:
            text = f"{text} {link}".strip()
        if len(text) > 300:
            text = text[:299] + "…"

        with httpx.Client(timeout=30) as client:
            if not self._login(client):
                return False

            record: dict = {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }

            # Link facet (byte-offset on the link's location in text)
            if link and link in text:
                start = text.index(link)
                record["facets"] = [{
                    "index": {
                        "byteStart": len(text[:start].encode("utf-8")),
                        "byteEnd": len(text[:start].encode("utf-8")) + len(link.encode("utf-8")),
                    },
                    "features": [{
                        "$type": "app.bsky.richtext.facet#link",
                        "uri": link,
                    }],
                }]

            try:
                resp = client.post(
                    "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                    headers=self._auth_headers(),
                    json={
                        "repo": self._session["did"],
                        "collection": "app.bsky.feed.post",
                        "record": record,
                    },
                )
                resp.raise_for_status()
                result = resp.json()
                bsky_uri = result.get("uri", "")
                bsky_cid = result.get("cid", "")
                record_daily_summary_share(date_key, bsky_uri, bsky_cid, text)
                logger.info("Shared daily summary for %s to Bluesky", date_key)
                return True
            except httpx.HTTPError:
                logger.exception("Failed to share daily summary for %s", date_key)
                return False

    def share_pending(self, limit: int = 5) -> list[str]:
        """Share published posts that haven't been shared to Bluesky yet.

        Returns list of post IDs that were successfully shared.
        """
        if not self.is_configured:
            return []

        posts = get_posts_not_shared_to_bluesky(limit=limit)
        shared_ids: list[str] = []
        for post in posts:
            if self.share_post(post):
                shared_ids.append(post.id)
        return shared_ids

    def _build_post_text(self, post: CuratedPost) -> str:
        """Format post text within 300 character limit.

        Format: Title + commentary excerpt + hashtags.
        """
        hashtags = self._get_hashtags(post)
        hashtag_str = " ".join(hashtags) if hashtags else "#QuantumComputing"

        # Extract first 1-2 sentences of commentary
        commentary_excerpt = ""
        if post.curator_commentary:
            sentences = post.curator_commentary.replace("\n", " ").split(". ")
            excerpt_parts: list[str] = []
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                candidate = s if s.endswith(".") else s + "."
                if not excerpt_parts:
                    excerpt_parts.append(candidate)
                elif len(". ".join(excerpt_parts) + " " + candidate) <= 200:
                    excerpt_parts.append(candidate)
                else:
                    break
            commentary_excerpt = " ".join(excerpt_parts)

        # Build text and truncate to 300 chars
        parts = [post.title]
        if commentary_excerpt:
            parts.append("")
            parts.append(commentary_excerpt)
        parts.append("")
        parts.append(hashtag_str)

        text = "\n".join(parts)

        if len(text) > 300:
            # Trim commentary to fit
            available = 300 - len(post.title) - len(hashtag_str) - 4  # newlines
            if available > 20 and commentary_excerpt:
                commentary_excerpt = commentary_excerpt[: available - 3].rsplit(" ", 1)[0] + "..."
                text = f"{post.title}\n\n{commentary_excerpt}\n\n{hashtag_str}"
            else:
                text = f"{post.title}\n\n{hashtag_str}"

        if len(text) > 300:
            # Title itself too long, truncate it
            max_title = 300 - len(hashtag_str) - 4
            text = f"{post.title[:max_title - 3]}...\n\n{hashtag_str}"

        return text[:300]

    def _get_hashtags(self, post: CuratedPost) -> list[str]:
        """Get hashtags from post topics (max 3)."""
        tags: list[str] = []
        for topic in post.topics[:3]:
            tag = TOPIC_HASHTAGS.get(topic.value, "")
            if tag:
                tags.append(tag)
        if not tags:
            tags.append("#QuantumComputing")
        return tags

    def _build_embed(self, post: CuratedPost) -> dict | None:
        """Build an external embed (link card) for the post."""
        if not post.original_url:
            return None

        embed: dict = {
            "$type": "app.bsky.embed.external",
            "external": {
                "uri": post.original_url,
                "title": post.title[:300],
                "description": (post.summary or post.meta_description or "")[:300],
            },
        }

        # Try to attach thumbnail
        if post.image_url:
            thumb_blob = self._upload_thumbnail(post.image_url)
            if thumb_blob:
                embed["external"]["thumb"] = thumb_blob

        return embed

    def _upload_thumbnail(self, image_url: str) -> dict | None:
        """Download an image and upload as a blob to Bluesky.

        Skips images larger than 1MB.
        """
        if not self._session:
            return None

        try:
            with httpx.Client(timeout=15) as client:
                img_resp = client.get(image_url, follow_redirects=True)
                img_resp.raise_for_status()

                image_data = img_resp.content
                if len(image_data) > 1_000_000:
                    logger.info("Image too large (%d bytes), skipping thumbnail", len(image_data))
                    return None

                content_type = img_resp.headers.get("content-type", "image/jpeg")
                if not content_type.startswith("image/"):
                    return None

                resp = client.post(
                    "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                    headers={
                        **self._auth_headers(),
                        "Content-Type": content_type,
                    },
                    content=image_data,
                )
                resp.raise_for_status()
                return resp.json().get("blob")
        except httpx.HTTPError:
            logger.debug("Failed to download/upload thumbnail: %s", image_url)
            return None


# --- Database helpers ---

def init_bluesky_table() -> None:
    """Create the bluesky_shares table if it doesn't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bluesky_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT NOT NULL UNIQUE,
            bsky_uri TEXT NOT NULL,
            bsky_cid TEXT NOT NULL,
            shared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_bsky_post_id ON bluesky_shares(post_id);
    """)
    conn.commit()
    conn.close()


def record_bluesky_share(post_id: str, bsky_uri: str, bsky_cid: str) -> None:
    """Record a successful Bluesky share."""
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO bluesky_shares (post_id, bsky_uri, bsky_cid, shared_at) VALUES (?, ?, ?, ?)",
        (post_id, bsky_uri, bsky_cid, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def is_post_shared_to_bluesky(post_id: str) -> bool:
    """Check if a post has already been shared to Bluesky."""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM bluesky_shares WHERE post_id = ?", (post_id,)
    ).fetchone()
    conn.close()
    return row is not None


def record_daily_summary_share(
    summary_date: str,
    bsky_uri: str,
    bsky_cid: str,
    post_text: str,
) -> None:
    """Record a successful daily-summary share keyed by date.

    ``summary_date`` is YYYY-MM-DD (caller decides timezone). UNIQUE
    on ``summary_date`` enforces "one summary per day"; INSERT OR
    REPLACE means a manual re-share with the same date overwrites
    the row (useful for testing — the idempotency check happens
    upstream in ``share_daily_summary``).
    """
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO bluesky_daily_summaries "
        "(summary_date, bsky_uri, bsky_cid, post_text, shared_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (summary_date, bsky_uri, bsky_cid, post_text, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def is_daily_summary_shared(summary_date: str) -> bool:
    """Check whether a daily summary has already been posted for the given date."""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM bluesky_daily_summaries WHERE summary_date = ?",
        (summary_date,),
    ).fetchone()
    conn.close()
    return row is not None


def get_posts_not_shared_to_bluesky(limit: int = 5) -> list[CuratedPost]:
    """Get published posts that haven't been shared to Bluesky yet."""
    from .db import _row_to_post

    conn = get_connection()
    rows = conn.execute("""
        SELECT cp.* FROM curated_posts cp
        LEFT JOIN bluesky_shares bs ON cp.id = bs.post_id
        WHERE cp.status = 'published'
        AND bs.post_id IS NULL
        ORDER BY cp.published_to_site_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [_row_to_post(r) for r in rows]
