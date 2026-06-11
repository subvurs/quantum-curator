"""Bluesky social sharing for Quantum Curator."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

import httpx

from .bluesky_handles import find_mentions_in_text, find_source_attribution
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


# --- Facet helpers ---

# Hashtag pattern: '#' followed by 1+ word chars. Matches what users
# type in posts (e.g., "#QuantumHardware"). The captured group excludes
# the leading '#' because Bluesky's facet#tag.tag value must NOT contain
# the '#'.
_TAG_RE = re.compile(r"#(\w+)")

# Module-level DID resolution cache. Handles do not change in a single
# run; this avoids repeat hits to public.api.bsky.app for the ~6
# unique handles we use per post.
_DID_CACHE: dict[str, Optional[str]] = {}


def _byte_offset(text: str, char_idx: int) -> int:
    """Return the UTF-8 byte offset of the char at ``char_idx``."""
    return len(text[:char_idx].encode("utf-8"))


def _build_tag_facets(text: str) -> list[dict]:
    """Build app.bsky.richtext.facet#tag facets for every #word in text.

    Byte offsets cover the full ``#word`` span. The facet ``tag`` value
    excludes the leading '#' per the facet schema.
    """
    facets: list[dict] = []
    for m in _TAG_RE.finditer(text):
        start_b = _byte_offset(text, m.start())
        end_b = _byte_offset(text, m.end())
        facets.append({
            "index": {"byteStart": start_b, "byteEnd": end_b},
            "features": [{
                "$type": "app.bsky.richtext.facet#tag",
                "tag": m.group(1),
            }],
        })
    return facets


def _resolve_handle(client: httpx.Client, handle: str) -> Optional[str]:
    """Resolve a bsky handle to a DID via the public unauthenticated API.

    Returns the DID string on success, None on any failure. Cached
    per-process — handles do not change mid-run, and failed lookups are
    cached as None so we don't retry on every mention scan.
    """
    if not handle:
        return None
    if handle in _DID_CACHE:
        return _DID_CACHE[handle]
    try:
        resp = client.get(
            "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle",
            params={"handle": handle},
            timeout=5.0,
        )
        resp.raise_for_status()
        did = resp.json().get("did")
        _DID_CACHE[handle] = did if isinstance(did, str) and did else None
        return _DID_CACHE[handle]
    except (httpx.HTTPError, ValueError, KeyError):
        # Cache the None too — don't retry a failed lookup mid-run.
        _DID_CACHE[handle] = None
        return None


def _build_mention_facets(
    client: httpx.Client,
    text: str,
    *,
    exclude_spans: Optional[set[tuple[int, int]]] = None,
) -> list[dict]:
    """Build app.bsky.richtext.facet#mention facets for alias hits in text.

    ``exclude_spans`` is a set of ``(byte_start, byte_end)`` pairs that
    have already been emitted as facets elsewhere (e.g. the explicit
    "via @handle" attribution facet). Those byte ranges are skipped to
    avoid duplicate facets covering the same span.
    """
    excluded = exclude_spans or set()
    facets: list[dict] = []
    seen: set[tuple[int, int]] = set(excluded)
    for start_b, end_b, handle in find_mentions_in_text(text):
        key = (start_b, end_b)
        if key in seen:
            continue
        seen.add(key)
        did = _resolve_handle(client, handle)
        if not did:
            # Silent fail — no facet rather than a broken mention.
            continue
        facets.append({
            "index": {"byteStart": start_b, "byteEnd": end_b},
            "features": [{
                "$type": "app.bsky.richtext.facet#mention",
                "did": did,
            }],
        })
    return facets


_VIA_HANDLE_RE = re.compile(r"via @([a-zA-Z0-9.\-_]+)$", re.MULTILINE)


def _maybe_append_attribution(
    text: str, source_name: str, max_chars: int
) -> str:
    """Append "\\nvia @handle" if source maps and the budget allows.

    Silently no-ops on (a) unknown source, (b) attribute_source=false
    row, or (c) insufficient remaining budget. Never truncates ``text``
    to make the suffix fit — the prose post is more important than the
    attribution.
    """
    handle = find_source_attribution(source_name)
    if not handle:
        return text
    suffix = f"\nvia @{handle}"
    if len(text) + len(suffix) <= max_chars:
        return text + suffix
    return text


def _build_attribution_facet(
    client: httpx.Client, text: str
) -> tuple[Optional[dict], Optional[tuple[int, int]]]:
    """Build the explicit mention facet for a "via @handle" suffix.

    Returns ``(facet, (byte_start, byte_end))`` or ``(None, None)`` if
    no attribution suffix is present or DID resolution fails. The
    returned byte span lets the caller dedup against
    ``_build_mention_facets`` output.
    """
    m = _VIA_HANDLE_RE.search(text)
    if not m:
        return None, None
    handle = m.group(1)
    did = _resolve_handle(client, handle)
    if not did:
        return None, None
    # Cover just the "@handle" portion (skip the "via " prefix).
    at_start_char = m.start() + len("via ")
    end_char = m.end()
    start_b = _byte_offset(text, at_start_char)
    end_b = _byte_offset(text, end_char)
    facet = {
        "index": {"byteStart": start_b, "byteEnd": end_b},
        "features": [{
            "$type": "app.bsky.richtext.facet#mention",
            "did": did,
        }],
    }
    return facet, (start_b, end_b)


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

            facets: list[dict] = []

            # Link facet so the URL is clickable.
            if post.original_url and post.original_url in text:
                start = text.index(post.original_url)
                facets.append({
                    "index": {
                        "byteStart": _byte_offset(text, start),
                        "byteEnd": _byte_offset(text, start) + len(post.original_url.encode("utf-8")),
                    },
                    "features": [{
                        "$type": "app.bsky.richtext.facet#link",
                        "uri": post.original_url,
                    }],
                })

            # Tag facets — make every #word clickable as a tag feed entry.
            facets.extend(_build_tag_facets(text))

            # Explicit "via @handle" attribution facet. Track its byte
            # span so the alias-based mention scan below doesn't emit
            # a duplicate facet on the same range.
            attribution_facet, attribution_span = _build_attribution_facet(client, text)
            exclude_spans: set[tuple[int, int]] = set()
            if attribution_facet is not None and attribution_span is not None:
                facets.append(attribution_facet)
                exclude_spans.add(attribution_span)

            # Mention facets — scan the prose for known aliases.
            facets.extend(
                _build_mention_facets(client, text, exclude_spans=exclude_spans)
            )

            if facets:
                record["facets"] = facets

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
        thread: bool = True,
        payload: dict | None = None,
    ) -> bool:
        """Share the daily Quantum Intel summary to Bluesky.

        Distinct from ``share_post`` (which pushes individual CuratedPost
        rows). This is the once-per-day Intel digest path. Idempotent
        via the ``bluesky_daily_summaries`` table — the UNIQUE
        constraint on ``summary_date`` means re-running on the same
        date is a no-op after the first successful share.

        If ``image_bytes`` is provided the (root) post carries an
        ``app.bsky.embed.images`` embed in addition to the text. The
        text path is screen-reader-friendly; the image carries the full
        structured summary for sighted readers.

        Threading
        ---------
        When ``thread=True`` (default) and ``payload`` is provided,
        ``render_bluesky_thread`` is used to produce a 1-3 post list.
        A length-1 list takes the single-post fast path (byte-identical
        to the old behavior). A length>1 list is posted as a reply
        chain — image embed on the root only, "(N/M)" suffix already
        included by the renderer.

        When ``thread=False`` or ``payload=None``, the legacy
        single-post path is taken using ``text`` as-is.

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

        # Decide single vs threaded path.
        posts: list[str]
        if thread and payload is not None:
            from .intel.daily_summary import render_bluesky_thread

            posts = render_bluesky_thread(payload, link)
        else:
            # Append the link if not already in the text (render_bluesky
            # already appends qrater.org; this guards custom callers).
            if link and link not in text:
                text = f"{text} {link}".strip()
            if len(text) > 300:
                # Safety net for custom callers that bypassed render_bluesky.
                cut = text[:300]
                if " " in cut:
                    cut = cut.rsplit(" ", 1)[0]
                text = cut
            posts = [text]

        with httpx.Client(timeout=30) as client:
            if not self._login(client):
                return False

            # Upload the image once — it goes on the root post only.
            image_embed: dict | None = None
            if image_bytes:
                blob_ref = self._upload_image_blob(
                    client, image_bytes, mime=image_mime
                )
                if blob_ref:
                    alt = image_alt or f"Quantum Intel daily summary — {date_key}"
                    image_embed = self._build_images_embed(blob_ref, alt)
                else:
                    logger.info(
                        "Image blob upload failed for %s; falling back to text-only",
                        date_key,
                    )

            # Single-post fast path.
            if len(posts) == 1:
                root_uri = self._post_one(
                    client,
                    posts[0],
                    link=link,
                    embed=image_embed,
                    reply=None,
                )
                if root_uri is None:
                    return False
                return True

            # Threaded path. Post root, then chain replies. Image embed
            # on the root only. All thread posts get tag/mention facets
            # like any other post.
            root_uri, root_cid = self._post_one(
                client,
                posts[0],
                link=link,
                embed=image_embed,
                reply=None,
                return_cid=True,
            ) or (None, None)
            if root_uri is None:
                return False

            parent_uri, parent_cid = root_uri, root_cid
            thread_uris: list[str] = [root_uri]
            for body in posts[1:]:
                reply_block = {
                    "root": {"uri": root_uri, "cid": root_cid},
                    "parent": {"uri": parent_uri, "cid": parent_cid},
                }
                result = self._post_one(
                    client,
                    body,
                    link=link,
                    embed=None,
                    reply=reply_block,
                    return_cid=True,
                )
                if result is None:
                    # Partial-failure: persist what we have so it's
                    # visible in the DB; caller treats as failure.
                    record_daily_summary_share(
                        date_key, root_uri, root_cid or "", posts[0]
                    )
                    return False
                uri, cid = result
                thread_uris.append(uri)
                parent_uri, parent_cid = uri, cid

            # Persist root + each thread post.
            record_daily_summary_share(
                date_key, root_uri, root_cid or "", posts[0], is_thread=True
            )
            record_thread_posts(date_key, thread_uris, posts)
            logger.info(
                "Shared daily summary thread (%d posts) for %s to Bluesky",
                len(posts),
                date_key,
            )
            return True

    def _post_one(
        self,
        client: httpx.Client,
        text: str,
        *,
        link: str | None = None,
        embed: dict | None = None,
        reply: dict | None = None,
        return_cid: bool = False,
    ):
        """Post a single record. Returns URI (or (URI, CID)) or None on failure.

        Adds link / tag / mention facets automatically. Used by both
        the single-post and threaded paths so they share one facet
        pipeline.
        """
        record: dict = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
        if embed is not None:
            record["embed"] = embed
        if reply is not None:
            record["reply"] = reply

        facets: list[dict] = []

        # Link facet (first occurrence of the link in text).
        if link and link in text:
            start = text.index(link)
            facets.append({
                "index": {
                    "byteStart": _byte_offset(text, start),
                    "byteEnd": _byte_offset(text, start) + len(link.encode("utf-8")),
                },
                "features": [{
                    "$type": "app.bsky.richtext.facet#link",
                    "uri": link,
                }],
            })

        # Tag facets — every #word becomes clickable.
        facets.extend(_build_tag_facets(text))

        # Mention facets — alias hits in the prose.
        facets.extend(_build_mention_facets(client, text))

        if facets:
            record["facets"] = facets

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
            if return_cid:
                return bsky_uri, bsky_cid
            return bsky_uri
        except httpx.HTTPError:
            logger.exception("Failed to post Bluesky record")
            return None

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
            return _maybe_append_attribution(text, post.source_name, max_chars)

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
        text = text[:max_chars]
        return _maybe_append_attribution(text, post.source_name, max_chars)

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
    is_thread: bool = False,
) -> None:
    """Record a successful daily-summary share keyed by date.

    ``summary_date`` is YYYY-MM-DD (caller decides timezone). UNIQUE
    on ``summary_date`` enforces "one summary per day"; INSERT OR
    REPLACE means a manual re-share with the same date overwrites
    the row (useful for testing — the idempotency check happens
    upstream in ``share_daily_summary``).

    When ``is_thread=True``, ``root_uri`` / ``root_cid`` are populated
    alongside the legacy ``bsky_uri`` / ``bsky_cid`` (same values —
    the duplication is intentional so downstream readers can use
    either column without thread-awareness). Per-post rows for the
    thread chain live in ``bluesky_thread_posts``; insert them via
    ``record_thread_posts`` after this call.
    """
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO bluesky_daily_summaries "
        "(summary_date, bsky_uri, bsky_cid, post_text, shared_at, "
        " root_uri, root_cid, is_thread) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            summary_date,
            bsky_uri,
            bsky_cid,
            post_text,
            datetime.utcnow().isoformat(),
            bsky_uri if is_thread else None,
            bsky_cid if is_thread else None,
            1 if is_thread else 0,
        ),
    )
    conn.commit()
    conn.close()


def record_thread_posts(
    summary_date: str,
    thread_uris: list[str],
    posts: list[str],
) -> None:
    """Persist per-post rows for a threaded daily-summary share.

    ``thread_uris[i]`` corresponds to ``posts[i]`` (root is position 0).
    The (summary_date, position) tuple is UNIQUE so a re-share on the
    same date replaces prior rows cleanly.
    """
    if not thread_uris:
        return
    conn = get_connection()
    rows = [
        (
            summary_date,
            i,
            uri,
            posts[i] if i < len(posts) else "",
            datetime.utcnow().isoformat(),
        )
        for i, uri in enumerate(thread_uris)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO bluesky_thread_posts "
        "(summary_date, position, bsky_uri, post_text, posted_at) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
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
