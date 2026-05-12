"""
PDF extractor — extracts text or renders pages as images for vision models.

Text extraction uses pdfplumber. Image rendering uses PyMuPDF (fitz).
"""

import asyncio
import base64
from pathlib import Path

from .base import StatusCallback

_MAX_PAGES_TEXT = 200
_MAX_PAGES_VISION = 10
_VISION_DPI = 150


class PDFExtractor:
    async def extract(self, file_path: Path, on_status: StatusCallback) -> str:
        """Extract text from PDF using pdfplumber."""
        await on_status("extracting", "Extracting text from PDF…")
        text = await asyncio.to_thread(self._extract_text, file_path)
        if not text.strip():
            raise ValueError(
                "No text could be extracted from this PDF. "
                "It may be a scanned document or image-only PDF."
            )
        return text

    async def extract_images(
        self,
        file_path: Path,
        on_status: StatusCallback,
        max_pages: int | None = None,
    ) -> list[str]:
        """Render PDF pages as base64 PNG images for vision models."""
        limit = max_pages if max_pages is not None else _MAX_PAGES_VISION
        await on_status("extracting", f"Rendering PDF pages as images (up to {limit})…")
        return await asyncio.to_thread(self._render_pages, file_path, limit)

    def _extract_text(self, file_path: Path) -> str:
        import pdfplumber

        pages: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                if i >= _MAX_PAGES_TEXT:
                    pages.append(f"\n[Truncated: showing {_MAX_PAGES_TEXT} of {total_pages} pages]")
                    break
                t = page.extract_text()
                if t:
                    pages.append(t.strip())
        return "\n\n".join(pages)

    def _render_pages(self, file_path: Path, max_pages: int) -> list[str]:
        import fitz

        images: list[str] = []
        with fitz.open(file_path) as doc:
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                pix = page.get_pixmap(dpi=_VISION_DPI)
                png_bytes = pix.tobytes("png")
                images.append(base64.b64encode(png_bytes).decode("ascii"))
        return images
