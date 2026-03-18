"""Auto-generate images for articles that have no image.

Searches Unsplash for a relevant stock photo. When Unsplash is not
configured or returns nothing, falls back to a static topic-based
placeholder URL. Images are saved to data/images/ and served as
static assets.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from .config import get_settings
from .models import RawArticle

logger = logging.getLogger(__name__)

# Unsplash fallback queries per topic -- broad enough to always return results.
# Used when the article-specific query finds nothing.
TOPIC_FALLBACK_QUERIES: dict[str, str] = {
    "hardware": "quantum computer processor chip technology",
    "algorithms": "abstract mathematics algorithm visualization",
    "error_correction": "digital error correction computing grid",
    "cryptography": "cybersecurity encryption digital lock",
    "machine_learning": "artificial intelligence neural network",
    "simulation": "molecular simulation chemistry laboratory",
    "sensing": "precision measurement scientific instrument",
    "industry": "technology startup modern office",
    "research": "scientific research laboratory experiment",
    "policy": "government technology policy building",
    "general": "quantum physics abstract light",
}

# Default fallback if everything fails (no API key, no network, etc.)
DEFAULT_FALLBACK_QUERY = "quantum physics abstract light"


def _build_search_query(article: RawArticle) -> str:
    """Build a search query from article topics and title keywords.

    Extracts meaningful words from the title and combines with topic names
    to form a concise Unsplash search query.
    """
    parts: list[str] = []

    # Add first topic
    if article.topics:
        parts.append(article.topics[0].value.replace("_", " "))

    # Add key title words (skip short/common words)
    stop_words = {
        "a", "an", "the", "of", "in", "on", "for", "to", "and", "or",
        "is", "are", "was", "were", "with", "from", "by", "at", "as",
        "its", "it", "this", "that", "new", "via", "using", "based",
    }
    title_words = [
        w for w in article.title.split()
        if len(w) > 3 and w.lower().strip(":-,.'\"()") not in stop_words
    ]
    parts.extend(title_words[:4])

    query = " ".join(parts) if parts else DEFAULT_FALLBACK_QUERY
    return query[:100]  # Unsplash query length limit


def _get_topic_fallback_query(article: RawArticle) -> str:
    """Get a broad fallback query based on the article's primary topic."""
    if article.topics:
        topic_key = article.topics[0].value
        return TOPIC_FALLBACK_QUERIES.get(topic_key, DEFAULT_FALLBACK_QUERY)
    return DEFAULT_FALLBACK_QUERY


async def search_unsplash(query: str, api_key: str) -> str | None:
    """Search Unsplash for a relevant photo.

    Args:
        query: Search query string.
        api_key: Unsplash API access key.

    Returns:
        URL to the regular-sized image, or None if nothing found.
    """
    url = "https://api.unsplash.com/search/photos"
    params = {
        "query": query,
        "per_page": "1",
        "orientation": "landscape",
    }
    headers = {
        "Authorization": f"Client-ID {api_key}",
        "Accept-Version": "v1",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                return None

            image_url = results[0].get("urls", {}).get("regular")
            return image_url or None

    except Exception as e:
        logger.warning("Unsplash search failed for %r: %s", query, e)
        return None


async def _download_image(url: str) -> bytes | None:
    """Download image bytes from a URL."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type:
                logger.warning("Non-image content-type from %s: %s", url, content_type)
                return None
            return resp.content
    except Exception as e:
        logger.warning("Image download failed from %s: %s", url, e)
        return None


async def ensure_article_image(
    article: RawArticle,
    data_dir: Path,
    base_url: str,
) -> str:
    """Ensure an article has an image, fetching one from Unsplash if needed.

    Flow:
      1. Search Unsplash with article-specific query (title + topics)
      2. If no result, retry with a broader topic-based fallback query
      3. If Unsplash not configured or fails entirely, return ""

    Saves downloaded images to data_dir/images/ for persistence across rebuilds.

    Args:
        article: The article needing an image.
        data_dir: Path to data directory (e.g. Path("data")).
        base_url: Site base URL for constructing image paths.

    Returns:
        Image URL (relative to site) or "" on total failure.
    """
    settings = get_settings()
    image_dir = data_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    file_stem = article.id[:8]
    image_path = image_dir / f"{file_stem}.jpg"

    # If already generated from a previous run, reuse it
    if image_path.exists() and image_path.stat().st_size > 0:
        return f"{base_url.rstrip('/')}/static/images/generated/{file_stem}.jpg"

    if not settings.unsplash_api_key:
        return ""

    image_bytes: bytes | None = None

    # 1. Try article-specific query
    query = _build_search_query(article)
    logger.info("Searching Unsplash for: %s", query)
    unsplash_url = await search_unsplash(query, settings.unsplash_api_key)
    if unsplash_url:
        image_bytes = await _download_image(unsplash_url)

    # 2. Fall back to broad topic query
    if image_bytes is None:
        fallback_query = _get_topic_fallback_query(article)
        logger.info("Trying Unsplash fallback query: %s", fallback_query)
        unsplash_url = await search_unsplash(fallback_query, settings.unsplash_api_key)
        if unsplash_url:
            image_bytes = await _download_image(unsplash_url)

    if image_bytes is None:
        logger.info("No image found for article %s", article.id[:8])
        return ""

    # Save to disk
    image_path.write_bytes(image_bytes)
    logger.info("Saved image: %s (%d bytes)", image_path, len(image_bytes))

    return f"{base_url.rstrip('/')}/static/images/generated/{file_stem}.jpg"
