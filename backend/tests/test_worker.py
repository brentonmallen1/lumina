"""Tests for the job worker."""

import asyncio
import os
import tempfile
import time
import pytest

# Point to a temp DB before importing db module
_temp_dir = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _temp_dir

import db
from jobs.worker import JobWorker


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh DB for each test."""
    db.DB_PATH = db._DATA_DIR / "test_worker.db"
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    db.init_db()
    yield
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()


@pytest.fixture
def worker():
    """Create a worker instance for testing."""
    w = JobWorker(max_concurrent=2)
    yield w
    w.stop()


class TestWorkerBasics:
    """Test basic worker operations."""

    def test_worker_init(self, worker):
        """Worker initializes with correct settings."""
        assert worker._max_concurrent == 2
        assert worker._running is False
        assert worker.active_count == 0
        assert worker.queued_count == 0

    def test_worker_start_stop(self, worker):
        """Worker starts and stops cleanly."""
        worker.start()
        assert worker._running is True
        assert worker._thread is not None
        assert worker._thread.is_alive()

        worker.stop()
        assert worker._running is False

    def test_worker_double_start(self, worker):
        """Starting twice is a no-op."""
        worker.start()
        thread1 = worker._thread

        worker.start()
        thread2 = worker._thread

        assert thread1 is thread2


class TestJobProcessing:
    """Test job processing functionality."""

    def test_simple_job_processing(self, worker):
        """Process a simple job."""
        results = []

        async def simple_handler(job):
            results.append(job["id"])
            await asyncio.sleep(0.1)
            return {"result": "done"}

        worker.register_handler("test", simple_handler)
        worker.start()

        job = db.create_job(job_type="test")
        worker.enqueue(job["id"])

        # Wait for processing
        time.sleep(0.5)

        assert job["id"] in results
        updated = db.get_job(job["id"])
        assert updated["status"] == "done"
        assert updated["result"] == "done"

    def test_job_failure(self, worker):
        """Failed jobs are marked as error."""
        async def failing_handler(job):
            raise ValueError("Test error")

        worker.register_handler("test", failing_handler)
        worker.start()

        job = db.create_job(job_type="test")
        worker.enqueue(job["id"])

        time.sleep(0.5)

        updated = db.get_job(job["id"])
        assert updated["status"] == "error"
        assert "Test error" in updated["error"]

    def test_no_handler_registered(self, worker):
        """Jobs without handlers are marked as error."""
        worker.start()

        job = db.create_job(job_type="unknown_type")
        worker.enqueue(job["id"])

        time.sleep(0.5)

        updated = db.get_job(job["id"])
        assert updated["status"] == "error"
        assert "No handler" in updated["error"]


class TestConcurrency:
    """Test concurrency limits."""

    def test_concurrency_limit(self, worker):
        """Respects max_concurrent limit."""
        active_at_same_time = []
        current_active = {"count": 0}
        lock = asyncio.Lock()

        async def slow_handler(job):
            async with lock:
                current_active["count"] += 1
                active_at_same_time.append(current_active["count"])

            await asyncio.sleep(0.2)

            async with lock:
                current_active["count"] -= 1

            return {"result": "done"}

        worker.register_handler("test", slow_handler)
        worker.start()

        # Create 4 jobs
        jobs = [db.create_job(job_type="test") for _ in range(4)]
        for job in jobs:
            worker.enqueue(job["id"])

        # Wait for all to complete
        time.sleep(1.5)

        # Should never have more than 2 active at once
        assert max(active_at_same_time) <= 2

        # All jobs should be done
        for job in jobs:
            updated = db.get_job(job["id"])
            assert updated["status"] == "done"


class TestQueueOrder:
    """Test FIFO queue ordering."""

    def test_fifo_order(self, worker):
        """Jobs are processed in submission order."""
        processed_order = []

        async def tracking_handler(job):
            processed_order.append(job["id"])
            await asyncio.sleep(0.05)
            return {"result": "done"}

        # Use concurrency of 1 to ensure strict ordering
        worker._max_concurrent = 1
        worker.register_handler("test", tracking_handler)
        worker.start()

        # Create jobs in order
        job_ids = []
        for i in range(5):
            job = db.create_job(job_type="test", config={"order": i})
            job_ids.append(job["id"])
            worker.enqueue(job["id"])

        # Wait for all to complete
        time.sleep(1.0)

        # Should be processed in order
        assert processed_order == job_ids


class TestJobRecovery:
    """Test job recovery after restart."""

    def test_recovery_pending_jobs(self, worker):
        """Pending jobs are recovered on startup."""
        # Create pending jobs before starting worker
        job1 = db.create_job(job_type="test")
        job2 = db.create_job(job_type="test")

        recovered = []

        async def tracking_handler(job):
            recovered.append(job["id"])
            return {"result": "recovered"}

        worker.register_handler("test", tracking_handler)
        worker.start()

        time.sleep(0.5)

        assert job1["id"] in recovered
        assert job2["id"] in recovered

    def test_recovery_running_jobs(self, worker):
        """Running jobs are reset to pending and recovered."""
        # Create a job and mark it as running (simulating crash)
        job = db.create_job(job_type="test")
        db.update_job_status(job["id"], "running", "Was running")

        recovered = []

        async def tracking_handler(job):
            recovered.append(job["id"])
            return {"result": "recovered"}

        worker.register_handler("test", tracking_handler)
        worker.start()

        time.sleep(0.5)

        assert job["id"] in recovered

        updated = db.get_job(job["id"])
        assert updated["status"] == "done"

    def test_skip_completed_jobs(self, worker):
        """Completed jobs are not re-processed."""
        job = db.create_job(job_type="test")
        db.complete_job(job["id"], result="already done")

        processed = []

        async def tracking_handler(job):
            processed.append(job["id"])
            return {"result": "reprocessed"}

        worker.register_handler("test", tracking_handler)
        worker.start()

        # Manually enqueue completed job (shouldn't happen normally)
        worker.enqueue(job["id"])

        time.sleep(0.5)

        # Should not be reprocessed
        assert job["id"] not in processed

        # Should still have original result
        updated = db.get_job(job["id"])
        assert updated["result"] == "already done"


class TestStatusUpdates:
    """Test job status updates during processing."""

    def test_status_updates(self, worker):
        """Status is updated during processing."""
        statuses_seen = []

        async def updating_handler(job):
            # Record initial status
            current = db.get_job(job["id"])
            statuses_seen.append(current["status"])

            db.update_job_status(job["id"], "running", "Step 1")
            await asyncio.sleep(0.05)

            db.update_job_status(job["id"], "running", "Step 2")
            await asyncio.sleep(0.05)

            return {"result": "done"}

        worker.register_handler("test", updating_handler)
        worker.start()

        job = db.create_job(job_type="test")
        worker.enqueue(job["id"])

        time.sleep(0.5)

        # Should have seen running status
        assert "running" in statuses_seen


class TestCancellation:
    """Test job cancellation."""

    def test_cancel_pending_job(self, worker):
        """Cancelled jobs are skipped."""
        job = db.create_job(job_type="test")
        db.cancel_job(job["id"])

        processed = []

        async def tracking_handler(job):
            processed.append(job["id"])
            return {"result": "done"}

        worker.register_handler("test", tracking_handler)
        worker.start()
        worker.enqueue(job["id"])

        time.sleep(0.5)

        # Should not be processed
        assert job["id"] not in processed

        # Should still be cancelled
        updated = db.get_job(job["id"])
        assert updated["status"] == "cancelled"
