"""
Webpage extractor — fetches a URL via Playwright (headless Chromium) and
extracts the main article content using readability-lxml.

Also extracts ld+json (schema.org) structured data when available (e.g., Recipe).
"""

import json
import re

from .base import StatusCallback

# Stealth UA — reduces bot detection for most news / article sites.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _parse_iso_duration(iso: str) -> str:
    """Convert ISO 8601 duration (PT1H30M) to human-readable format."""
    if not isinstance(iso, str) or not iso.startswith("PT"):
        return str(iso)
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return iso
    parts = []
    if m.group(1):
        h = int(m.group(1))
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m.group(2):
        mins = int(m.group(2))
        parts.append(f"{mins} minute{'s' if mins != 1 else ''}")
    if m.group(3):
        s = int(m.group(3))
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts) if parts else iso


def _is_recipe_type(type_val) -> bool:
    """Check if @type indicates a Recipe (handles string or array format)."""
    if type_val == "Recipe":
        return True
    if isinstance(type_val, list) and "Recipe" in type_val:
        return True
    return False


class WebpageExtractor:
    def __init__(self):
        self.title: str | None = None

    async def extract(self, url: str, on_status: StatusCallback) -> str:
        from readability import Document

        await on_status("extracting", "Loading webpage with browser…")
        html = await self._load_html(url)

        await on_status("extracting", "Checking for structured data (schema.org)…")
        structured = self._extract_ld_json(html)

        await on_status("extracting", "Extracting article content…")
        doc = Document(html)
        self.title = doc.title() or None

        raw = doc.summary()
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()

        if not text and not structured:
            raise ValueError("Could not extract readable content from this URL.")

        if structured:
            await on_status("extracting", "Found structured recipe data")
            return f"Structured data (schema.org):\n{structured}\n\nPage content:\n{text}"

        await on_status("extracting", "Content extracted")
        return text

    def _extract_ld_json(self, html: str) -> str | None:
        """Extract schema.org ld+json data from HTML, focusing on Recipe schema."""
        pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

        recipes = []
        for match in matches:
            try:
                data = json.loads(match)
                # Handle @graph format (array of objects)
                if isinstance(data, dict) and "@graph" in data:
                    data = data["@graph"]
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and _is_recipe_type(item.get("@type")):
                            recipes.append(self._format_recipe_schema(item))
                elif isinstance(data, dict) and _is_recipe_type(data.get("@type")):
                    recipes.append(self._format_recipe_schema(data))
            except (json.JSONDecodeError, TypeError):
                continue

        return "\n\n".join(recipes) if recipes else None

    def _format_recipe_schema(self, recipe: dict) -> str:
        """Format a schema.org Recipe object as readable text."""
        parts = []
        if recipe.get("name"):
            parts.append(f"Recipe: {recipe['name']}")
        if recipe.get("description"):
            parts.append(f"Description: {recipe['description']}")
        if recipe.get("prepTime"):
            parts.append(f"Prep time: {_parse_iso_duration(recipe['prepTime'])}")
        if recipe.get("cookTime"):
            parts.append(f"Cook time: {_parse_iso_duration(recipe['cookTime'])}")
        if recipe.get("totalTime"):
            parts.append(f"Total time: {_parse_iso_duration(recipe['totalTime'])}")
        if recipe.get("recipeYield"):
            yield_val = recipe["recipeYield"]
            if isinstance(yield_val, list):
                yield_val = yield_val[0]
            parts.append(f"Servings: {yield_val}")

        ingredients = recipe.get("recipeIngredient", [])
        if ingredients:
            parts.append("Ingredients:")
            for ing in ingredients:
                parts.append(f"  - {ing}")

        instructions = recipe.get("recipeInstructions", [])
        if instructions:
            parts.append("Instructions:")
            for i, step in enumerate(instructions, 1):
                if isinstance(step, dict):
                    text = step.get("text", str(step))
                else:
                    text = str(step)
                parts.append(f"  {i}. {text}")

        return "\n".join(parts)

    async def _load_html(self, url: str) -> str:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=_USER_AGENT)
            page = await context.new_page()
            try:
                # Try networkidle first; fall back to domcontentloaded on timeout.
                try:
                    await page.goto(url, wait_until="networkidle", timeout=25_000)
                except Exception:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                return await page.content()
            finally:
                await browser.close()
