"""Tests for job and extraction cache CRUD operations."""

import os
import tempfile
import pytest

# Point to a temp DB before importing db module
_temp_dir = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _temp_dir

import db


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh DB for each test."""
    db.DB_PATH = db._DATA_DIR / "test_app.db"
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    db.init_db()
    yield
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()


class TestJobCRUD:
    """Test job create, read, update, delete operations."""

    def test_create_job_minimal(self):
        """Create a job with minimal required fields."""
        job = db.create_job(job_type="transcribe")
        assert job["id"] is not None
        assert job["type"] == "transcribe"
        assert job["status"] == "pending"
        assert job["config"] == {}
        assert job["created_at"] is not None

    def test_create_job_with_all_fields(self):
        """Create a job with all optional fields."""
        job = db.create_job(
            job_type="summarize",
            config={"mode": "key_points", "model": "llama3"},
            source_type="youtube",
            source_ref="https://youtube.com/watch?v=abc123",
            source_title="Test Video Title",
            thumbnail="base64data...",
            content_hash="sha256:abc123",
            input_file="abc123.mp3",
            parent_job_id=None,
            batch_id="batch-001",
        )
        assert job["type"] == "summarize"
        assert job["config"]["mode"] == "key_points"
        assert job["source_type"] == "youtube"
        assert job["source_ref"] == "https://youtube.com/watch?v=abc123"
        assert job["source_title"] == "Test Video Title"
        assert job["thumbnail"] == "base64data..."
        assert job["content_hash"] == "sha256:abc123"
        assert job["batch_id"] == "batch-001"

    def test_get_job(self):
        """Retrieve a job by ID."""
        created = db.create_job(job_type="transcribe")
        fetched = db.get_job(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_get_job_not_found(self):
        """Return None for non-existent job."""
        result = db.get_job("nonexistent-id")
        assert result is None

    def test_list_jobs_default(self):
        """List jobs returns recent jobs without children."""
        db.create_job(job_type="transcribe")
        db.create_job(job_type="summarize")
        jobs = db.list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_filter_by_status(self):
        """Filter jobs by status."""
        job1 = db.create_job(job_type="transcribe")
        job2 = db.create_job(job_type="transcribe")
        db.update_job_status(job1["id"], "running")

        pending = db.list_jobs(status="pending")
        assert len(pending) == 1
        assert pending[0]["id"] == job2["id"]

        running = db.list_jobs(status="running")
        assert len(running) == 1
        assert running[0]["id"] == job1["id"]

    def test_list_jobs_filter_by_type(self):
        """Filter jobs by type."""
        db.create_job(job_type="transcribe")
        db.create_job(job_type="summarize")

        transcribe_jobs = db.list_jobs(job_type="transcribe")
        assert len(transcribe_jobs) == 1
        assert transcribe_jobs[0]["type"] == "transcribe"

    def test_list_jobs_filter_by_batch(self):
        """Filter jobs by batch ID."""
        db.create_job(job_type="transcribe", batch_id="batch-1")
        db.create_job(job_type="transcribe", batch_id="batch-1")
        db.create_job(job_type="transcribe", batch_id="batch-2")

        batch1_jobs = db.list_jobs(batch_id="batch-1")
        assert len(batch1_jobs) == 2

    def test_list_jobs_excludes_children(self):
        """Children are excluded by default."""
        parent = db.create_job(job_type="transcribe")
        db.create_job(job_type="transcribe", parent_job_id=parent["id"])

        jobs = db.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == parent["id"]

    def test_list_jobs_include_children(self):
        """Include children when requested."""
        parent = db.create_job(job_type="transcribe")
        db.create_job(job_type="transcribe", parent_job_id=parent["id"])

        jobs = db.list_jobs(include_children=True)
        assert len(jobs) == 2

    def test_delete_job_completed(self):
        """Delete a completed job."""
        job = db.create_job(job_type="transcribe")
        db.complete_job(job["id"], result="transcript text")
        assert db.delete_job(job["id"]) is True
        assert db.get_job(job["id"]) is None

    def test_delete_job_pending_fails(self):
        """Cannot delete a pending job."""
        job = db.create_job(job_type="transcribe")
        assert db.delete_job(job["id"]) is False
        assert db.get_job(job["id"]) is not None


class TestJobStateTransitions:
    """Test job status transitions."""

    def test_pending_to_running(self):
        """Transition from pending to running."""
        job = db.create_job(job_type="transcribe")
        updated = db.update_job_status(job["id"], "running", "Processing...", started_at=True)
        assert updated["status"] == "running"
        assert updated["status_detail"] == "Processing..."
        assert updated["started_at"] is not None

    def test_running_to_done(self):
        """Transition from running to done via complete_job."""
        job = db.create_job(job_type="transcribe")
        db.update_job_status(job["id"], "running")
        completed = db.complete_job(
            job["id"],
            result="Transcript text here",
            result_meta={"language": "en", "segments": []},
        )
        assert completed["status"] == "done"
        assert completed["result"] == "Transcript text here"
        assert completed["result_meta"]["language"] == "en"
        assert completed["completed_at"] is not None

    def test_running_to_error(self):
        """Transition from running to error via fail_job."""
        job = db.create_job(job_type="transcribe")
        db.update_job_status(job["id"], "running")
        failed = db.fail_job(job["id"], "Model failed to load")
        assert failed["status"] == "error"
        assert failed["error"] == "Model failed to load"
        assert failed["completed_at"] is not None

    def test_cancel_pending_job(self):
        """Cancel a pending job."""
        job = db.create_job(job_type="transcribe")
        cancelled = db.cancel_job(job["id"])
        assert cancelled["status"] == "cancelled"
        assert cancelled["completed_at"] is not None

    def test_cancel_running_job(self):
        """Cancel a running job."""
        job = db.create_job(job_type="transcribe")
        db.update_job_status(job["id"], "running")
        cancelled = db.cancel_job(job["id"])
        assert cancelled["status"] == "cancelled"

    def test_cancel_done_job_noop(self):
        """Cancelling a done job has no effect."""
        job = db.create_job(job_type="transcribe")
        db.complete_job(job["id"], result="done")
        result = db.cancel_job(job["id"])
        assert result["status"] == "done"

    def test_invalid_status_raises(self):
        """Invalid status raises ValueError."""
        job = db.create_job(job_type="transcribe")
        with pytest.raises(ValueError, match="Invalid status"):
            db.update_job_status(job["id"], "invalid_status")


class TestBatchJobs:
    """Test batch job operations."""

    def test_create_batch_jobs(self):
        """Create multiple jobs with same batch ID."""
        batch_id = "batch-test-001"
        job1 = db.create_job(job_type="summarize", batch_id=batch_id, source_ref="url1")
        job2 = db.create_job(job_type="summarize", batch_id=batch_id, source_ref="url2")
        job3 = db.create_job(job_type="summarize", batch_id=batch_id, source_ref="url3")

        batch_jobs = db.list_jobs(batch_id=batch_id)
        assert len(batch_jobs) == 3

    def test_cancel_batch(self):
        """Cancel all jobs in a batch."""
        batch_id = "batch-cancel-test"
        db.create_job(job_type="transcribe", batch_id=batch_id)
        job2 = db.create_job(job_type="transcribe", batch_id=batch_id)
        db.update_job_status(job2["id"], "running")
        db.create_job(job_type="transcribe", batch_id=batch_id)

        cancelled_count = db.cancel_batch(batch_id)
        assert cancelled_count == 3

        batch_jobs = db.list_jobs(batch_id=batch_id)
        for job in batch_jobs:
            assert job["status"] == "cancelled"


class TestChildJobs:
    """Test parent/child job relationships (chunking)."""

    def test_create_child_jobs(self):
        """Create child jobs linked to parent."""
        parent = db.create_job(job_type="transcribe")
        child1 = db.create_job(job_type="transcribe", parent_job_id=parent["id"])
        child2 = db.create_job(job_type="transcribe", parent_job_id=parent["id"])

        children = db.get_child_jobs(parent["id"])
        assert len(children) == 2
        assert children[0]["parent_job_id"] == parent["id"]
        assert children[1]["parent_job_id"] == parent["id"]

    def test_child_jobs_ordered_by_creation(self):
        """Child jobs are returned in creation order."""
        parent = db.create_job(job_type="transcribe")
        child1 = db.create_job(
            job_type="transcribe",
            parent_job_id=parent["id"],
            config={"chunk_num": 0},
        )
        child2 = db.create_job(
            job_type="transcribe",
            parent_job_id=parent["id"],
            config={"chunk_num": 1},
        )

        children = db.get_child_jobs(parent["id"])
        assert children[0]["config"]["chunk_num"] == 0
        assert children[1]["config"]["chunk_num"] == 1


class TestJobCounts:
    """Test job count functions."""

    def test_get_job_counts(self):
        """Get counts by status."""
        db.create_job(job_type="transcribe")
        job2 = db.create_job(job_type="transcribe")
        db.update_job_status(job2["id"], "running")
        job3 = db.create_job(job_type="transcribe")
        db.complete_job(job3["id"], result="done")

        counts = db.get_job_counts()
        assert counts.get("pending", 0) == 1
        assert counts.get("running", 0) == 1
        assert counts.get("done", 0) == 1

    def test_get_active_job_count(self):
        """Get running + queued counts for header indicator."""
        db.create_job(job_type="transcribe")
        job2 = db.create_job(job_type="transcribe")
        db.update_job_status(job2["id"], "running")
        job3 = db.create_job(job_type="transcribe")
        db.update_job_status(job3["id"], "queued")

        active = db.get_active_job_count()
        assert active["running"] == 1
        assert active["queued"] == 2  # 1 pending + 1 queued


class TestJobRecovery:
    """Test job recovery scenarios."""

    def test_get_jobs_by_status_for_recovery(self):
        """Get pending/running jobs for worker recovery."""
        db.create_job(job_type="transcribe")
        job2 = db.create_job(job_type="transcribe")
        db.update_job_status(job2["id"], "running")
        job3 = db.create_job(job_type="transcribe")
        db.complete_job(job3["id"], result="done")

        recoverable = db.get_jobs_by_status(["pending", "running"])
        assert len(recoverable) == 2
        statuses = {j["status"] for j in recoverable}
        assert statuses == {"pending", "running"}


class TestJobCleanup:
    """Test job cleanup operations."""

    def test_cleanup_old_jobs(self):
        """Cleanup removes old completed jobs."""
        job = db.create_job(job_type="transcribe")
        db.complete_job(job["id"], result="done")

        # Manually backdate the completed_at for testing
        conn = db._connect()
        conn.execute(
            "UPDATE jobs SET completed_at = datetime('now', '-100 hours') WHERE id = ?",
            (job["id"],),
        )
        conn.commit()
        conn.close()

        deleted = db.cleanup_old_jobs(hours=72)
        assert deleted == 1
        assert db.get_job(job["id"]) is None


class TestExtractionCache:
    """Test extraction cache operations."""

    def test_set_and_get_cache(self):
        """Store and retrieve cached extraction."""
        cache = db.set_extraction_cache(
            content_hash="sha256:test123",
            source_type="youtube",
            source_ref="https://youtube.com/watch?v=test",
            extracted_text="This is the transcript text",
            title="Test Video",
            thumbnail="base64thumbnail...",
            metadata={"duration": 300},
        )
        assert cache["content_hash"] == "sha256:test123"
        assert cache["extracted_text"] == "This is the transcript text"

        retrieved = db.get_extraction_cache("sha256:test123")
        assert retrieved is not None
        assert retrieved["title"] == "Test Video"
        assert retrieved["metadata"]["duration"] == 300

    def test_cache_miss(self):
        """Return None for cache miss."""
        result = db.get_extraction_cache("nonexistent-hash")
        assert result is None

    def test_cache_updates_accessed_at(self):
        """Accessing cache updates accessed_at timestamp."""
        db.set_extraction_cache(
            content_hash="sha256:access-test",
            source_type="url",
            source_ref="https://example.com",
            extracted_text="Text content",
        )

        # First access
        first = db.get_extraction_cache("sha256:access-test")
        first_accessed = first["accessed_at"]

        # Backdate accessed_at
        conn = db._connect()
        conn.execute(
            "UPDATE extraction_cache SET accessed_at = datetime('now', '-1 hour') WHERE content_hash = ?",
            ("sha256:access-test",),
        )
        conn.commit()
        conn.close()

        # Second access should update
        second = db.get_extraction_cache("sha256:access-test")
        assert second["accessed_at"] != first_accessed

    def test_cache_upsert(self):
        """Setting same hash updates existing entry."""
        db.set_extraction_cache(
            content_hash="sha256:upsert-test",
            source_type="youtube",
            source_ref="url1",
            extracted_text="First text",
        )

        db.set_extraction_cache(
            content_hash="sha256:upsert-test",
            source_type="youtube",
            source_ref="url1",
            extracted_text="Updated text",
        )

        cache = db.get_extraction_cache("sha256:upsert-test")
        assert cache["extracted_text"] == "Updated text"

    def test_delete_cache(self):
        """Delete cache entry (force refresh)."""
        db.set_extraction_cache(
            content_hash="sha256:delete-test",
            source_type="url",
            source_ref="https://example.com",
            extracted_text="Text",
        )

        assert db.delete_extraction_cache("sha256:delete-test") is True
        assert db.get_extraction_cache("sha256:delete-test") is None

    def test_delete_nonexistent_cache(self):
        """Deleting non-existent cache returns False."""
        assert db.delete_extraction_cache("sha256:nonexistent") is False

    def test_cleanup_old_cache(self):
        """Cleanup removes stale cache entries."""
        db.set_extraction_cache(
            content_hash="sha256:old-cache",
            source_type="url",
            source_ref="https://example.com",
            extracted_text="Old text",
        )

        # Backdate accessed_at
        conn = db._connect()
        conn.execute(
            "UPDATE extraction_cache SET accessed_at = datetime('now', '-200 hours') WHERE content_hash = ?",
            ("sha256:old-cache",),
        )
        conn.commit()
        conn.close()

        deleted = db.cleanup_old_cache(hours=168)
        assert deleted == 1
        assert db.get_extraction_cache("sha256:old-cache") is None

    def test_cache_stats(self):
        """Get cache statistics."""
        db.set_extraction_cache(
            content_hash="sha256:stats-test-1",
            source_type="youtube",
            source_ref="url1",
            extracted_text="Text 1",
            thumbnail="thumb1",
        )
        db.set_extraction_cache(
            content_hash="sha256:stats-test-2",
            source_type="url",
            source_ref="url2",
            extracted_text="Text 2",
        )

        stats = db.get_cache_stats()
        assert stats["total_entries"] == 2
        assert stats["total_text_bytes"] > 0
