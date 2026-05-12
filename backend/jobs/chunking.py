"""Audio chunking for long content.

Splits long audio files into manageable chunks for parallel processing.
"""

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

import db

logger = logging.getLogger(__name__)

CHUNK_DURATION_SECONDS = 10 * 60  # 10 minutes
OVERLAP_SECONDS = 30
CHUNK_THRESHOLD_SECONDS = 30 * 60  # 30 minutes


async def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""

    def _probe():
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip()) if result.stdout.strip() else 0

    return await asyncio.to_thread(_probe)


async def extract_audio_segment(
    audio_path: Path,
    start_seconds: float,
    end_seconds: float,
    output_dir: Path,
    chunk_num: int,
) -> Path:
    """Extract a segment of audio using ffmpeg."""
    output_path = output_dir / f"chunk_{chunk_num:03d}{audio_path.suffix}"

    def _extract():
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i", str(audio_path),
                "-ss", str(start_seconds),
                "-to", str(end_seconds),
                "-c", "copy",
                str(output_path),
            ],
            capture_output=True,
            check=True,
        )

    await asyncio.to_thread(_extract)
    return output_path


async def should_chunk(audio_path: Path) -> bool:
    """Check if audio should be chunked based on duration."""
    duration = await get_audio_duration(audio_path)
    return duration > CHUNK_THRESHOLD_SECONDS


async def create_chunk_jobs(
    parent_job_id: str,
    audio_path: Path,
    config: dict,
) -> list[str]:
    """Split audio and create child jobs for each chunk.

    Returns list of child job IDs.
    """
    duration = await get_audio_duration(audio_path)

    if duration <= CHUNK_THRESHOLD_SECONDS:
        return []

    logger.info(f"Chunking {audio_path.name} ({duration:.0f}s) into segments")

    chunk_dir = Path(tempfile.mkdtemp(prefix="chunks_"))
    chunk_ids = []
    start = 0
    chunk_num = 0

    while start < duration:
        end = min(start + CHUNK_DURATION_SECONDS, duration)

        chunk_path = await extract_audio_segment(
            audio_path, start, end, chunk_dir, chunk_num
        )

        chunk_job = db.create_job(
            job_type="transcribe",
            config={
                **config,
                "chunk_num": chunk_num,
                "start_seconds": start,
                "end_seconds": end,
            },
            source_type="file",
            source_ref=audio_path.name,
            input_file=str(chunk_path),
            parent_job_id=parent_job_id,
        )
        chunk_ids.append(chunk_job["id"])
        logger.info(f"Created chunk job {chunk_job['id']} for {start:.0f}s - {end:.0f}s")

        start = end - OVERLAP_SECONDS
        chunk_num += 1

    db.update_job_status(
        parent_job_id,
        "running",
        f"Processing {len(chunk_ids)} chunks",
    )

    return chunk_ids


def merge_chunk_results(chunks: list[dict], overlap_words: int = 30) -> str:
    """Merge transcription results from chunks with overlap removal.

    The overlap_words parameter determines how many words to skip at the
    start of each chunk (after the first) to avoid duplicate text from
    the overlap period.
    """
    chunks = sorted(chunks, key=lambda c: c["config"].get("chunk_num", 0))

    merged_parts = []
    for i, chunk in enumerate(chunks):
        result = chunk.get("result", "")
        if not result:
            continue

        if i > 0 and overlap_words > 0:
            words = result.split()
            if len(words) > overlap_words:
                result = " ".join(words[overlap_words:])

        merged_parts.append(result.strip())

    return " ".join(merged_parts)


async def wait_for_chunks(
    parent_job_id: str,
    chunk_ids: list[str],
    poll_interval: float = 1.0,
) -> list[dict]:
    """Wait for all chunk jobs to complete and return their results.

    Updates parent job status with progress.
    """
    total = len(chunk_ids)
    completed_chunks = []

    while len(completed_chunks) < total:
        chunks = db.get_child_jobs(parent_job_id)
        completed = [c for c in chunks if c["status"] in ("done", "error", "cancelled")]
        errors = [c for c in chunks if c["status"] == "error"]

        if errors:
            error_msgs = [c.get("error", "Unknown error") for c in errors]
            raise RuntimeError(f"Chunk processing failed: {'; '.join(error_msgs[:3])}")

        completed_chunks = [c for c in completed if c["status"] == "done"]

        db.update_job_status(
            parent_job_id,
            "running",
            f"Chunk {len(completed_chunks)} of {total}",
        )

        if len(completed_chunks) < total:
            await asyncio.sleep(poll_interval)

    return completed_chunks
