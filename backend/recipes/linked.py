"""
Recipe pages linked from a video description.

Cooking videos often link a "print recipe" page whose HTML embeds the
creator's exact recipe as schema.org JSON-LD. When one is reachable, that
data beats anything reconstructed from a transcript.

This makes one plain HTTP request per candidate link. Sites that refuse
automated requests are reported back to the caller, and the video is used
instead — no attempt is made to get around such blocks.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Lumina/0.2; +self-hosted recipe import)",
    "Accept": "text/html,application/xhtml+xml",
}

# Links in descriptions that are never the recipe itself.
_SKIP_HOSTS = (
    "youtube.com", "youtu.be", "patreon.com", "amazon.", "amzn.", "instagram.com", "tiktok.com",
    "facebook.com", "fb.com", "twitter.com", "x.com", "threads.net", "linktr.ee", "pinterest.",
    "discord.", "twitch.tv", "spotify.com", "apple.com", "ko-fi.com", "buymeacoffee.com",
    "shopify.", "etsy.com", "geni.us", "skimresources", "rstyle.me", "ltk.app",
)
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def candidate_links(description: str | None, recipe_name: str | None = None, limit: int = 3) -> list[str]:
    """Description URLs most likely to be the recipe page, best first."""
    if not description:
        return []
    name_words = {w for w in re.findall(r"[a-z]{4,}", (recipe_name or "").lower())}
    scored: list[tuple[int, int, str]] = []
    lines = description.splitlines()
    for idx, line in enumerate(lines):
        for url in _URL_RE.findall(line):
            url = url.rstrip(".,;:!")
            host = urlparse(url).netloc.lower()
            if not host or any(s in host for s in _SKIP_HOSTS):
                continue
            context = " ".join(lines[max(0, idx - 1): idx + 1]).lower()
            path = urlparse(url).path.lower()
            score = 0
            if "recipe" in context or "recipe" in path:
                score += 3
            if "print" in context:
                score += 1
            score += sum(1 for w in name_words if w in path)
            if path.strip("/"):
                score += 1  # deep links beat bare home pages
            scored.append((score, -len(scored), url))
    seen, out = set(), []
    for score, _order, url in sorted(scored, reverse=True):
        # Only links that look like the recipe: labelled "recipe" nearby, or a
        # path that shares words with the recipe/video title. Skips sponsors.
        if score >= 3 and url not in seen:
            seen.add(url)
            out.append(url)
    return out[:limit]


def find_recipe_node(html: str) -> dict | None:
    """The first schema.org Recipe object embedded in a page's ld+json."""
    for raw in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(raw.strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                t = node.get("@type")
                if t == "Recipe" or (isinstance(t, list) and "Recipe" in t):
                    return node
                if "@graph" in node:
                    stack.append(node["@graph"])
    return None


class LinkedRecipe:
    def __init__(self, url: str, recipe: dict | None, error: str | None = None):
        self.url = url
        self.recipe = recipe
        self.error = error


async def fetch_linked_recipe(urls: list[str]) -> LinkedRecipe | None:
    """Try each candidate; return the first page with a usable Recipe, or the
    last failure (so the caller can explain why it fell back)."""
    last: LinkedRecipe | None = None
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=HEADERS) as client:
        for url in urls:
            try:
                r = await client.get(url)
            except httpx.HTTPError as exc:
                last = LinkedRecipe(url, None, f"couldn't be reached ({type(exc).__name__})")
                continue
            if r.status_code in (401, 403, 429, 503):
                last = LinkedRecipe(url, None, "doesn't allow automated requests")
                continue
            if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                last = LinkedRecipe(url, None, f"returned HTTP {r.status_code}")
                continue
            node = find_recipe_node(r.text)
            if node and node.get("recipeIngredient") and node.get("recipeInstructions"):
                return LinkedRecipe(str(r.url), node)
            last = LinkedRecipe(url, None, "has no recipe data")
    return last
