"""
YouTube extractor.

Fast path (default): fetch auto-generated captions via yt-dlp.
Fallback: download audio → Whisper transcription.

The fallback is also used when prefer_captions=False or when captions
aren't available for the video.

Also provides standalone download helpers used by the YouTube download tool:
  get_video_info()   — fetch metadata without downloading
  download_video()   — download video+audio, optionally remuxed
  download_audio()   — extract/convert audio to a target format

All functions accept an optional `cookies` parameter (Netscape-format cookie
text). When provided it is written to a temp file and passed to yt-dlp as
`cookiefile`, enabling authenticated / rate-limit-bypassing requests.
"""

import asyncio
import contextlib
import shutil
import tempfile
from pathlib import Path

from .base import StatusCallback


# ── Cookie helper ──────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _cookies_file(cookies_text: str | None):
    """
    Write Netscape-format cookie text to a temp file, yield the path, then
    delete it. Yields None if cookies_text is empty so callers can always use
    the same pattern:

        with _cookies_file(cookies) as cf:
            opts = {"cookiefile": cf, ...} if cf else {...}
    """
    if not cookies_text or not cookies_text.strip():
        yield None
        return
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(cookies_text)
        path = f.name
    try:
        yield path
    finally:
        Path(path).unlink(missing_ok=True)


# ── Standalone download helpers ────────────────────────────────────────────────

_VALID_VIDEO_FORMATS   = {"mp4", "webm", "mkv"}
_VALID_AUDIO_FORMATS   = {"mp3", "m4a", "flac", "wav", "ogg", "opus"}
_VALID_VIDEO_QUALITIES = {"best", "2160", "1080", "720", "480", "360"}


def get_video_info(url: str, cookies: str | None = None) -> dict:
    """
    Fetch video metadata without downloading.
    Returns: { title, description, duration_seconds, thumbnail, uploader }
    Raises ValueError for invalid / private / unavailable videos.
    """
    import yt_dlp

    with _cookies_file(cookies) as cf:
        ydl_opts: dict = {
            "quiet":          True,
            "no_warnings":    True,
            "skip_download":  True,
            "socket_timeout": 15,
        }
        if cf:
            ydl_opts["cookiefile"] = cf

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as exc:
                raise ValueError(str(exc)) from exc

    return _info_summary(info)


def _info_summary(info: dict) -> dict:
    return {
        "title":            info.get("title", ""),
        "description":      info.get("description", ""),
        "duration_seconds": info.get("duration"),
        "thumbnail":        info.get("thumbnail"),
        "uploader":         info.get("uploader") or info.get("channel") or "",
        "upload_date":      info.get("upload_date"),
        "chapters":         [
            {"start_time": c.get("start_time", 0), "title": c.get("title", "")}
            for c in (info.get("chapters") or [])
        ],
        "webpage_url":      info.get("webpage_url"),
        "video_id":         info.get("id"),
        "language":         info.get("language"),
    }


def source_meta_from_info(summary: dict) -> dict:
    """Map a get_video_info() summary to the runner's source-header keys."""
    return {
        "title":       summary.get("title"),
        "uploader":    summary.get("uploader"),
        "duration":    summary.get("duration_seconds"),
        "upload_date": summary.get("upload_date"),
        "description": summary.get("description"),
        "chapters":    summary.get("chapters") or [],
        "url":         summary.get("webpage_url"),
        "video_id":    summary.get("video_id"),
        "thumbnail":   summary.get("thumbnail"),
    }


