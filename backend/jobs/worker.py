"""Background job worker with persistent queue.

The worker processes jobs from a DB-backed queue with configurable concurrency.
Jobs survive server restarts - on startup, pending/running jobs are recovered.
"""

import asyncio
import logging
import threading
import traceback
from queue import Queue, Empty
from typing import Callable, Awaitable

import db

logger = logging.getLogger(__name__)

# Type alias for job handlers
JobHandler = Callable[[dict], Awaitable[dict | None]]

# Global worker instance
_worker: "JobWorker | None" = None


class JobWorker:
    """Background worker that processes jobs from a DB-backed queue.

    Features:
    - Configurable concurrency limit
    - Job recovery on startup (pending/running jobs)
    - Graceful shutdown
    - Status updates persisted to DB
    """

    def __init__(self, max_concurrent: int = 2):
        self._max_concurrent = max_concurrent
        self._queue: Queue[str] = Queue()
        self._active: dict[str, asyncio.Task] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._handlers: dict[str, JobHandler] = {}

    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        """Register a handler for a job type."""
        self._handlers[job_type] = handler
        logger.info(f"Registered handler for job type: {job_type}")

    def start(self) -> None:
        """Start the worker thread and recover pending jobs."""
        if self._running:
            logger.warning("Worker already running")
            return

        self._running = True

        # Recover jobs that were running when server stopped
        self._recover_jobs()

        # Start worker thread
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="job-worker")
        self._thread.start()
        logger.info(f"Job worker started (max_concurrent={self._max_concurrent})")

    def stop(self) -> None:
        """Stop the worker gracefully."""
        if not self._running:
            return

        logger.info("Stopping job worker...")
        self._running = False

        # Cancel active tasks
        if self._loop:
            for job_id, task in list(self._active.items()):
                task.cancel()
                logger.info(f"Cancelled active job: {job_id}")

        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

        logger.info("Job worker stopped")

    def enqueue(self, job_id: str) -> None:
        """Add a job to the processing queue."""
        self._queue.put(job_id)
        logger.debug(f"Enqueued job: {job_id}")

    def get_queue_position(self, job_id: str) -> int | None:
        """Get position in queue (0 = running, >0 = waiting)."""
        if job_id in self._active:
            return 0
        # Can't easily get position in Queue, return approximate
        return self._queue.qsize() if self._queue.qsize() > 0 else None

    @property
    def active_count(self) -> int:
        """Number of currently running jobs."""
        return len(self._active)

    @property
    def queued_count(self) -> int:
        """Number of jobs waiting in queue."""
        return self._queue.qsize()

    def _recover_jobs(self) -> None:
        """Recover pending/running jobs from DB after restart."""
        try:
            # Get all jobs that should be recovered
            jobs = db.get_jobs_by_status(["pending", "running", "queued"])

            for job in jobs:
                if job["status"] == "running":
                    # Mark as pending for re-processing
                    db.update_job_status(
                        job["id"],
                        "pending",
                        "Recovering after restart"
                    )
                    logger.info(f"Recovered running job: {job['id']}")

                # Re-enqueue all
                self._queue.put(job["id"])

            if jobs:
                logger.info(f"Recovered {len(jobs)} jobs from previous session")
        except Exception as e:
            logger.error(f"Failed to recover jobs: {e}")

    def _run_loop(self) -> None:
        """Main worker loop running in dedicated thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._async_loop())
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
        finally:
            self._loop.close()
            self._loop = None

    async def _async_loop(self) -> None:
        """Async processing loop."""
        while self._running:
            # Clean up completed tasks
            completed = [jid for jid, task in self._active.items() if task.done()]
            for jid in completed:
                task = self._active.pop(jid)
                try:
                    task.result()  # Raise any exception
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Job {jid} failed: {e}")

            # Start new jobs if under concurrency limit
            while len(self._active) < self._max_concurrent:
                try:
                    job_id = self._queue.get_nowait()
                    task = asyncio.create_task(self._process_job(job_id))
                    self._active[job_id] = task
                    logger.debug(f"Started job: {job_id}")
                except Empty:
                    break

            await asyncio.sleep(0.1)

    async def _process_job(self, job_id: str) -> None:
        """Process a single job."""
        job = db.get_job(job_id)
        if not job:
            logger.warning(f"Job not found: {job_id}")
            return

        # Check if already completed/cancelled
        if job["status"] in ("done", "error", "cancelled"):
            logger.info(f"Skipping already finished job: {job_id} ({job['status']})")
            return

        job_type = job["type"]
        handler = self._handlers.get(job_type)

        if not handler:
            logger.error(f"No handler for job type: {job_type}")
            db.fail_job(job_id, f"No handler registered for job type: {job_type}")
            return

        # Mark as running
        db.update_job_status(job_id, "running", "Starting...", started_at=True)
        logger.info(f"Processing job: {job_id} (type={job_type})")

        try:
            # Call the handler
            result = await handler(job)

            # Handler should return result dict or None
            if result is not None:
                db.complete_job(
                    job_id,
                    result=result.get("result"),
                    result_meta=result.get("result_meta"),
                    output_file=result.get("output_file"),
                )
            # If handler returns None, it handled completion itself

            logger.info(f"Completed job: {job_id}")

        except asyncio.CancelledError:
            db.update_job_status(job_id, "cancelled", "Cancelled by worker shutdown")
            logger.info(f"Job cancelled: {job_id}")
            raise

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Job {job_id} failed: {error_msg}\n{traceback.format_exc()}")
            db.fail_job(job_id, error_msg)


def get_worker() -> JobWorker | None:
    """Get the global worker instance."""
    return _worker


def init_worker(max_concurrent: int | None = None) -> JobWorker:
    """Initialize and return the global worker instance."""
    global _worker

    if _worker is not None:
        return _worker

    # Get concurrency from settings if not specified
    if max_concurrent is None:
        try:
            max_concurrent = int(db.get_setting("max_concurrent_jobs", "2"))
        except (ValueError, TypeError):
            max_concurrent = 2

    _worker = JobWorker(max_concurrent=max_concurrent)
    return _worker


def shutdown_worker() -> None:
    """Shutdown the global worker instance."""
    global _worker
    if _worker:
        _worker.stop()
        _worker = None
