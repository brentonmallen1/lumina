"""Job type handlers for the worker.

Each handler is an async function that takes a job dict and returns
a result dict (or None if it handles completion itself).
"""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import db

if TYPE_CHECKING:
    from audio import AudioPipeline, EnhancementOptions

logger = logging.getLogger(__name__)


async def handle_transcribe(job: dict) -> dict | None:
    """Handle transcription jobs.

    Job config expected:
    - enhancement: dict with normalize, denoise, isolate, upsample flags
    - language: optional language code

    Job fields used:
    - input_file: path to audio file (relative to AUDIO_CACHE)
    """
    from audio import AudioPipeline, EnhancementOptions
    from transcriber import get_engine
    import os

    job_id = job["id"]
    config = job.get("config") or {}
    input_file = job.get("input_file")

    if not input_file:
        raise ValueError("No input file specified")

    # Resolve audio cache path
    cache_base = Path(os.getenv("AUDIO_CACHE_DIR", Path(__file__).parent.parent / "cache" / "audio"))
    audio_path = cache_base / input_file

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Enhancement options
    enhancement = config.get("enhancement") or {}
    opts = EnhancementOptions(
        normalize=enhancement.get("normalize", False),
        denoise=enhancement.get("denoise", False),
        isolate=enhancement.get("isolate", False),
        upsample=enhancement.get("upsample", False),
    )

    processed_path = audio_path

    # Apply audio enhancement if any options are enabled
    if opts.normalize or opts.denoise or opts.isolate or opts.upsample:
        db.update_job_status(job_id, "running", "Enhancing audio...")
        logger.info(f"Job {job_id}: Enhancing audio with {opts}")

        pipeline = AudioPipeline()
        processed_path = await asyncio.to_thread(
            pipeline.run_sync, str(audio_path), opts
        )
        processed_path = Path(processed_path)

    # Transcribe
    db.update_job_status(job_id, "running", "Transcribing...")
    logger.info(f"Job {job_id}: Transcribing {processed_path}")

    engine = await asyncio.to_thread(get_engine)
    if engine is None:
        raise RuntimeError("Transcription engine not loaded")

    # Run transcription in thread pool. Engines take only the path (language
    # comes from the engine's configuration); Canary/Qwen return plain text.
    raw = await asyncio.to_thread(engine.transcribe, str(processed_path))
    result = raw if isinstance(raw, dict) else {"text": raw or "", "segments": []}

    # Clean up enhanced temp file if different from original
    if processed_path != audio_path and processed_path.exists():
        try:
            processed_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to clean up temp file: {e}")

    return {
        "result": result.get("text", ""),
        "result_meta": {
            "segments": result.get("segments", []),
            "language": result.get("language", ""),
        },
    }


async def handle_enhance(job: dict) -> dict | None:
    """Handle audio enhancement jobs.

    Job config expected:
    - enhancement: dict with normalize, denoise, isolate, upsample flags
    """
    from audio import AudioPipeline, EnhancementOptions
    import os

    job_id = job["id"]
    config = job.get("config") or {}
    input_file = job.get("input_file")

    if not input_file:
        raise ValueError("No input file specified")

    cache_base = Path(os.getenv("AUDIO_CACHE_DIR", Path(__file__).parent.parent / "cache" / "audio"))
    audio_path = cache_base / input_file

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    enhancement = config.get("enhancement") or {}
    opts = EnhancementOptions(
        normalize=enhancement.get("normalize", False),
        denoise=enhancement.get("denoise", False),
        isolate=enhancement.get("isolate", False),
        upsample=enhancement.get("upsample", False),
    )

    if not (opts.normalize or opts.denoise or opts.isolate or opts.upsample):
        return {"result": "No enhancement options selected", "output_file": input_file}

    db.update_job_status(job_id, "running", "Enhancing audio...")
    logger.info(f"Job {job_id}: Enhancing audio")

    pipeline = AudioPipeline()
    output_path = await asyncio.to_thread(
        pipeline.run_sync, str(audio_path), opts
    )

    # Move output to cache directory with job_id prefix
    output_path = Path(output_path)
    final_name = f"{job_id}_enhanced{output_path.suffix}"
    final_path = cache_base / final_name

    if output_path != final_path:
        import shutil
        shutil.move(str(output_path), str(final_path))

    return {
        "result": "Audio enhanced successfully",
        "output_file": final_name,
    }


