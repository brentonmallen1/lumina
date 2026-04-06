"""
Image extractor — validates an image file and returns its base64 encoding.

Unlike other extractors, there is no text extraction step. The raw image
bytes are base64-encoded and passed directly to a vision-capable LLM.
"""

import base64
from pathlib import Path

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class ImageExtractor:
    def extract(self, file_path: Path) -> str:
        """
        Read image bytes and return a base64-encoded string.
        Raises ValueError for unsupported file types.
        """
        suffix = file_path.suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported image type: {suffix}. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )
        return base64.b64encode(file_path.read_bytes()).decode()
