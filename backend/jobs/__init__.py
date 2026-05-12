"""Job queue infrastructure for persistent async processing."""

from .worker import JobWorker, get_worker, init_worker, shutdown_worker
from .handlers import register_handlers
from .cache import (
    compute_content_hash,
    extract_youtube_video_id,
    normalize_url,
    process_thumbnail,
    fetch_youtube_thumbnail,
    fetch_og_image,
    fetch_page_title,
)
from .chunking import (
    get_audio_duration,
    should_chunk,
    create_chunk_jobs,
    merge_chunk_results,
    wait_for_chunks,
    CHUNK_DURATION_SECONDS,
    CHUNK_THRESHOLD_SECONDS,
    OVERLAP_SECONDS,
)

__all__ = [
    "JobWorker",
    "get_worker",
    "init_worker",
    "shutdown_worker",
    "register_handlers",
    "compute_content_hash",
    "extract_youtube_video_id",
    "normalize_url",
    "process_thumbnail",
    "fetch_youtube_thumbnail",
    "fetch_og_image",
    "fetch_page_title",
    "get_audio_duration",
    "should_chunk",
    "create_chunk_jobs",
    "merge_chunk_results",
    "wait_for_chunks",
    "CHUNK_DURATION_SECONDS",
    "CHUNK_THRESHOLD_SECONDS",
    "OVERLAP_SECONDS",
]