def download_video(
    url: str,
    output_dir: Path,
    quality: str = "best",
    fmt: str = "mp4",
    cookies: str | None = None,
) -> Path:
    """
    Download video+audio and remux to the requested container/codec.

    quality: "best" | "2160" | "1080" | "720" | "480" | "360"
    fmt:     "mp4" | "webm" | "mkv"

    Returns the path to the downloaded file.
    """
    import yt_dlp

    if quality == "best":
        format_spec = "bestvideo+bestaudio/best"
    else:
        format_spec = (
            f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
        )

    with _cookies_file(cookies) as cf:
        ydl_opts: dict = {
            "format":              format_spec,
            "merge_output_format": fmt,
            "outtmpl":             str(output_dir / "%(title)s.%(ext)s"),
            "quiet":               True,
            "no_warnings":         True,
            "writethumbnail":      False,
            "socket_timeout":      30,
            "retries":             3,
        }
        if cf:
            ydl_opts["cookiefile"] = cf

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            path = Path(filename)
            if not path.exists():
                candidates = list(output_dir.glob(f"{path.stem}.*"))
                if candidates:
                    path = candidates[0]

    return path


def download_audio(
    url: str,
    output_dir: Path,
    fmt: str = "mp3",
    quality: str = "192",
    cookies: str | None = None,
) -> Path:
    """
    Download and extract audio in the requested format.

    fmt:     "mp3" | "m4a" | "flac" | "wav" | "ogg" | "opus"
    quality: bitrate string for lossy formats ("128","192","256","320")
             or "best" (ignored for lossless)

    Returns the path to the downloaded file.
    """
    import yt_dlp

    codec_map = {
        "mp3":  "mp3",
        "m4a":  "m4a",
        "flac": "flac",
        "wav":  "wav",
        "ogg":  "vorbis",
        "opus": "opus",
    }
    codec = codec_map.get(fmt, "mp3")
    lossless = fmt in ("flac", "wav")

    postprocessor: dict = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
    if not lossless and quality.isdigit():
        postprocessor["preferredquality"] = quality

    with _cookies_file(cookies) as cf:
        ydl_opts: dict = {
            "format":         "bestaudio/best",
            "outtmpl":        str(output_dir / "%(title)s.%(ext)s"),
            "postprocessors": [postprocessor],
            "quiet":          True,
            "no_warnings":    True,
            "socket_timeout": 30,
            "retries":        3,
        }
        if cf:
            ydl_opts["cookiefile"] = cf

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            stem = Path(ydl.prepare_filename(info)).stem
            output_file = output_dir / f"{stem}.{fmt}"
            if not output_file.exists():
                alt = output_dir / f"{stem}.ogg" if fmt == "ogg" else None
                if alt and alt.exists():
                    output_file = alt
                else:
                    candidates = list(output_dir.glob(f"{stem}.*"))
                    if candidates:
                        output_file = candidates[0]

    return output_file


# Languages tried, in order, when no explicit language is requested.
_FALLBACK_LANGS = ["en", "en-US", "en-GB"]
# Preferred caption formats (json3 carries exact cue timing; vtt is the fallback).
_CAPTION_EXTS = ("json3", "vtt")


def _pick_caption_track(info: dict, language: str | None) -> tuple[dict, str, bool] | None:
    """Choose the best caption track. Returns (track, lang, is_auto) or None.

    Order: requested language → the video's original language → English;
    for each, human-made subtitles beat auto-generated captions. For auto
    captions, YouTube's "<lang>-orig" track is the untranslated original.
    """
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    original = (info.get("language") or "").split("-")[0] or None

    prefs: list[str] = []
    for lang in [language, original, *_FALLBACK_LANGS]:
        if lang and lang not in prefs:
            prefs.append(lang)

    def best(tracks: list[dict]) -> dict | None:
        for ext in _CAPTION_EXTS:
            for t in tracks:
                if t.get("ext") == ext and t.get("url"):
                    return t
        return None

    for lang in prefs:
        for key in (lang, *[k for k in manual if k.split("-")[0] == lang]):
            if key in manual and (t := best(manual[key])):
                return t, key, False
        for key in (f"{lang}-orig", lang):
            if key in auto and (t := best(auto[key])):
                return t, key, True
    return None


