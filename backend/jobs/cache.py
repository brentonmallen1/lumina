"""Extraction cache utilities.

Provides hash computation and thumbnail processing for content caching.
"""

import base64
import hashlib
import io
import logging
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


def compute_content_hash(source_type: str, source_ref: str, file_path: Path | None = None) -> str:
    """Compute a content hash for cache lookup.

    Hash strategy by source type:
    - youtube: sha256(f"youtube:{video_id}")
    - url: sha256(normalized_url)
    - file: sha256(first 1MB + size + name)
    - text: sha256(text_content)
    """
    if source_type == "youtube":
        video_id = extract_youtube_video_id(source_ref)
        if video_id:
            return hashlib.sha256(f"youtube:{video_id}".encode()).hexdigest()
        # Fall back to URL hash
        return hashlib.sha256(source_ref.encode()).hexdigest()

    elif source_type in ("url", "webpage"):
        normalized = normalize_url(source_ref)
        return hashlib.sha256(normalized.encode()).hexdigest()

    elif source_type == "text":
        return hashlib.sha256(source_ref.encode()).hexdigest()

    elif file_path and file_path.exists():
        # Hash first 1MB + file size + name
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            h.update(f.read(1024 * 1024))  # First 1MB
        h.update(str(file_path.stat().st_size).encode())
        h.update(file_path.name.encode())
        return h.hexdigest()

    else:
        # Generic hash of source_ref
        return hashlib.sha256(source_ref.encode()).hexdigest()


def extract_youtube_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    # youtube.com/watch?v=VIDEO_ID
    # youtu.be/VIDEO_ID
    # youtube.com/embed/VIDEO_ID
    # youtube.com/v/VIDEO_ID

    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",  # Just the video ID
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    # Try parsing as URL
    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc:
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]

    return None


def normalize_url(url: str) -> str:
    """Normalize URL for consistent hashing.

    - Lowercase scheme and host
    - Remove common tracking parameters
    - Sort query parameters
    - Remove trailing slashes
    """
    parsed = urlparse(url.lower())

    # Remove tracking parameters
    tracking_params = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "ref", "referrer", "fbclid", "gclid", "mc_cid", "mc_eid",
    }

    qs = parse_qs(parsed.query)
    filtered_qs = {k: v for k, v in qs.items() if k.lower() not in tracking_params}

    # Sort and rebuild query string
    sorted_qs = "&".join(
        f"{k}={v[0]}" for k, v in sorted(filtered_qs.items())
    )

    # Rebuild URL
    path = parsed.path.rstrip("/") or "/"
    if sorted_qs:
        return f"{parsed.scheme}://{parsed.netloc}{path}?{sorted_qs}"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def process_thumbnail(image_data: bytes, max_size: int = 256, quality: int = 80) -> str:
    """Resize and convert image to base64 WebP.

    Args:
        image_data: Raw image bytes
        max_size: Maximum width/height (maintains aspect ratio)
        quality: WebP quality (1-100)

    Returns:
        Base64-encoded WebP image
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_data))

        # Convert to RGB if necessary (for WebP)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Resize maintaining aspect ratio
        img.thumbnail((max_size, max_size))

        # Convert to WebP
        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=quality)

        return base64.b64encode(buffer.getvalue()).decode()

    except ImportError:
        logger.warning("Pillow not installed, skipping thumbnail processing")
        return ""
    except Exception as e:
        logger.warning(f"Failed to process thumbnail: {e}")
        return ""


async def fetch_youtube_thumbnail(video_id: str) -> str:
    """Fetch and process YouTube video thumbnail.

    Tries high quality first, falls back to default.
    """
    import httpx

    thumbnail_urls = [
        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/default.jpg",
    ]

    async with httpx.AsyncClient() as client:
        for url in thumbnail_urls:
            try:
                resp = await client.get(url, timeout=10)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    return process_thumbnail(resp.content)
            except Exception as e:
                logger.debug(f"Failed to fetch thumbnail from {url}: {e}")
                continue

    return ""


async def fetch_og_image(url: str) -> str:
    """Fetch og:image from a webpage and process as thumbnail."""
    import httpx
    import re

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                return ""

            html = resp.text

            # Find og:image
            match = re.search(
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                html, re.IGNORECASE
            )
            if not match:
                match = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                    html, re.IGNORECASE
                )

            if not match:
                return ""

            image_url = match.group(1)

            # Fetch the image
            img_resp = await client.get(image_url, timeout=10)
            if img_resp.status_code == 200:
                return process_thumbnail(img_resp.content)

    except Exception as e:
        logger.debug(f"Failed to fetch og:image from {url}: {e}")

    return ""


async def fetch_page_title(url: str) -> str:
    """Fetch page title from a webpage."""
    import httpx
    import re

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                return ""

            html = resp.text

            # Find title tag
            match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                # Decode HTML entities
                import html as html_module
                return html_module.unescape(title)

    except Exception as e:
        logger.debug(f"Failed to fetch title from {url}: {e}")

    return ""
