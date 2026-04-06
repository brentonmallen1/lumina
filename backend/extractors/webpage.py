"""
Webpage extractor — fetches a URL via Playwright (headless Chromium) and
extracts the main article content using readability-lxml.
"""

import re

from .base import StatusCallback

# Stealth UA — reduces bot detection for most news / article sites.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class WebpageExtractor:
    async def extract(self, url: str, on_status: StatusCallback) -> str:
        await on_status("extracting", "Fetching and parsing webpage…")
        return await self._fetch(url)

    async def _fetch(self, url: str) -> str:
        from playwright.async_api import async_playwright
        from readability import Document

        html = await self._load_html(url)
        doc = Document(html)
        # readability returns article HTML — strip all tags for plain text
        raw = doc.summary()
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            raise ValueError("Could not extract readable content from this URL.")

        return text

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
