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
    from transcriber import load_engine
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

    engine = load_engine()
    if engine is None:
        raise RuntimeError("Transcription engine not loaded")

    # Run transcription in thread pool
    result = await asyncio.to_thread(
        engine.transcribe,
        str(processed_path),
        language=config.get("language") or None,
    )

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


async def handle_extract(job: dict) -> dict | None:
    """Handle content extraction jobs (YouTube, URL, PDF, etc).

    Job config expected:
    - prefer_captions: bool (for YouTube)
    """
    from extractors import get_extractor

    job_id = job["id"]
    source_type = job.get("source_type")
    source_ref = job.get("source_ref")
    config = job.get("config") or {}

    if not source_type or not source_ref:
        raise ValueError("Missing source_type or source_ref")

    db.update_job_status(job_id, "running", f"Extracting from {source_type}...")
    logger.info(f"Job {job_id}: Extracting from {source_type}: {source_ref}")

    # Get appropriate extractor
    extractor = get_extractor(source_type)
    if extractor is None:
        raise ValueError(f"Unknown source type: {source_type}")

    # Async status callback to update job progress
    async def on_status(phase: str, detail: str) -> None:
        db.update_job_status(job_id, "running", detail)

    # Run extraction
    text = await extractor.extract(source_ref, on_status)

    return {
        "result": text,
        "result_meta": {"char_count": len(text)},
    }


async def handle_summarize(job: dict) -> dict | None:
    """Handle summarization jobs.

    Job config expected:
    - mode: summary type (summary, key_points, mind_map, etc.)
    - model: optional model override
    - extracted_text: the text to summarize (optional - will extract if source provided)

    Job fields used:
    - source_type: url, youtube, pdf, etc (triggers extraction)
    - source_ref: the URL or path to extract from
    """
    from llm import OllamaClient
    from llm.prompts import get_prompt
    from extractors import get_extractor
    from extractors.pdf import PDFExtractor

    job_id = job["id"]
    config = job.get("config") or {}
    mode = config.get("mode", "summary")
    source_type = job.get("source_type")
    source_ref = job.get("source_ref")

    # Get LLM settings early (needed for vision check)
    settings = db.get_all_settings()
    model = config.get("model") or settings.get("ollama_model")
    if not model:
        raise ValueError("No LLM model configured - check settings")

    client = OllamaClient(
        base_url=settings.get("ollama_url", "http://localhost:11434"),
        timeout=float(settings.get("ollama_timeout", "120")),
    )

    async def on_status(phase: str, detail: str) -> None:
        db.update_job_status(job_id, "running", detail)

    # Get prompt template
    prompt_data = get_prompt(mode)
    if not prompt_data:
        raise ValueError(f"Unknown summarization mode: {mode}")

    system_prompt = prompt_data.get("system", "")
    template = prompt_data.get("template", "{content}")

    # Check for vision-first PDF handling
    if source_type == "pdf" and source_ref:
        file_path = Path(source_ref)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {source_ref}")

        extractor = PDFExtractor()

        # Try vision first if model supports it
        vision_override = settings.get("ollama_vision_override", "false") == "true" or None
        if await client.supports_vision(model, override=vision_override):
            db.update_job_status(job_id, "running", "Rendering PDF for vision model...")
            logger.info(f"Job {job_id}: Using vision mode for PDF")
            try:
                images = await extractor.extract_images(file_path, on_status)
                if images:
                    db.update_job_status(job_id, "running", "Analyzing PDF with vision model...")
                    user_prompt = template.replace(
                        "{content}",
                        f"[PDF with {len(images)} page(s) attached as images]"
                    )
                    response_text = ""
                    async for chunk in client.generate_stream(
                        user_prompt, model, system_prompt, images=images
                    ):
                        response_text += chunk

                    return {
                        "result": response_text,
                        "result_meta": {
                            "mode": mode,
                            "source_type": source_type,
                            "vision_mode": True,
                            "pages_processed": len(images),
                            "char_count": len(response_text),
                        },
                    }
            except Exception as e:
                logger.warning(f"Job {job_id}: Vision extraction failed, falling back to text: {e}")

        # Fall back to text extraction
        db.update_job_status(job_id, "running", "Extracting text from PDF...")
        logger.info(f"Job {job_id}: Using text extraction for PDF")
        extracted_text = await extractor.extract(file_path, on_status)

    # Get text - either from config or by extracting from source
    elif not config.get("extracted_text") and source_type and source_ref:
        db.update_job_status(job_id, "running", f"Extracting from {source_type}...")
        logger.info(f"Job {job_id}: Extracting from {source_type}: {source_ref}")

        # Construct extractor based on source type
        if source_type == "youtube":
            from extractors.youtube import YouTubeExtractor
            from transcriber import load_engine
            engine = load_engine()
            if engine is None:
                raise RuntimeError("Transcription engine not loaded")
            prefer_captions = config.get("prefer_captions", True)
            extractor = YouTubeExtractor(engine=engine, prefer_captions=prefer_captions)
        else:
            extractor = get_extractor(source_type)
            if extractor is None:
                raise ValueError(f"Unknown source type: {source_type}")

        extracted_text = await extractor.extract(source_ref, on_status)
    else:
        extracted_text = config.get("extracted_text")

    if not extracted_text:
        raise ValueError("No text to summarize - provide extracted_text or source")

    db.update_job_status(job_id, "running", "Generating summary...")
    logger.info(f"Job {job_id}: Summarizing with mode={mode}")

    # Build prompt with content
    user_prompt = template.replace("{content}", extracted_text)

    response_text = ""
    async for chunk in client.generate_stream(user_prompt, model, system_prompt):
        response_text += chunk

    return {
        "result": response_text,
        "result_meta": {
            "mode": mode,
            "source_type": source_type,
            "char_count": len(response_text),
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
