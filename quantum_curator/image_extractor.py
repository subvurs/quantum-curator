"""OG image fallback extraction for articles missing images."""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from .config import get_settings


async def extract_og_image(url: str, timeout: int | None = None) -> str:
    """Fetch a page and extract the og:image meta tag.

    Args:
        url: Article URL to fetch.
        timeout: HTTP timeout in seconds (default from settings, capped at 10).

    Returns:
        Image URL string, or "" if extraction fails.
    """
    settings = get_settings()
    timeout = timeout or min(settings.fetch_timeout, 10)

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "QuantumCurator/1.0 (image-extractor)"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.lower():
                return ""

            soup = BeautifulSoup(response.text[:50000], "lxml")

            # Try og:image first
            og_tag = soup.find("meta", property="og:image")
            if og_tag and og_tag.get("content"):
                return og_tag["content"]

            # Try twitter:image
            tw_tag = soup.find("meta", attrs={"name": "twitter:image"})
            if tw_tag and tw_tag.get("content"):
                return tw_tag["content"]

            # Fallback: first reasonably-sized image in content
            for img in soup.find_all("img", src=True):
                src = img["src"]
                width = img.get("width", "")
                height = img.get("height", "")
                try:
                    if width and int(width) < 200:
                        continue
                    if height and int(height) < 100:
                        continue
                except ValueError:
                    pass
                if src.startswith("data:") or src.endswith(".svg"):
                    continue
                return src

    except Exception:
        pass

    return ""
