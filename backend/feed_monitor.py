"""
RSS/Podcast feed monitor.

Polls registered feeds on a schedule, downloads new episode audio,
and optionally queues them for transcription + summarization.

Requires: feedparser>=6.0, apscheduler>=3.10
Install with: uv sync --extra feeds
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_started = False
_scheduler = None
_scheduler_lock = threading.Lock()


def check_available() -> tuple[bool, str]:
    """Return (available, reason) — whether feed monitoring can run."""
    try:
        import feedparser  # noqa: F401
        import apscheduler  # noqa: F401
        return True, ""
    except ImportError as e:
        return False, f"Missing dependency: {e}. Run: uv sync --extra feeds"


def _get_audio_enclosures(entry) -> list[str]:
    """Extract audio URLs from an RSS entry's enclosures."""
    urls = []
    audio_types = ("audio/", "video/")
    for enc in getattr(entry, "enclosures", []) or []:
        enc_type = getattr(enc, "type", "") or ""
        if any(enc_type.startswith(t) for t in audio_types):
            if getattr(enc, "href", ""):
                urls.append(enc.href)
    # Fall back: look for 'audio' link rel
    if not urls:
        for link in getattr(entry, "links", []) or []:
            if getattr(link, "rel", "") == "enclosure" and getattr(link, "href", ""):
                urls.append(link.href)
    return urls


def check_feed(feed_id: str, trigger_jobs: bool = True) -> dict:
    """
    Poll a single feed for new entries.

    Returns {"feed_id": ..., "new_entries": int, "errors": [...]}
    """
    import feedparser
    import db

    feed = db.get_feed(feed_id)
    if not feed:
        return {"feed_id": feed_id, "new_entries": 0, "errors": ["Feed not found"]}

    result: dict = {"feed_id": feed_id, "new_entries": 0, "errors": []}

    try:
        parsed = feedparser.parse(feed["url"])
        if parsed.bozo and not parsed.entries:
            result["errors"].append(f"Feed parse error: {parsed.bozo_exception}")
            return result

        # Update title if not set yet
        feed_title = feed.get("title") or (parsed.feed.get("title") or "")
        if feed_title and feed_title != feed.get("title"):
            db.update_feed(feed_id, title=feed_title)

        last_entry_id = feed.get("last_entry_id")
        new_last_id = last_entry_id

        for entry in parsed.entries:
            entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not entry_id:
                continue

            # Stop if we've reached entries we've already processed
            if entry_id == last_entry_id:
                break

            if new_last_id is None or new_last_id == last_entry_id:
                new_last_id = entry_id

            audio_urls = _get_audio_enclosures(entry)
            if not audio_urls:
                continue

            title = entry.get("title", "Untitled")
            published = entry.get("published", datetime.now(timezone.utc).isoformat())
            audio_url = audio_urls[0]

            db_entry = db.upsert_feed_entry(
                feed_id=feed_id,
                entry_id=entry_id,
                title=title,
                audio_url=audio_url,
                published=published,
            )

            if db_entry.get("status") == "pending" and trigger_jobs and feed.get("auto_summarize"):
                _queue_entry_job(db_entry, feed)

            result["new_entries"] += 1

        db.update_feed(feed_id, last_checked=datetime.now(timezone.utc).isoformat(),
                       last_entry_id=new_last_id or last_entry_id)

    except Exception as exc:
        result["errors"].append(str(exc))
        logger.error("Error checking feed %s: %s", feed_id, exc)

    return result


def _queue_entry_job(entry: dict, feed: dict) -> None:
    """Download the episode audio and queue a transcription+summarization job."""
    import db
    import httpx
    import tempfile
    import asyncio

    entry_id = entry["id"]
    audio_url = entry.get("audio_url", "")
    if not audio_url:
        return

    def _run():
        try:
            db.update_feed_entry_status(entry_id, "downloading")

            # Download audio to temp file
            with httpx.stream("GET", audio_url, follow_redirects=True, timeout=300) as resp:
                resp.raise_for_status()
                suffix = Path(audio_url.split("?")[0]).suffix or ".mp3"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        tmp.write(chunk)
                    tmp_path = Path(tmp.name)

            # Import here to avoid circular dependency
            from main import AUDIO_CACHE, _jobs, _lock, _run_transcription
            import json

            job_id = str(uuid.uuid4())
            audio_path = AUDIO_CACHE / f"{job_id}{suffix}"
            tmp_path.rename(audio_path)

            sidecar = AUDIO_CACHE / f"{job_id}.json"
            sidecar.write_text(json.dumps({
                "job_id":      job_id,
                "filename":    entry.get("title", "podcast") + suffix,
                "audio_file":  audio_path.name,
                "size":        audio_path.stat().st_size,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "feed_id":     feed.get("id"),
                "entry_id":    entry_id,
            }))

            with _lock:
                _jobs[job_id] = {
                    "status":        "pending",
                    "status_detail": "",
                    "result":        None,
                    "segments":      [],
                    "language":      "",
                    "error":         None,
                    "filename":      entry.get("title", "podcast") + suffix,
                    "audio_path":    str(audio_path),
                }

            db.update_feed_entry_status(entry_id, "processing", job_id)
            _run_transcription(job_id, audio_path)
            db.update_feed_entry_status(entry_id, "done", job_id)

        except Exception as exc:
            logger.error("Error queuing feed entry %s: %s", entry_id, exc)
            db.update_feed_entry_status(entry_id, "error")

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def start(get_feeds_fn=None) -> None:
    """Start the background scheduler for feed polling."""
    global _started, _scheduler

    available, reason = check_available()
    if not available:
        logger.warning("Feed monitor not started: %s", reason)
        return

    with _scheduler_lock:
        if _started:
            return

        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler(daemon=True)

        # Check all feeds every 15 minutes; individual interval enforced in check_feed
        def _poll_all():
            import db
            for feed in db.list_feeds():
                last = feed.get("last_checked")
                interval = feed.get("check_interval", 3600)
                if last:
                    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(
                        last if last.endswith("Z") else last + "Z"
                    )).total_seconds()
                    if elapsed < interval:
                        continue
                try:
                    check_feed(feed["id"])
                except Exception as exc:
                    logger.error("Poll error for feed %s: %s", feed["id"], exc)

        _scheduler.add_job(_poll_all, "interval", minutes=15, id="poll_all_feeds",
                           replace_existing=True)
        _scheduler.start()
        _started = True
        logger.info("Feed monitor started.")


def stop() -> None:
    """Stop the background scheduler."""
    global _started, _scheduler
    with _scheduler_lock:
        if _scheduler and _started:
            _scheduler.shutdown(wait=False)
            _started = False