class YouTubeExtractor:
    def __init__(
        self,
        engine=None,
        prefer_captions: bool = True,
        cookies: str | None = None,
        language: str | None = None,
    ) -> None:
        # engine may be None: it's resolved lazily (shared instance) only when
        # we fall back to audio transcription.
        self.engine = engine
        self.prefer_captions = prefer_captions
        self.cookies = cookies
        self.language = language

    # ── Public ────────────────────────────────────────────────────────────────

    async def extract(self, url: str, on_status: StatusCallback) -> str:
        text, _meta = await self.extract_with_meta(url, on_status)
        return text

    async def extract_with_meta(self, url: str, on_status: StatusCallback) -> tuple[str, dict]:
        """Timestamped transcript plus video metadata (title, description, chapters…).

        One yt-dlp metadata request provides both the metadata and the caption
        track URLs; audio is only downloaded when no usable captions exist.
        """
        await on_status("extracting", "Fetching video info…")
        info, captions = await asyncio.to_thread(self._info_and_captions, url)
        meta = source_meta_from_info(_info_summary(info))
        if meta.get("title"):
            await on_status("extracting", f"Found: {meta['title'][:80]}")

        if captions:
            text, lang, is_auto = captions
            meta["transcript_source"] = f"{'auto-captions' if is_auto else 'captions'} ({lang})"
            await on_status("extracting", f"Using {'auto-generated' if is_auto else 'uploaded'} captions ({lang})")
            return text, meta

        if self.prefer_captions:
            await on_status("extracting", "No captions available — transcribing the audio instead")
        await on_status("extracting", "Downloading audio from YouTube…")
        audio_path, tmpdir = await asyncio.to_thread(self._download_audio, url)
        try:
            await on_status("transcribing", "Transcribing audio — this may take a while…")
            text = await asyncio.to_thread(self._transcribe, audio_path)
            await on_status("transcribing", "Transcription complete")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        meta["transcript_source"] = "audio transcription"
        return text, meta

    # ── Private ───────────────────────────────────────────────────────────────

    def _ydl_opts(self, cookiefile: str | None) -> dict:
        opts: dict = {
            "quiet":          True,
            "no_warnings":    True,
            "skip_download":  True,
            "socket_timeout": 30,
            "retries":        3,
        }
        if cookiefile:
            opts["cookiefile"] = cookiefile
        return opts

    def _info_and_captions(self, url: str) -> tuple[dict, tuple[str, str, bool] | None]:
        import yt_dlp
        from .captions import caption_track_to_text

        with _cookies_file(self.cookies) as cf:
            with yt_dlp.YoutubeDL(self._ydl_opts(cf)) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                except Exception as exc:
                    raise ValueError(f"Could not load video: {exc}") from exc
                if not self.prefer_captions:
                    return info, None
                picked = _pick_caption_track(info, self.language)
                if not picked:
                    return info, None
                track, lang, is_auto = picked
                try:
                    # ydl.urlopen reuses yt-dlp's headers, cookies and proxy settings.
                    raw = ydl.urlopen(track["url"]).read()
                    text = caption_track_to_text(raw, track["ext"])
                except Exception:
                    return info, None
                return info, ((text, lang, is_auto) if text.strip() else None)

    def _download_audio(self, url: str) -> tuple[Path, Path]:
        """Download best audio track. Returns (audio_path, tmpdir) — caller cleans up tmpdir."""
        import yt_dlp

        tmpdir = Path(tempfile.mkdtemp())
        with _cookies_file(self.cookies) as cf:
            ydl_opts: dict = {
                "format":  "bestaudio/best",
                "outtmpl": str(tmpdir / "%(id)s.%(ext)s"),
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}
                ],
                "quiet":       True,
                "no_warnings": True,
                "socket_timeout": 30,
                "retries":        3,
            }
            if cf:
                ydl_opts["cookiefile"] = cf

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id = info["id"]

        return tmpdir / f"{video_id}.mp3", tmpdir

    def _transcribe(self, audio_path: Path) -> str:
        from .captions import segments_from_engine, to_paragraphs

        if self.engine is None:
            from transcriber import get_engine
            self.engine = get_engine()
        # Engines take only the path; their language comes from settings.
        return to_paragraphs(segments_from_engine(self.engine.transcribe(str(audio_path))))
