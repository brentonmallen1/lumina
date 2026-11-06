"""
Source extraction shared by the job handler and the streaming endpoints.

``extract_source`` turns a (source_type, source_ref) pair into
``(text, meta)`` where ``meta`` feeds ``llm.runner.build_source_header``
(title, uploader, duration, description, chapters, url, …).

YouTube and webpage extractions are cached in the ``extraction_cache`` table,
so running a second mode on the same video doesn't re-download anything.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable

import db

logger = logging.getLogger(__name__)

StatusFn = Callable[[str, str], Awaitable[None]]

CACHEABLE = {"youtube", "url"}


def _cache_key(source_type: str, source_ref: str, config: dict) -> str:
    from jobs.cache import compute_content_hash
    ref = source_ref
    if source_type == "youtube" and not config.get("prefer_captions", True):
        ref = f"{source_ref}#audio-transcription"
    return compute_content_hash(source_type, ref)


async def extract_source(
    source_type: str,
    source_ref: str,
    *,
    config: dict | None = None,
    settings: dict | None = None,
    on_status: StatusFn,
) -> tuple[str, dict]:
    config = config or {}
    settings = settings if settings is not None else db.get_all_settings()

    cache_key = None
    if source_type in CACHEABLE:
        cache_key = _cache_key(source_type, source_ref, config)
        if not config.get("refresh"):
            cached = db.get_extraction_cache(cache_key)
            if cached and cached.get("extracted_text"):
                await on_status("extracting", "Using cached transcript…" if source_type == "youtube"
                                else "Using cached page content…")
                meta = dict(cached.get("metadata") or {})
                meta.setdefault("title", cached.get("title"))
                return cached["extracted_text"], meta

    if source_type == "youtube":
        text, meta = await _extract_youtube(source_ref, config, settings, on_status)
    elif source_type in ("url", "webpage"):
        from extractors.webpage import WebpageExtractor
        extractor = WebpageExtractor()
        text = await extractor.extract(source_ref, on_status)
        meta = {"title": extractor.title, "url": source_ref}
    elif source_type == "pdf":
        from extractors.pdf import PDFExtractor
        path = Path(source_ref)
        text = await PDFExtractor().extract(path, on_status)
        meta = {"title": path.stem}
    elif source_type in ("audio", "video", "file"):
        from extractors.audio import AudioExtractor
        from extractors.video import VideoExtractor
        from transcriber import get_engine
        path = Path(source_ref)
        engine = await asyncio.to_thread(get_engine)
        cls = VideoExtractor if path.suffix.lower() in VIDEO_EXTENSIONS else AudioExtractor
        text = await cls(engine=engine).extract(path, on_status)
        meta = {"title": path.stem}
    else:
        raise ValueError(f"Unknown source type: {source_type}")

    meta = {k: v for k, v in meta.items() if v not in (None, "", [])}

    if cache_key and text:
        try:
            db.set_extraction_cache(
                cache_key, source_type, source_ref, text,
                title=meta.get("title"), metadata=meta,
            )
        except Exception as exc:  # cache is best-effort
            logger.warning(f"Could not cache extraction for {source_ref}: {exc}")

    return text, meta


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".m4v"}


async def _extract_youtube(url: str, config: dict, settings: dict, on_status: StatusFn) -> tuple[str, dict]:
    from extractors.youtube import YouTubeExtractor

    cookies = settings.get("youtube_cookies") or None
    extractor = YouTubeExtractor(
        engine=None,  # resolved lazily only if we fall back to audio transcription
        prefer_captions=config.get("prefer_captions", True),
        cookies=cookies,
        language=config.get("language") or settings.get("language") or None,
    )
    text, meta = await extractor.extract_with_meta(url, on_status)
    meta.setdefault("url", url)
    return text, meta
