"""
Shared types for the extractor layer.

Each extractor exposes:
    async def extract(self, source, on_status: StatusCallback) -> str

`source` is either a Path (file-based) or a str URL.
`on_status` is called with (phase, detail) when the extractor transitions
between processing stages.  Phases: "extracting" | "transcribing".
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Coroutine, Any

# Async callback: on_status(phase, detail)
StatusCallback = Callable[[str, str], Coroutine[Any, Any, None]]


class Extractor(ABC):
    """Base class for content extractors."""

    @abstractmethod
    async def extract(
        self,
        source: str | Path,
        on_status: StatusCallback | None = None,
    ) -> str:
        """Extract text content from the source.

        Args:
            source: URL string or file Path
            on_status: Optional callback for progress updates

        Returns:
            Extracted text content
        """
        pass
