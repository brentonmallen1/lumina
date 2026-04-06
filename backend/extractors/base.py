"""
Shared types for the extractor layer.

Each extractor exposes:
    async def extract(self, source, on_status: StatusCallback) -> str

`source` is either a Path (file-based) or a str URL.
`on_status` is called with (phase, detail) when the extractor transitions
between processing stages.  Phases: "extracting" | "transcribing".
"""

from typing import Callable, Coroutine, Any

# Async callback: on_status(phase, detail)
StatusCallback = Callable[[str, str], Coroutine[Any, Any, None]]
