"""
Audio extractor — transcribes audio files via the loaded Whisper engine.
Accepts any audio format supported by the engine (mp3, wav, m4a, flac, …).
"""

import asyncio
from pathlib import Path

from .base import StatusCallback


class AudioExtractor:
    def __init__(self, engine) -> None:
        self.engine = engine

    async def extract(self, file_path: Path, on_status: StatusCallback) -> str:
        await on_status("transcribing", "Running Whisper transcription — this may take a while…")
        return await asyncio.to_thread(self._run, file_path)

    def _run(self, file_path: Path) -> str:
        return self.engine.transcribe(str(file_path))