class JobCancelled(Exception):
    """Raised by a handler when it notices the user cancelled its job."""


async def handle_extract(job: dict) -> dict | None:
    """Handle content extraction jobs (YouTube, URL, PDF, audio, video).

    Job config expected:
    - prefer_captions: bool (for YouTube)
    """
    from sources import extract_source

    job_id = job["id"]
    source_type = job.get("source_type")
    source_ref = job.get("source_ref")
    config = job.get("config") or {}

    if not source_type or not source_ref:
        raise ValueError("Missing source_type or source_ref")

    db.update_job_status(job_id, "running", f"Extracting from {source_type}...")
    logger.info(f"Job {job_id}: Extracting from {source_type}: {source_ref}")

    async def on_status(phase: str, detail: str) -> None:
        db.update_job_status(job_id, "running", detail)

    text, meta = await extract_source(source_type, source_ref, config=config, on_status=on_status)

    return {
        "result": text,
        "result_meta": {"char_count": len(text), "source_meta": meta},
    }


async def handle_summarize(job: dict) -> dict | None:
    """Handle summarization jobs — the path the UI uses for YouTube and URLs.

    Job config:
    - mode: summary type (summary, key_points, mind_map, …)
    - model: optional model override
    - extracted_text: text to process (skips extraction when present)
    - prefer_captions / refresh / language: extraction options

    Everything LLM-related goes through llm.runner, the same path as the
    streaming endpoints (context window, thinking, budgets, JSON validation).
    """
    import time
    from llm.runner import build_source_header, compose_document, resolve_runtime, run_mode
    from sources import extract_source

    job_id = job["id"]
    config = job.get("config") or {}
    mode = config.get("mode", "summary")
    source_type = job.get("source_type")
    source_ref = job.get("source_ref")

    settings = db.get_all_settings()
    rt = await resolve_runtime(settings, config.get("model"))

    async def on_status(phase: str, detail: str) -> None:
        if db.update_job_progress(job_id, status_detail=detail) == "cancelled":
            raise JobCancelled()

    images: list[str] | None = None
    source_meta: dict = config.get("source_meta") or {}
    content = config.get("extracted_text") or ""

    if not content and source_type == "pdf" and source_ref:
        from extractors.pdf import PDFExtractor
        file_path = Path(source_ref)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {source_ref}")
        source_meta = {"title": file_path.stem}
        if rt.supports_vision:
            await on_status("extracting", "Rendering PDF for vision model...")
            try:
                images = await PDFExtractor().extract_images(file_path, on_status)
            except JobCancelled:
                raise
            except Exception as e:
                logger.warning(f"Job {job_id}: Vision rendering failed, falling back to text: {e}")
                images = None
        if images:
            content = f"[PDF with {len(images)} page(s) attached as images]"
        else:
            content = await PDFExtractor().extract(file_path, on_status)
    elif not content and source_type and source_ref:
        content, source_meta = await extract_source(
            source_type, source_ref, config=config, settings=settings, on_status=on_status,
        )

    if not content:
        raise ValueError("No text to summarize - provide extracted_text or source")

    if source_meta.get("title") and source_meta["title"] != job.get("source_title"):
        db.update_job_title(job_id, source_meta["title"])

    header = build_source_header(source_meta)
    await on_status("thinking", f"Processing with {mode} mode…")
    logger.info(f"Job {job_id}: mode={mode} model={rt.model} num_ctx={rt.num_ctx}")

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    warnings: list[str] = []
    final: dict = {}
    last_write = 0.0

    async for ev in run_mode(
        content, mode, rt, header=header, source_meta=source_meta, images=images,
        options=config.get("options"),
    ):
        kind = ev["type"]
        if kind == "text":
            text_parts.append(ev["text"])
        elif kind == "thinking":
            reasoning_parts.append(ev["text"])
        elif kind == "reset":
            text_parts.clear()
        elif kind == "warning":
            warnings.append(ev["message"])
        elif kind == "status":
            await on_status("thinking", ev["detail"])
        elif kind == "result":
            final = ev

        now = time.monotonic()
        if kind in ("text", "thinking") and now - last_write > 1.0:
            last_write = now
            detail = "Thinking…" if not text_parts else "Writing…"
            status = db.update_job_progress(job_id, status_detail=detail, partial_result="".join(text_parts))
            if status == "cancelled":
                raise JobCancelled()

    result_text = final.get("text", "".join(text_parts))
    meta = final.get("meta", {})
    reasoning = final.get("reasoning") or "".join(reasoning_parts)

    # Save to history server-side so the result is kept even if the user
    # navigated away while the job ran.
    if result_text:
        try:
            db.create_history_entry(
                mode=mode,
                source=source_type or "text",
                result=result_text,
                reasoning=reasoning,
                source_detail=source_ref or "",
            )
        except Exception as e:
            logger.warning(f"Job {job_id}: could not save history: {e}")

    return {
        "result": result_text,
        "result_meta": {
            **{k: v for k, v in meta.items() if k != "data"},
            "source_type": source_type,
            "source_meta": source_meta,
            "char_count": len(result_text),
            "reasoning": reasoning,
            "warnings": warnings,
            # Full source (with header) so chat sees title, description and chapters too.
            "extracted_text": compose_document(header, content) if not images else "",
        },
    }


