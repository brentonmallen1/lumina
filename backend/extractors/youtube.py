"""
YouTube extractor.

Fast path (default): fetch auto-generated captions via yt-dlp.
Fallback: download audio → Whisper transcription.

The fallback is also used when prefer_captions=False or when captions
aren't available for the video.
"""

import asyncio
import re
import shutil
import tempfile
from pathlib import Path

from .base import StatusCallback


class YouTubeExtractor:
    def __init__(self, engine, prefer_captions: bool = True) -> None:
        self.engine = engine
        self.prefer_captions = prefer_captions

    # ── Public ────────────────────────────────────────────────────────────────

    async def extract(self, url: str, on_status: StatusCallback) -> str:
        if self.prefer_captions:
            await on_status("extracting", "Fetching YouTube captions…")
            try:
                captions = await asyncio.to_thread(self._fetch_captions, url)
                if captions:
                    return captions
            except Exception:
                pass
            await on_status("extracting", "Captions unavailable — downloading audio…")
        else:
            await on_status("extracting", "Downloading YouTube audio…")

        audio_path, tmpdir = await asyncio.to_thread(self._download_audio, url)
        await on_status("transcribing", "Running Whisper transcription — this may take a while…")
        try:
            return await asyncio.to_thread(self._transcribe, audio_path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── Private ───────────────────────────────────────────────────────────────

    def _fetch_captions(self, url: str) -> str | None:
        import yt_dlp

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                "writeautomaticsub": True,
                "writesubtitles": True,
                "subtitleslangs": ["en", "en-US", "en-GB"],
                "subtitlesformat": "vtt",
                "skip_download": True,
                "outtmpl": f"{tmpdir}/%(id)s.%(ext)s",
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            vtt_files = list(Path(tmpdir).glob("*.vtt"))
            if not vtt_files:
                return None

            return self._parse_vtt(vtt_files[0].read_text(encoding="utf-8", errors="replace"))

    def _parse_vtt(self, vtt_text: str) -> str:
        """
        Extract clean text from a WebVTT file.

        YouTube auto-generated VTT has inline timing tags (<00:00:01.320>)
        and repeated cues. We deduplicate by cue text to get a clean transcript.
        """
        blocks = re.split(r"\n{2,}", vtt_text.strip())
        seen: set[str] = set()
        texts: list[str] = []

        for block in blocks:
            lines = block.strip().splitlines()
            if not lines:
                continue
            if lines[0].startswith("WEBVTT") or lines[0].startswith("NOTE"):
                continue

            text_parts: list[str] = []
            for line in lines:
                if "-->" in line or re.match(r"^\d+$", line.strip()):
                    continue
                # Strip inline timing tags and HTML
                line = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", line)
                line = re.sub(r"<[^>]+>", "", line)
                line = line.strip()
                if line:
                    text_parts.append(line)

            text = " ".join(text_parts)
            if text and text not in seen:
                seen.add(text)
                texts.append(text)

        return " ".join(texts)

    def _download_audio(self, url: str) -> tuple[Path, Path]:
        """Download best audio track. Returns (audio_path, tmpdir) — caller cleans up tmpdir."""
        import yt_dlp

        tmpdir = Path(tempfile.mkdtemp())
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(tmpdir / "%(id)s.%(ext)s"),
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}
            ],
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info["id"]

        return tmpdir / f"{video_id}.mp3", tmpdir

    def _transcribe(self, audio_path: Path) -> str:
        return self.engine.transcribe(str(audio_path))
