"""
PDF extractor — extracts text from PDF files via pdfplumber.
"""

import asyncio
from pathlib import Path

from .base import StatusCallback


class PDFExtractor:
    async def extract(self, file_path: Path, on_status: StatusCallback) -> str:
        await on_status("extracting", "Extracting text from PDF…")
        text = await asyncio.to_thread(self._run, file_path)
        if not text.strip():
            raise ValueError(
                "No text could be extracted from this PDF. "
                "It may be a scanned document or image-only PDF."
            )
        return text

    def _run(self, file_path: Path) -> str:
        import pdfplumber

        pages: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t.strip())
        return "\n\n".join(pages)
