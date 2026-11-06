"""HTTP-level tests for auth, settings, jobs and exports (no engine / Ollama needed)."""

import base64

import pytest
from fastapi.testclient import TestClient

import db
import main


@pytest.fixture(autouse=True)
def fresh_db():
    db.DB_PATH = db._DATA_DIR / "test_api.db"
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    db.init_db()
    main._reload_settings()
    yield
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()


@pytest.fixture
def client():
    # No context manager → lifespan (engine load, worker, feed monitor) doesn't run.
    return TestClient(main.app)


def _set(**settings):
    db.update_settings({k: str(v) for k, v in settings.items()})
    main._reload_settings()


def _basic(user, pwd):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()}


# ── Auth ─────────────────────────────────────────────────────────────────────

def test_api_key_works_with_basic_auth_enabled(client):
    _set(auth_enabled="true", auth_username="admin", auth_password="pw", api_key="secret-key")
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/jobs", headers={"X-API-Key": "secret-key"}).status_code == 200
    assert client.get("/api/jobs", headers={"Authorization": "Bearer secret-key"}).status_code == 200
    assert client.get("/api/jobs", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/jobs", headers=_basic("admin", "pw")).status_code == 200


# ── Settings ─────────────────────────────────────────────────────────────────

def test_settings_mask_secrets_and_keep_them_on_save(client):
    _set(api_key="abc123", hf_token="")
    data = client.get("/api/settings").json()
    assert data["api_key"] == main._SECRET_MASK
    assert data["hf_token"] == ""  # unset secrets stay empty

    # Saving the masked draft back must not overwrite the real value.
    r = client.put("/api/settings", json={"api_key": main._SECRET_MASK, "app_name": "Lumina"})
    assert r.status_code == 200
    assert db.get_setting("api_key") == "abc123"


def test_invalid_setting_is_400(client):
    r = client.put("/api/settings", json={"ollama_output_budget": "12"})
    assert r.status_code == 400


def test_old_context_settings_are_retired():
    keys = db.get_all_settings()
    assert "ollama_context_size" not in keys and "ollama_token_budget" not in keys
    assert keys["ollama_output_budget"] == "32768"


# ── Jobs ─────────────────────────────────────────────────────────────────────

def test_retry_resets_and_requeues(client, monkeypatch):
    import jobs

    queued = []

    class FakeWorker:
        def enqueue(self, job_id):
            queued.append(job_id)

    monkeypatch.setattr(jobs, "get_worker", lambda: FakeWorker())
    job = db.create_job(job_type="summarize", source_type="youtube", source_ref="u")
    db.fail_job(job["id"], "boom")

    r = client.post(f"/api/jobs/{job['id']}/retry")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending" and body["error"] is None
    assert queued == [job["id"]]


def test_unknown_job_type_rejected(client):
    r = client.post("/api/jobs", json={"job_type": "nope", "source_type": "url", "source_ref": "x"})
    assert r.status_code == 400


def test_job_list_returns_previews(client):
    job = db.create_job(job_type="summarize")
    db.update_job_status(job["id"], "running")
    db.complete_job(job["id"], result="x" * 5000, result_meta={"extracted_text": "huge", "mode": "summary"})
    listed = client.get("/api/jobs").json()["jobs"][0]
    assert len(listed["result"]) == 2000 and listed["result_truncated"] is True
    assert "extracted_text" not in listed["result_meta"] and listed["result_meta"]["mode"] == "summary"
    full = client.get(f"/api/jobs/{job['id']}").json()
    assert len(full["result"]) == 5000


def test_cancelled_job_is_not_resurrected():
    job = db.create_job(job_type="summarize")
    db.update_job_status(job["id"], "running")
    db.cancel_job(job["id"])
    db.update_job_status(job["id"], "running", "late progress")
    db.complete_job(job["id"], result="late")
    assert db.update_job_progress(job["id"], "x") == "cancelled"
    assert db.get_job(job["id"])["status"] == "cancelled"


# ── Exports from queued transcriptions ───────────────────────────────────────

def test_export_reads_db_transcription_jobs(client):
    job = db.create_job(job_type="transcribe", source_title="talk.mp3")
    db.update_job_status(job["id"], "running")
    db.complete_job(job["id"], result="hello world", result_meta={
        "segments": [{"start": 0.0, "end": 1.5, "text": "hello world"}],
    })
    r = client.get(f"/api/export/{job['id']}")
    assert r.status_code == 200 and r.text == "hello world"
    srt = client.get(f"/api/export/{job['id']}/srt")
    assert srt.status_code == 200 and "00:00:00,000 --> 00:00:01,500" in srt.text


# ── Feeds ────────────────────────────────────────────────────────────────────

def test_feed_timestamp_parsing():
    from feed_monitor import parse_timestamp
    for value in ("2026-11-05T10:00:00+00:00", "2026-11-05T10:00:00Z", "2026-11-05 10:00:00"):
        ts = parse_timestamp(value)
        assert ts is not None and ts.tzinfo is not None and ts.hour == 10
    assert parse_timestamp("garbage") is None and parse_timestamp(None) is None


def test_feed_url_must_be_http(client):
    r = client.post("/api/feeds", json={"url": "/etc/passwd"})
    assert r.status_code in (400, 503)  # 503 when feed deps are missing