async def handle_download(job: dict) -> dict | None:
    """Handle download jobs (YouTube video/audio).

    Job config expected:
    - mode: 'video' or 'audio'
    - quality: optional quality setting
    - format: optional format (mp4, mp3, etc.)
    """
    import yt_dlp
    import os

    job_id = job["id"]
    source_ref = job.get("source_ref")
    config = job.get("config") or {}
    mode = config.get("mode", "audio")

    if not source_ref:
        raise ValueError("No URL specified")

    db.update_job_status(job_id, "running", "Downloading...")
    logger.info(f"Job {job_id}: Downloading {source_ref} as {mode}")

    cache_base = Path(os.getenv("AUDIO_CACHE_DIR", Path(__file__).parent.parent / "cache" / "audio"))
    output_template = str(cache_base / f"{job_id}_%(title)s.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
    }

    if mode == "audio":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": config.get("format", "mp3"),
            }],
        })
    else:
        ydl_opts["format"] = config.get("quality", "best")

    # Progress callback
    def progress_hook(d):
        if d["status"] == "downloading":
            percent = d.get("_percent_str", "")
            db.update_job_status(job_id, "running", f"Downloading... {percent}")

    ydl_opts["progress_hooks"] = [progress_hook]

    # Run download in thread pool
    def do_download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(source_ref, download=True)
            return info

    info = await asyncio.to_thread(do_download)

    # Find the downloaded file
    title = info.get("title", "download")
    ext = config.get("format", "mp3") if mode == "audio" else info.get("ext", "mp4")
    output_file = f"{job_id}_{title}.{ext}"

    return {
        "result": f"Downloaded: {title}",
        "result_meta": {
            "title": title,
            "duration": info.get("duration"),
        },
        "output_file": output_file,
    }


def register_handlers(worker: "JobWorker") -> None:
    """Register all job handlers with the worker."""
    from .worker import JobWorker

    worker.register_handler("transcribe", handle_transcribe)
    worker.register_handler("enhance", handle_enhance)
    worker.register_handler("extract", handle_extract)
    worker.register_handler("summarize", handle_summarize)
    worker.register_handler("download", handle_download)

    logger.info("Registered all job handlers")
