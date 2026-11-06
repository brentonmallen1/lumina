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
from datetime import datetime, timezone

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


def _is_http_url(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        return urlparse(url).scheme in ("http", "https")
    except ValueError:
        return False


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse stored timestamps ("…Z", "…+00:00", or naive SQLite UTC) as aware UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def check_feed(feed_id: str, trigger_jobs: bool = True) -> dict:
    """
    Poll a single feed for new entries.

    New episodes are queued as ``feed_episode`` jobs on the worker (bounded by
    max_concurrent_jobs). On a feed's first check only the newest episode is
    queued, so adding a podcast doesn't download its whole back catalogue.

    Returns {"feed_id": ..., "new_entries": int, "errors": [...]}
    """
    import feedparser
    import db

    feed = db.get_feed(feed_id)
    if not feed:
        return {"feed_id": feed_id, "new_entries": 0, "errors": ["Feed not found"]}

    result: dict = {"feed_id": feed_id, "new_entries": 0, "errors": []}
    if not _is_http_url(feed["url"]):
        result["errors"].append("Feed URL must be http(s)")
        return result

    try:
        parsed = feedparser.parse(feed["url"])
        if parsed.bozo and not parsed.entries:
            result["errors"].append(f"Feed parse error: {parsed.bozo_exception}")
            return result

        feed_title = feed.get("title") or (parsed.feed.get("title") or "")
        if feed_title and feed_title != feed.get("title"):
            db.update_feed(feed_id, title=feed_title)

        last_entry_id = feed.get("last_entry_id")
        first_check = last_entry_id is None
        newest_id = None

        for entry in parsed.entries:
            entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not entry_id:
                continue
            if entry_id == last_entry_id:
                break  # reached episodes we've already seen
            if newest_id is None:
                newest_id = entry_id

            audio_urls = [u for u in _get_audio_enclosures(entry) if _is_http_url(u)]
            if not audio_urls:
                continue

            db_entry = db.upsert_feed_entry(
                feed_id=feed_id,
                entry_id=entry_id,
                title=entry.get("title", "Untitled"),
                audio_url=audio_urls[0],
                published=entry.get("published", datetime.now(timezone.utc).isoformat()),
            )
            result["new_entries"] += 1

            if db_entry.get("status") == "pending" and trigger_jobs and feed.get("auto_summarize"):
                _queue_entry_job(db_entry, feed)

            if first_check:
                break  # only the latest episode on a brand-new feed

        db.update_feed(feed_id, last_checked=datetime.now(timezone.utc).isoformat(),
                       last_entry_id=newest_id or last_entry_id)

    except Exception as exc:
        result["errors"].append(str(exc))
        logger.error("Error checking feed %s: %s", feed_id, exc)

    return result


def _queue_entry_job(entry: dict, feed: dict) -> None:
    """Queue a feed_episode job (download → transcribe → summarize) on the worker."""
    import db
    from jobs import get_worker

    job = db.create_job(
        job_type="feed_episode",
        config={
            "feed_entry_id": entry["id"],
            "audio_url": entry.get("audio_url", ""),
            "mode": feed.get("summarize_mode") or "summary",
        },
        source_type="feed",
        source_ref=entry.get("audio_url", ""),
        source_title=entry.get("title") or "Podcast episode",
    )
    db.update_feed_entry_status(entry["id"], "processing", job["id"])
    worker = get_worker()
    if worker:
        worker.enqueue(job["id"])
    else:
        db.fail_job(job["id"], "Job worker not available")
        db.update_feed_entry_status(entry["id"], "error", job["id"])


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

        import os
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler(daemon=True, timezone=os.environ.get("TZ", "UTC"))

        # Check all feeds every 15 minutes; individual interval enforced in check_feed
        def _poll_all():
            import db
            for feed in db.list_feeds():
                try:
                    last = parse_timestamp(feed.get("last_checked"))
                    interval = feed.get("check_interval") or 3600
                    if last and (datetime.now(timezone.utc) - last).total_seconds() < interval:
                        continue
                    check_feed(feed["id"])
                except Exception as exc:  # one bad feed must not stop the others
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
