"""
Video extractor — strips audio with ffmpeg, optionally enhances, then transcribes.
Accepts common video formats: mp4, mkv, avi, mov, wmv, flv, m4v, webm.
"""

import asyncio
import subprocess
import tempfile
from pathlib import Path

from .base import StatusCallback


class VideoExtractor:
    def __init__(self, engine, pipeline=None, options=None) -> None:
        self.engine   = engine
        self.pipeline = pipeline   # AudioPipeline | None
        self.options  = options    # EnhancementOptions | None

    async def extract(self, file_path: Path, on_status: StatusCallback) -> str:
        await on_status("extracting", "Extracting audio track from video…")
        audio_path = await asyncio.to_thread(self._strip_audio, file_path)
        await on_status("extracting", "Audio extracted — preparing for transcription…")

        enhanced = audio_path
        try:
            if self.pipeline and self.options and self.options.any_active:
                await on_status("extracting", "Enhancing audio…")
                enhanced = await self.pipeline.run(audio_path, self.options, on_status)
                await on_status("extracting", "Audio enhancement complete")

            await on_status("transcribing", "Running Whisper transcription — this may take a while…")
            transcript = await asyncio.to_thread(self._transcribe, enhanced)
            await on_status("transcribing", "Transcription complete")
            return transcript
        finally:
            audio_path.unlink(missing_ok=True)
            if enhanced != audio_path:
                enhanced.unlink(missing_ok=True)

    def _strip_audio(self, file_path: Path) -> Path:
        tmp = Path(tempfile.mktemp(suffix=".mp3"))
        try:
            subprocess.run(
                [
                    "ffmpeg", "-i", str(file_path),
                    "-vn",           # no video
                    "-acodec", "mp3",
                    "-y",
                    str(tmp),
                ],
                check=True,
                capture_output=True,
                timeout=300,  # 5 minute timeout for audio extraction
            )
        except subprocess.TimeoutExpired:
            tmp.unlink(missing_ok=True)
            raise ValueError("Audio extraction timed out — video may be too large or corrupted")
        return tmp

    def _transcribe(self, audio_path: Path) -> str:
        result = self.engine.transcribe(str(audio_path))
        return result.get("text", "") if isinstance(result, dict) else result
