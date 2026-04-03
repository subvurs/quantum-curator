"""Twitter/X social sharing for Quantum Curator."""

from __future__ import annotations

import logging
from datetime import datetime

from .config import get_settings
from .db import get_connection
from .models import CuratedPost

logger = logging.getLogger(__name__)

# Topic -> hashtag mapping (same as bluesky but Twitter uses 280 char limit)
TOPIC_HASHTAGS: dict[str, str] = {
    "hardware": "#QuantumHardware",
    "algorithms": "#QuantumAlgorithms",
    "error_correction": "#QEC",
    "cryptography": "#QuantumCrypto",
    "machine_learning": "#QuantumML",
    "simulation": "#QuantumSimulation",
    "sensing": "#QuantumSensing",
    "industry": "#QuantumIndustry",
    "research": "#QuantumResearch",
    "policy": "#QuantumPolicy",
    "general": "#QuantumComputing",
}

# Twitter counts URLs as 23 chars regardless of actual length
TWITTER_URL_LENGTH = 23
TWITTER_CHAR_LIMIT = 280


class TwitterSharer:
    """Share curated posts to Twitter/X."""

    def __init__(self) -> None:
        settings = get_settings()
        self._consumer_key = settings.twitter_consumer_key
        self._consumer_secret = settings.twitter_consumer_secret
        self._access_token = settings.twitter_access_token
        self._access_token_secret = settings.twitter_access_token_secret
        self._client = None

    @property
    def is_configured(self) -> bool:
        """Check if Twitter credentials are set."""
        return bool(
            self._consumer_key
            and self._consumer_secret
            and self._access_token
            and self._access_token_secret
        )

    def _get_client(self):
        """Get or create a tweepy Client."""
        if self._client is not None:
            return self._client
        try:
            import tweepy

            self._client = tweepy.Client(
                consumer_key=self._consumer_key,
                consumer_secret=self._consumer_secret,
                access_token=self._access_token,
                access_token_secret=self._access_token_secret,
            )
            return self._client
        except Exception:
            logger.exception("Failed to create Twitter client")
            return None

    def share_post(self, post: CuratedPost) -> bool:
        """Share a single curated post to Twitter/X.

        Returns True on success, False on failure.
        """
        if not self.is_configured:
            logger.warning("Twitter not configured, skipping share")
            return False

        client = self._get_client()
        if not client:
            return False

        text = self._build_tweet_text(post)

        try:
            response = client.create_tweet(text=text)
            tweet_data = response.data
            tweet_id = str(tweet_data["id"])
            record_twitter_share(post.id, tweet_id)
            logger.info("Tweeted: %s", post.title)
            return True
        except Exception:
            logger.exception("Failed to tweet: %s", post.title)
            return False

    def share_pending(self, limit: int = 5) -> list[str]:
        """Share published posts that haven't been tweeted yet.

        Returns list of post IDs that were successfully shared.
        """
        if not self.is_configured:
            return []

        posts = get_posts_not_shared_to_twitter(limit=limit)
        shared_ids: list[str] = []
        for post in posts:
            if self.share_post(post):
                shared_ids.append(post.id)
        return shared_ids

    def _build_tweet_text(self, post: CuratedPost) -> str:
        """Format tweet text within 280 character limit.

        Format: Title + commentary excerpt + hashtags + URL.
        Twitter auto-generates a link card from the URL.
        URLs always count as 23 chars regardless of actual length.
        """
        hashtags = self._get_hashtags(post)
        hashtag_str = " ".join(hashtags) if hashtags else "#QuantumComputing"
        url = post.original_url or ""

        # Calculate space: URL counts as 23 chars + 1 space before it
        url_cost = (TWITTER_URL_LENGTH + 1) if url else 0
        hashtag_cost = len(hashtag_str)

        # Space for title + commentary (minus url, hashtags, newlines)
        # Layout: title\n\ncommentary\n\nhashtags\n\nurl
        overhead = 6  # three sets of \n\n separators
        available_for_content = TWITTER_CHAR_LIMIT - url_cost - hashtag_cost - overhead

        # Extract first 1-2 sentences of commentary
        commentary_excerpt = ""
        if post.curator_commentary and available_for_content > len(post.title) + 10:
            remaining = available_for_content - len(post.title)
            sentences = post.curator_commentary.replace("\n", " ").split(". ")
            excerpt_parts: list[str] = []
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                candidate = s if s.endswith(".") else s + "."
                if not excerpt_parts:
                    if len(candidate) <= remaining:
                        excerpt_parts.append(candidate)
                elif len(" ".join(excerpt_parts) + " " + candidate) <= remaining:
                    excerpt_parts.append(candidate)
                else:
                    break
            commentary_excerpt = " ".join(excerpt_parts)

        # Build tweet
        parts: list[str] = [post.title]

        if commentary_excerpt:
            parts.append("")
            parts.append(commentary_excerpt)

        parts.append("")
        parts.append(hashtag_str)

        if url:
            parts.append("")
            parts.append(url)

        text = "\n".join(parts)

        # If still too long, drop commentary
        actual_len = self._tweet_length(text, url)
        if actual_len > TWITTER_CHAR_LIMIT:
            if url:
                text = f"{post.title}\n\n{hashtag_str}\n\n{url}"
            else:
                text = f"{post.title}\n\n{hashtag_str}"

        # If title itself is too long, truncate
        actual_len = self._tweet_length(text, url)
        if actual_len > TWITTER_CHAR_LIMIT:
            max_title = TWITTER_CHAR_LIMIT - url_cost - hashtag_cost - 7  # newlines + "..."
            truncated_title = post.title[: max_title - 3] + "..."
            if url:
                text = f"{truncated_title}\n\n{hashtag_str}\n\n{url}"
            else:
                text = f"{truncated_title}\n\n{hashtag_str}"

        return text

    def _tweet_length(self, text: str, url: str) -> int:
        """Calculate effective tweet length (URLs count as 23 chars)."""
        if url and url in text:
            return len(text) - len(url) + TWITTER_URL_LENGTH
        return len(text)

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


# --- Database helpers ---

def init_twitter_table() -> None:
    """Create the twitter_shares table if it doesn't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS twitter_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT NOT NULL UNIQUE,
            tweet_id TEXT NOT NULL,
            shared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_twitter_post_id ON twitter_shares(post_id);
    """)
    conn.commit()
    conn.close()


def record_twitter_share(post_id: str, tweet_id: str) -> None:
    """Record a successful Twitter share."""
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO twitter_shares (post_id, tweet_id, shared_at) VALUES (?, ?, ?)",
        (post_id, tweet_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def is_post_shared_to_twitter(post_id: str) -> bool:
    """Check if a post has already been shared to Twitter."""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM twitter_shares WHERE post_id = ?", (post_id,)
    ).fetchone()
    conn.close()
    return row is not None


def get_posts_not_shared_to_twitter(limit: int = 5) -> list[CuratedPost]:
    """Get published posts that haven't been shared to Twitter yet."""
    from .db import _row_to_post

    conn = get_connection()
    rows = conn.execute("""
        SELECT cp.* FROM curated_posts cp
        LEFT JOIN twitter_shares ts ON cp.id = ts.post_id
        WHERE cp.status = 'published'
        AND ts.post_id IS NULL
        ORDER BY cp.published_to_site_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [_row_to_post(r) for r in rows]
