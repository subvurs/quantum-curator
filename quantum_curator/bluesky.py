"""Bluesky social sharing for Quantum Curator."""

from __future__ import annotations

import logging
import re
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
        image_bytes: bytes | None = None,
        image_alt: str | None = None,
        image_mime: str = "image/png",
    ) -> bool:
        """Share the daily Quantum Intel summary as a single Bluesky post.

        Distinct from ``share_post`` (which pushes individual CuratedPost
        rows). This is the once-per-day Intel digest path: the post text
        comes from ``intel.daily_summary.render_bluesky`` and the link
        is a single CTA (default qrater.org). Idempotent via the
        ``bluesky_daily_summaries`` table — the UNIQUE constraint on
        ``summary_date`` means re-running on the same date is a no-op
        after the first successful share.

        If ``image_bytes`` is provided the post carries an
        ``app.bsky.embed.images`` embed in addition to the text. The
        text path is the screen-reader-friendly version; the image
        carries the full structured summary (TL;DR + Implications +
        Attention + Tags) for sighted readers. The image is a
        redundancy, not a replacement — text-only callers still work.

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
            # Safety net for custom callers that bypassed render_bluesky.
            # Cut at the last word boundary that fits (no ellipsis — the
            # image embed and qrater.org CTA carry the rest).
            cut = text[:300]
            if " " in cut:
                cut = cut.rsplit(" ", 1)[0]
            text = cut

        with httpx.Client(timeout=30) as client:
            if not self._login(client):
                return False

            record: dict = {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }

            # Optional image embed. Upload the blob first; only attach
            # the embed if the upload succeeded (text-only fallback).
            if image_bytes:
                blob_ref = self._upload_image_blob(
                    client, image_bytes, mime=image_mime
                )
                if blob_ref:
                    alt = image_alt or f"Quantum Intel daily summary — {date_key}"
                    record["embed"] = self._build_images_embed(blob_ref, alt)
                else:
                    logger.info(
                        "Image blob upload failed for %s; falling back to text-only",
                        date_key,
                    )

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

        Format: Title + packed-sentence commentary + hashtags.

        Pack as many complete commentary sentences as fit in the budget
        rather than chopping mid-sentence with "..." — the truncated
        ellipsis form is what users complained about ("many posts ending
        in '...'"). If even the title-plus-hashtags doesn't fit, drop
        commentary first, then word-wrap the title at the last word
        boundary that fits (still no ellipsis).
        """
        max_chars = 300
        hashtags = self._get_hashtags(post)
        hashtag_str = " ".join(hashtags) if hashtags else "#QuantumComputing"
        title = post.title.strip()

        # Budget for commentary = total - title - hashtags - separators ("\n\n" * 2).
        # If even the no-commentary frame doesn't fit, fall through to
        # the degraded paths below.
        frame_overhead = len(title) + len(hashtag_str) + 4  # two "\n\n"
        commentary_budget = max_chars - frame_overhead

        commentary_excerpt = ""
        if post.curator_commentary and commentary_budget > 20:
            # Split into sentences; keep the period attached. The regex
            # tolerates ?! as terminators and collapses whitespace from
            # the multi-paragraph commentary the curator emits.
            normalized = re.sub(r"\s+", " ", post.curator_commentary).strip()
            sentences = re.split(r"(?<=[.!?])\s+", normalized)
            packed: list[str] = []
            running = 0
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                # Width when appended to packed (join with single space)
                added = (1 if packed else 0) + len(s)
                if running + added <= commentary_budget:
                    packed.append(s)
                    running += added
                else:
                    break
            commentary_excerpt = " ".join(packed)

        # Assemble. No-commentary case yields "title\n\nhashtags".
        if commentary_excerpt:
            text = f"{title}\n\n{commentary_excerpt}\n\n{hashtag_str}"
        else:
            text = f"{title}\n\n{hashtag_str}"

        if len(text) <= max_chars:
            return text

        # Title + hashtags alone overflows. Word-wrap the title at the
        # last whitespace boundary that fits; no ellipsis. If the title
        # is one long unbroken token, fall back to a hard slice (rare
        # — but still preferable to dropping the share entirely).
        title_budget = max_chars - len(hashtag_str) - 4  # "\n\n" * 2
        if title_budget <= 0:
            # Hashtags alone exceed the budget — degrade to title only.
            return title[:max_chars]
        truncated_title = title[:title_budget]
        # Cut at last word boundary if one exists in the window.
        if " " in truncated_title:
            truncated_title = truncated_title.rsplit(" ", 1)[0]
        text = f"{truncated_title}\n\n{hashtag_str}"
        # Safety clamp — shouldn't fire after word-boundary cut, but
        # protects callers from a malformed result if it ever does.
        return text[:max_chars]

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

    def _upload_image_blob(
        self,
        client: httpx.Client,
        image_bytes: bytes,
        *,
        mime: str = "image/png",
    ) -> dict | None:
        """Upload raw image bytes to Bluesky and return the blob ref.

        Mirrors ``_upload_thumbnail`` but takes bytes directly (no URL
        fetch) so the daily-summary card renderer can hand us its
        Pillow output without a round trip through disk. Returns the
        ``blob`` dict from ``com.atproto.repo.uploadBlob`` or None on
        any failure (size, content-type sanity check, HTTP error).
        """
        if not self._session:
            return None
        if not image_bytes:
            return None
        if len(image_bytes) > 1_000_000:
            logger.info(
                "Daily-summary image too large (%d bytes), skipping embed",
                len(image_bytes),
            )
            return None
        if not mime.startswith("image/"):
            logger.info("Refusing non-image MIME %r for blob upload", mime)
            return None

        try:
            resp = client.post(
                "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                headers={
                    **self._auth_headers(),
                    "Content-Type": mime,
                },
                content=image_bytes,
            )
            resp.raise_for_status()
            return resp.json().get("blob")
        except httpx.HTTPError:
            logger.exception("Failed to upload image blob")
            return None

    def _build_images_embed(self, blob_ref: dict, alt_text: str) -> dict:
        """Build the ``app.bsky.embed.images`` embed payload."""
        return {
            "$type": "app.bsky.embed.images",
            "images": [
                {
                    "alt": alt_text,
                    "image": blob_ref,
                }
            ],
        }

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
