import asyncio
import base64
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

# ── Local dev cache defaults ───────────────────────────────────────────────
# Set before any HuggingFace library is imported so they pick up the right
# cache location. Docker overrides these via docker-compose.yml env vars.
_CACHE_BASE = Path(__file__).parent / "cache"

if "HF_HOME" not in os.environ:
    os.environ["HF_HOME"] = str(_CACHE_BASE / "models" / "hf")
if "WHISPER_DOWNLOAD_ROOT" not in os.environ:
    os.environ["WHISPER_DOWNLOAD_ROOT"] = str(_CACHE_BASE / "models" / "whisper")
# TORCH_HOME — used by older demucs versions / torch.hub downloads
if "TORCH_HOME" not in os.environ:
    os.environ["TORCH_HOME"] = str(_CACHE_BASE / "models" / "torch")
# ──────────────────────────────────────────────────────────────────────────

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import db
from db import init_db, get_all_settings, update_settings as db_update_settings
from llm import OllamaClient
from transcriber import load_engine, set_shared_engine
from audio import AudioPipeline, EnhancementOptions, get_model_status, download_model

_STATIC_DIR = Path(__file__).parent / "static"

# Audio cache path — env-var only since changing it at runtime would orphan files.
AUDIO_CACHE = Path(os.getenv("AUDIO_CACHE_DIR", _CACHE_BASE / "audio"))
AUDIO_CACHE.mkdir(parents=True, exist_ok=True)

# Allowed audio extensions — structural constraint, not a runtime setting.
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".opus", ".aac", ".wma"}

# File extensions routed to VideoExtractor (ffmpeg audio strip first).
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".m4v"}

security = HTTPBasic(auto_error=False)

_SSE_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}

# ── Settings (DB-backed) ───────────────────────────────────────────────────
# Loaded at startup via init_db() + _reload_settings(), then refreshed
# whenever the /api/settings PUT endpoint is called.
_settings: dict[str, str] = {}


def _reload_settings() -> None:
    global _settings
    _settings = get_all_settings()


# Helpers — always read from the live _settings dict.
def _auth_enabled() -> bool:
    return _settings.get("auth_enabled", "false").lower() in ("true", "1", "yes")


def _auth_username() -> str:
    return _settings.get("auth_username", "admin")


def _auth_password() -> str:
    return _settings.get("auth_password", "")


def _app_name() -> str:
    return _settings.get("app_name", "Lumina")


def _api_key() -> str:
    return _settings.get("api_key", "")


# Settings that require an engine restart when changed.
_ENGINE_SETTINGS = {"transcription_engine", "whisper_model_size", "compute_type", "language"}

# ── Authentication ─────────────────────────────────────────────────────────
def verify_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> bool:
    """Verify HTTP Basic Auth credentials if auth is enabled.

    Requests already authenticated by API key (see auth_middleware) pass.
    """
    if not _auth_enabled() or getattr(request.state, "api_key_ok", False):
        return True

    pwd = _auth_password()
    if not pwd:
        raise HTTPException(
            status_code=500,
            detail="auth_enabled=true but auth_password is not set. Configure it in Settings.",
        )

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": f'Basic realm="{_app_name()}"'},
        )

    username_ok = secrets.compare_digest(credentials.username.encode(), _auth_username().encode())
    password_ok = secrets.compare_digest(credentials.password.encode(), pwd.encode())

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": f'Basic realm="{_app_name()}"'},
        )

    return True


# ── In-memory job store ────────────────────────────────────────────────────
_jobs: dict[str, dict] = {}
_lock = threading.Lock()

# ── Engine state ───────────────────────────────────────────────────────────
_engine = None
_engine_status = "loading"   # loading | ready | error
_engine_message = "Starting up..."


def _load_engine_background() -> None:
    """Load (or reload) the transcription engine in a background thread.

    Sets env vars from DB settings before calling load_engine() so that
    existing engine files (which read from os.environ) pick up the right values.
    """
    global _engine, _engine_status, _engine_message

    engine_name = _settings.get("transcription_engine", "faster-whisper")
    model_name  = _settings.get("whisper_model_size", "large-v3-turbo")
    compute     = _settings.get("compute_type", "int8")
    language    = _settings.get("language", "")

    # Propagate DB settings into environment so engine files pick them up.
    os.environ["TRANSCRIPTION_ENGINE"] = engine_name
    os.environ["WHISPER_MODEL_SIZE"]   = model_name
    os.environ["COMPUTE_TYPE"]         = compute
    if language:
        os.environ["LANGUAGE"] = language
    elif "LANGUAGE" in os.environ:
        del os.environ["LANGUAGE"]

    _engine_message = f"Loading {engine_name} · {model_name}…"

    try:
        _engine = load_engine()
        set_shared_engine(_engine)
        _engine_status = "ready"
        _engine_message = "Ready"
    except Exception as exc:
        _engine_status = "error"
        _engine_message = str(exc)


def _purge_old_audio() -> None:
    """Delete audio files (and their sidecars) older than audio_cache_ttl_hours,
    except files that queued or running jobs and live pipeline sessions still use."""
    ttl = int(_settings.get("audio_cache_ttl_hours", "72") or 0)
    if ttl <= 0:
        return
    in_use: set[str] = set()
    for job in db.get_jobs_by_status(["pending", "queued", "running"]):
        if job.get("input_file"):
            in_use.add(Path(job["input_file"]).name)
            in_use.add(Path(job["input_file"]).stem + ".json")
    with _lock:
        for session in _pipeline_sessions.values():
            for key in ("original_file", "current_file"):
                if session.get(key):
                    in_use.add(Path(session[key]).name)
            for step in session.get("steps") or []:
                in_use.add(Path(step.get("output_file", "")).name)
    cutoff = time.time() - (ttl * 3600)
    for f in list(AUDIO_CACHE.iterdir()):
        try:
            if f.name not in in_use and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
        except OSError:
            pass


# Finished jobs and extraction-cache entries are kept for 30 days.
_JOB_RETENTION_HOURS = 30 * 24
_CACHE_RETENTION_HOURS = 30 * 24


def _housekeeping() -> None:
    try:
        _purge_old_audio()
        jobs = db.cleanup_old_jobs(hours=_JOB_RETENTION_HOURS)
        cache = db.cleanup_old_cache(hours=_CACHE_RETENTION_HOURS)
        if jobs or cache:
            print(f"[housekeeping] removed {jobs} old jobs, {cache} stale cache entries")
    except Exception as exc:
        print(f"[housekeeping] failed: {exc}")


async def _purge_loop() -> None:
    while True:
        await asyncio.to_thread(_housekeeping)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Init DB and load settings BEFORE starting the engine thread so
    # _load_engine_background reads the correct DB-backed values.
    init_db()
    _reload_settings()

    thread = threading.Thread(target=_load_engine_background, daemon=True)
    thread.start()

    # Hourly housekeeping (audio TTL, old jobs, stale cache). Always scheduled,
    # so changing the TTL setting later takes effect without a restart.
    housekeeping = asyncio.create_task(_purge_loop())

    # Start feed monitor (no-op if feedparser/apscheduler not installed)
    import feed_monitor
    feed_monitor.start()

    # Start job worker for persistent job queue
    from jobs import init_worker, register_handlers, shutdown_worker
    worker = init_worker()
    register_handlers(worker)
    worker.start()

    yield

    housekeeping.cancel()
    shutdown_worker()
    feed_monitor.stop()


app = FastAPI(title="Lumina", lifespan=lifespan)

from routers.llm import router as llm_router  # noqa: E402

app.include_router(llm_router, dependencies=[Depends(verify_auth)])

# The UI is served from this same origin (and proxied in dev), so cross-origin
# access is off unless explicitly allowed — otherwise any website a user visits
# could read this instance's API from the LAN.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ── Auth middleware (covers static asset requests) ─────────────────────────
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # API key: if set, a matching X-API-Key header or Bearer token on /api/*
    # grants access regardless of whether Basic Auth is enabled.
    key = _api_key()
    if key and request.url.path.startswith("/api/"):
        auth_hdr = request.headers.get("Authorization", "")
        candidate = request.headers.get("X-API-Key") or (
            auth_hdr[7:] if auth_hdr.startswith("Bearer ") else ""
        )
        if candidate and secrets.compare_digest(candidate.encode(), key.encode()):
            request.state.api_key_ok = True
            return await call_next(request)

    if not _auth_enabled():
        return await call_next(request)

    pwd = _auth_password()
    if not pwd:
        return Response(
            content="auth_enabled=true but auth_password is not set.",
            status_code=500,
        )

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            if (secrets.compare_digest(username.encode(), _auth_username().encode()) and
                    secrets.compare_digest(password.encode(), pwd.encode())):
                return await call_next(request)
        except Exception:
            pass

    return Response(
        content="Authentication required",
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{_app_name()}"'},
    )


# ── Engine loading page ────────────────────────────────────────────────────
def _loading_page(message: str, is_error: bool = False) -> str:
    color = "#ef4444" if is_error else "#6366f1"
    name = _app_name() if _settings else "Lumina"
    spinner = "" if is_error else """
      <div style="width:40px;height:40px;border-radius:50%;
        border:3px solid #c8cdd5;border-top-color:#6366f1;
        animation:spin .8s linear infinite;margin-bottom:20px;
      "></div>
      <style>@keyframes spin{to{transform:rotate(360deg)}}</style>"""
    reload_script = "" if is_error else """
      <script>
        const el = document.getElementById('msg');
        const poll = async () => {
          try {
            const r = await fetch('/api/ready');
            const d = await r.json();
            if (d.message) el.textContent = d.message;
            if (d.status === 'ready')  { location.reload(); return; }
            if (d.status === 'error')  { el.textContent = 'Error: ' + d.message; return; }
          } catch (_) { el.textContent = 'Waiting for server\u2026'; }
          setTimeout(poll, 1500);
        };
        poll();
      </script>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{name}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
          background:#e6e8ec;display:flex;align-items:center;
          justify-content:center;min-height:100vh;}}
    .card{{background:#eef0f3;border:1px solid #c8cdd5;border-radius:12px;
           padding:48px 40px;text-align:center;max-width:420px;width:90%;}}
    h1{{font-size:1.3rem;font-weight:700;color:#1e2330;margin-bottom:24px}}
    p{{font-size:.88rem;line-height:1.6;color:{color}}}
  </style>
</head>
<body>
  <div class="card">
    <h1>{name}</h1>
    {spinner}
    <p id="msg">{message}</p>
  </div>
  {reload_script}
</body>
</html>"""


# ── Readiness (no auth — called by loading page before credentials exist) ──
@app.get("/api/ready")
async def get_ready():
    return {"status": _engine_status, "message": _engine_message}


# ── Capabilities ───────────────────────────────────────────────────────────
@app.get("/api/capabilities")
async def get_capabilities(_: bool = Depends(verify_auth)):
    """
    Report which transcription engines are actually usable in this environment.
    Used by the Settings UI to disable options that can't be selected.

    Checks:
      faster-whisper / whisper — always available (base deps)
      canary     — requires NeMo, only installed with --extra canary
      qwen-audio — always has transformers but requires a CUDA GPU
    """
    import importlib.util
    import torch

    gpu = torch.cuda.is_available()

    nemo = importlib.util.find_spec("nemo") is not None

    return {
        "gpu": gpu,
        "engines": {
            "faster-whisper": {"available": True},
            "whisper":        {"available": True},
            "canary":         {
                "available": nemo and gpu,
                "reason":    None if (nemo and gpu)
                             else ("NeMo not installed — rebuild with INSTALL_CANARY=true" if not nemo
                                   else "Requires a CUDA GPU"),
            },
            "qwen-audio":     {
                "available": gpu,
                "reason":    None if gpu else "Requires a CUDA GPU",
            },
        },
    }


# ── Engine info ────────────────────────────────────────────────────────────
@app.get("/api/info")
async def get_info(_: bool = Depends(verify_auth)):
    import torch
    gpu_available = torch.cuda.is_available()
    return {
        "status":        _engine_status,
        "engine":        _settings.get("transcription_engine", "faster-whisper"),
        "model":         _engine.model_name if _engine else None,
        "gpu_available": gpu_available,
        "gpu_name":      torch.cuda.get_device_name(0) if gpu_available else None,
    }


# ── Settings API ───────────────────────────────────────────────────────────
# Secrets are never sent back to the browser; a set secret is shown as MASK and
# a PUT that echoes MASK leaves the stored value untouched.
_SECRET_KEYS = {"auth_password", "api_key", "hf_token", "youtube_cookies"}
_SECRET_MASK = "••••••••"


def _masked(settings: dict[str, str]) -> dict[str, str]:
    return {k: (_SECRET_MASK if k in _SECRET_KEYS and v else v) for k, v in settings.items()}


@app.get("/api/settings")
async def get_settings(_: bool = Depends(verify_auth)):
    return _masked(get_all_settings())


@app.put("/api/settings")
async def put_settings(updates: dict[str, str], _: bool = Depends(verify_auth)):
    updates = {k: v for k, v in updates.items() if not (k in _SECRET_KEYS and v == _SECRET_MASK)}
    old = get_all_settings()
    try:
        new = db_update_settings(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _reload_settings()
    if any(k.startswith("ollama_") for k in updates):
        from llm.runner import clear_profile_cache
        clear_profile_cache()

    engine_changed = any(
        old.get(k) != new.get(k)
        for k in _ENGINE_SETTINGS
        if k in updates
    )

    return {"settings": _masked(new), "restart_required": engine_changed}


@app.post("/api/reload-engine")
async def reload_engine(_: bool = Depends(verify_auth)):
    """Re-initialize the transcription engine using current DB settings."""
    global _engine_status, _engine_message
    _engine_status  = "loading"
    _engine_message = "Reloading engine..."
    thread = threading.Thread(target=_load_engine_background, daemon=True)
    thread.start()
    return {"status": "reloading"}


# ── Ollama ─────────────────────────────────────────────────────────────────

def _ollama_client() -> OllamaClient:
    """Construct an OllamaClient from the current live settings."""
    return OllamaClient(
        base_url=_settings.get("ollama_url", "http://localhost:11434"),
        timeout=float(_settings.get("ollama_timeout", "120")),
    )


@app.get("/api/ollama/test")
async def ollama_test():
    """
    Test connectivity to the configured Ollama instance.
    No auth required — called from the Settings UI before credentials are confirmed.
    Returns {"ok": bool, "message": str}.
    """
    result = await _ollama_client().test_connection()
    return result


@app.get("/api/ollama/models")
async def ollama_models(_: bool = Depends(verify_auth)):
    """
    List models installed in the configured Ollama instance.
    Returns {"models": [{name, size, parameter_size}, ...]} or empty list on error.
    """
    models = await _ollama_client().list_models()
    return {"models": models}


@app.get("/api/ollama/model/{name:path}")
async def ollama_model_info(name: str, _: bool = Depends(verify_auth)):
    """
    Model details for the Settings UI: the model's own max context, its
    capabilities (thinking / vision), and the context Lumina will actually use
    (per-model override → model max, then the optional global cap).
    """
    from llm.runner import ModelProfile, _context_overrides, resolve_num_ctx

    info = await _ollama_client().get_model_info(name)
    if not info:
        raise HTTPException(status_code=404, detail="Model not found")
    profile = ModelProfile(
        name=name,
        context_length=info.get("context_length"),
        modelfile_num_ctx=info.get("modelfile_num_ctx"),
        capabilities=set(info.get("capabilities") or []),
    )
    return {
        **info,
        "override": _context_overrides(_settings).get(name),
        "effective_context": resolve_num_ctx(_settings, name, profile),
    }


# ── Prompts ────────────────────────────────────────────────────────────────

class PromptCreate(BaseModel):
    name:          str
    mode:          str
    system_prompt: str = ""
    template:      str


class PromptUpdate(BaseModel):
    name:          str
    system_prompt: str = ""
    template:      str


@app.get("/api/prompts")
async def list_prompts(_: bool = Depends(verify_auth)):
    """List all prompts (built-in + custom), ordered built-in first then by name.

    Each prompt includes ``output_type`` (markdown | mindmap | json:<renderer>)
    so the frontend knows how to render that mode's results.
    """
    from llm.prompts import get_mode_meta
    return [{**p, "output_type": get_mode_meta(p["mode"])["output_type"]} for p in db.get_all_prompts()]


@app.post("/api/prompts", status_code=201)
async def create_prompt(body: PromptCreate, _: bool = Depends(verify_auth)):
    """Create a new custom prompt."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not body.template.strip():
        raise HTTPException(status_code=400, detail="template is required")
    if "{content}" not in body.template:
        raise HTTPException(status_code=400, detail="template must contain {content}")
    return db.create_prompt(
        name=body.name.strip(),
        mode=body.mode.strip(),
        system_prompt=body.system_prompt,
        template=body.template,
    )


@app.put("/api/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, body: PromptUpdate, _: bool = Depends(verify_auth)):
    """Update a prompt (name, system_prompt, template). Mode cannot be changed."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if "{content}" not in body.template:
        raise HTTPException(status_code=400, detail="template must contain {content}")
    result = db.update_prompt(
        prompt_id=prompt_id,
        name=body.name.strip(),
        system_prompt=body.system_prompt,
        template=body.template,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return result


@app.delete("/api/prompts/{prompt_id}", status_code=204)
async def delete_prompt(prompt_id: str, _: bool = Depends(verify_auth)):
    """Delete a custom prompt. Built-in prompts cannot be deleted."""
    ok = db.delete_prompt(prompt_id)
    if not ok:
        raise HTTPException(status_code=403, detail="Built-in prompts cannot be deleted")


@app.post("/api/prompts/reset")
async def reset_prompts(_: bool = Depends(verify_auth)):
    """Reset all built-in prompts to their hardcoded defaults."""
    db.reset_default_prompts()
    return {"ok": True}


# ── History ────────────────────────────────────────────────────────────────

class HistoryCreate(BaseModel):
    mode:          str
    source:        str
    source_detail: str = ""
    result:        str
    reasoning:     str = ""


@app.get("/api/history/search")
async def search_history(q: str = Query(..., min_length=1), _: bool = Depends(verify_auth)):
    """Full-text search across history results."""
    return db.search_history(q)


@app.get("/api/history")
async def list_history(_: bool = Depends(verify_auth)):
    """Return the 50 most recent summarization history entries."""
    return db.list_history()


@app.post("/api/history", status_code=201)
async def create_history(body: HistoryCreate, _: bool = Depends(verify_auth)):
    """Save a completed summarization to history."""
    if not body.result.strip():
        raise HTTPException(status_code=400, detail="result is required")
    return db.create_history_entry(
        mode=body.mode,
        source=body.source,
        source_detail=body.source_detail,
        result=body.result,
        reasoning=body.reasoning,
    )


@app.delete("/api/history/{entry_id}", status_code=204)
async def delete_history_entry(entry_id: str, _: bool = Depends(verify_auth)):
    """Delete a single history entry."""
    ok = db.delete_history_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Entry not found")


@app.delete("/api/history", status_code=204)
async def clear_history(_: bool = Depends(verify_auth)):
    """Delete all history entries."""
    db.clear_history()


# ── RSS/Podcast feeds ─────────────────────────────────────────────────────

class FeedCreate(BaseModel):
    url:              str
    check_interval:   int  = 3600   # seconds
    auto_summarize:   bool = True
    summarize_mode:   str  = "summary"


@app.get("/api/feeds")
async def list_feeds(_: bool = Depends(verify_auth)):
    return db.list_feeds()


@app.post("/api/feeds", status_code=201)
async def create_feed(body: FeedCreate, _: bool = Depends(verify_auth)):
    import feed_monitor, feedparser

    available, reason = feed_monitor.check_available()
    if not available:
        raise HTTPException(status_code=503, detail=reason)

    if not feed_monitor._is_http_url(body.url):
        raise HTTPException(status_code=400, detail="Feed URL must start with http:// or https://")

    # Validate URL and fetch initial title (network I/O — keep it off the event loop)
    try:
        parsed = await asyncio.to_thread(feedparser.parse, body.url)
        title = parsed.feed.get("title", "") or ""
    except Exception:
        title = ""

    feed = db.create_feed(
        url=body.url,
        title=title,
        check_interval=body.check_interval,
        auto_summarize=body.auto_summarize,
        summarize_mode=body.summarize_mode,
    )
    # Kick off an immediate check in the background
    threading.Thread(
        target=feed_monitor.check_feed, args=(feed["id"],), daemon=True
    ).start()
    return feed


@app.delete("/api/feeds/{feed_id}", status_code=204)
async def delete_feed(feed_id: str, _: bool = Depends(verify_auth)):
    ok = db.delete_feed(feed_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Feed not found")


@app.get("/api/feeds/{feed_id}/entries")
async def list_feed_entries(feed_id: str, _: bool = Depends(verify_auth)):
    return db.list_feed_entries(feed_id)


@app.post("/api/feeds/{feed_id}/check")
async def check_feed_now(feed_id: str, background_tasks: BackgroundTasks, _: bool = Depends(verify_auth)):
    import feed_monitor
    available, reason = feed_monitor.check_available()
    if not available:
        raise HTTPException(status_code=503, detail=reason)
    background_tasks.add_task(feed_monitor.check_feed, feed_id)
    return {"status": "checking"}


@app.get("/api/feeds/status")
async def feeds_status(_: bool = Depends(verify_auth)):
    """Return whether feed monitoring dependencies are available."""
    import feed_monitor
    available, reason = feed_monitor.check_available()
    return {"available": available, "reason": reason}


# ── Audio enhancement models ───────────────────────────────────────────────

@app.get("/api/audio/models")
async def get_audio_models(_: bool = Depends(verify_auth)):
    """
    Return package installation and weight-download status for each
    audio enhancement model.
    Shape: { "deepfilternet": {"package": bool, "weights": bool}, ... }
    """
    return get_model_status()


class DownloadModelsRequest(BaseModel):
    models: list[str]   # e.g. ["deepfilternet", "demucs", "lavasr"]


@app.post("/api/audio/models/download")
async def download_audio_models(req: DownloadModelsRequest, _: bool = Depends(verify_auth)):
    """
    Download model weights for one or more enhancement models.
    Streams SSE progress events; each model downloads sequentially.

    Events:
      {"model": "...", "status": "downloading"}
      {"model": "...", "status": "done"}
      {"model": "...", "status": "error", "error": "..."}
      [DONE]
    """
    async def event_stream():
        for name in req.models:
            yield f"data: {json.dumps({'model': name, 'status': 'downloading'})}\n\n"
            try:
                await asyncio.to_thread(download_model, name)
                yield f"data: {json.dumps({'model': name, 'status': 'done'})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'model': name, 'status': 'error', 'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ── Text-to-Speech ────────────────────────────────────────────────────────

from tts import TTSEngine, get_tts_status, download_tts_model, VOICES
from tts.preprocess import preprocess_for_speech


@app.get("/api/tts/status")
async def tts_status(_: bool = Depends(verify_auth)):
    """Return TTS package/weights availability."""
    return get_tts_status()


@app.get("/api/tts/voices")
async def tts_voices(_: bool = Depends(verify_auth)):
    """Return available voices with metadata."""
    return {"voices": VOICES}


@app.post("/api/tts/download")
async def tts_download(_: bool = Depends(verify_auth)):
    """
    Download Kokoro TTS model weights.
    Streams SSE progress events.

    Events:
      {"status": "downloading", "message": "..."}
      {"status": "done",        "message": "..."}
      {"status": "error",       "error":   "..."}
      [DONE]
    """
    async def event_stream():
        msg = {'status': 'downloading', 'message': 'Downloading Kokoro TTS model\u2026'}
        yield f"data: {json.dumps(msg)}\n\n"
        try:
            await asyncio.to_thread(download_tts_model)
            yield f"data: {json.dumps({'status': 'done', 'message': 'Model ready'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'status': 'error', 'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


class TTSSynthesizeRequest(BaseModel):
    text:  str
    voice: str | None = None  # Falls back to tts_voice setting


@app.post("/api/tts/synthesize")
async def tts_synthesize(req: TTSSynthesizeRequest, _: bool = Depends(verify_auth)):
    """
    Synthesize text to speech and return audio/wav.
    Uses the configured default voice if none is specified.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    voice = req.voice or _settings.get("tts_voice", "af_bella")
    speech_text = preprocess_for_speech(req.text)
    engine = TTSEngine()
    try:
        audio_bytes = await asyncio.to_thread(engine.synthesize, speech_text, voice)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return Response(content=audio_bytes, media_type="audio/wav")


def _run_enhancement(
    job_id: str,
    audio_path: Path,
    options: EnhancementOptions,
) -> None:
    """Background task: run the enhancement pipeline without transcription."""

    def _status(phase: str, detail: str) -> None:
        with _lock:
            _jobs[job_id]["status"]        = "enhancing"
            _jobs[job_id]["status_detail"] = detail

    try:
        pipeline = AudioPipeline()
        enhanced = pipeline.run_sync(audio_path, options, _status)

        if enhanced != audio_path:
            # Move the temp enhanced file to a stable location in the cache
            enhanced_name = f"{job_id}_enhanced{enhanced.suffix}"
            enhanced_path = AUDIO_CACHE / enhanced_name
            enhanced.rename(enhanced_path)
        else:
            # No-op enhancement — serve the original
            enhanced_path = audio_path

        # Update the sidecar with enhanced file info
        sidecar = AUDIO_CACHE / f"{job_id}.json"
        if sidecar.exists():
            meta = json.loads(sidecar.read_text())
            meta["enhanced_file"] = enhanced_path.name
            meta["enhancement_options"] = {
                "normalize": options.normalize,
                "denoise":   options.denoise,
                "isolate":   options.isolate,
                "upsample":  options.upsample,
            }
            sidecar.write_text(json.dumps(meta))

        with _lock:
            _jobs[job_id]["status"]        = "done"
            _jobs[job_id]["status_detail"] = ""
            _jobs[job_id]["enhanced_path"] = str(enhanced_path)

    except Exception as exc:
        traceback.print_exc()
        with _lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"]  = str(exc) or repr(exc)


def _sanitize_filename(filename: str) -> str:
    name = Path(filename).name
    return "".join(c for c in name if c.isalnum() or c in "._- ").strip() or "audio"


@app.post("/api/transcribe")
async def transcribe(
    file:              UploadFile = File(...),
    enhance_normalize: bool       = Form(False),
    enhance_denoise:   bool       = Form(False),
    enhance_isolate:   bool       = Form(False),
    enhance_separate:  bool       = Form(False),
    enhance_upsample:  bool       = Form(False),
    _: bool = Depends(verify_auth),
):
    if _engine_status != "ready":
        raise HTTPException(status_code=503, detail="Engine is still loading — please wait.")

    suffix = Path(file.filename or "audio").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    max_mb  = int(_settings.get("max_upload_size_mb", "500"))

    if max_mb > 0 and size_mb > max_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {size_mb:.1f} MB. Maximum: {max_mb} MB",
        )

    # Generate job ID and save file
    job_id     = str(uuid.uuid4())
    audio_file = f"{job_id}{suffix}"
    audio_path = AUDIO_CACHE / audio_file

    with open(audio_path, "wb") as f:
        f.write(contents)

    # Write sidecar for file metadata (legacy compatibility)
    sidecar = AUDIO_CACHE / f"{job_id}.json"
    sidecar.write_text(json.dumps({
        "job_id":      job_id,
        "filename":    file.filename,
        "audio_file":  audio_path.name,
        "size":        audio_path.stat().st_size,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }))

    # Create DB job with the same ID as the stored file and sidecar
    job = db.create_job(
        job_id=job_id,
        job_type="transcribe",
        config={
            "enhancement": {
                "normalize": enhance_normalize,
                "denoise": enhance_denoise,
                "isolate": enhance_isolate,
                "separate": enhance_separate,
                "upsample": enhance_upsample,
            },
        },
        source_type="file",
        source_ref=file.filename,
        source_title=file.filename,
        input_file=audio_file,
    )

    # Enqueue to worker
    from jobs import get_worker
    worker = get_worker()
    if worker:
        worker.enqueue(job_id)
    else:
        # Fallback if worker not running (shouldn't happen)
        db.fail_job(job_id, "Job worker not available")

    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str, _: bool = Depends(verify_auth)):
    # First check DB jobs (new system)
    db_job = db.get_job(job_id)
    if db_job:
        # Map DB job to legacy response format for compatibility
        return {
            "status": db_job["status"],
            "status_detail": db_job.get("status_detail", ""),
            "result": db_job.get("result"),
            "segments": db_job.get("result_meta", {}).get("segments", []),
            "language": db_job.get("result_meta", {}).get("language", ""),
            "error": db_job.get("error"),
            "filename": db_job.get("source_title") or db_job.get("source_ref", ""),
            "audio_path": str(AUDIO_CACHE / db_job["input_file"]) if db_job.get("input_file") else "",
        }

    # Fall back to in-memory jobs (legacy)
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Job Queue API ─────────────────────────────────────────────────────────────

@app.get("/api/jobs")
async def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    job_type: str | None = Query(None, alias="type", description="Filter by job type"),
    batch_id: str | None = Query(None, description="Filter by batch ID"),
    limit: int = Query(50, ge=1, le=200),
    _: bool = Depends(verify_auth),
):
    """List jobs with optional filters.

    List entries are summaries: results are cut to a preview and bulky
    result_meta keys (transcripts, segments, reasoning) are dropped — fetch
    GET /api/jobs/{id} for the full job.
    """
    status_filter = status.split(",") if status else None
    jobs = db.list_jobs(
        status=status_filter,
        job_type=job_type,
        batch_id=batch_id,
        limit=limit,
    )
    return {"jobs": [_job_summary(j) for j in jobs]}


_PREVIEW_CHARS = 2000
_BULKY_META = {"extracted_text", "segments", "reasoning", "data", "diarization", "source_meta"}


def _job_summary(job: dict) -> dict:
    result = job.get("result") or ""
    return {
        **job,
        "result": result[:_PREVIEW_CHARS] if result else job.get("result"),
        "result_truncated": len(result) > _PREVIEW_CHARS,
        "result_meta": {k: v for k, v in (job.get("result_meta") or {}).items() if k not in _BULKY_META},
    }


@app.get("/api/jobs/active")
async def get_active_jobs(_: bool = Depends(verify_auth)):
    """Get counts of active jobs (for header indicator)."""
    counts = db.get_active_job_count()
    return counts


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, _: bool = Depends(verify_auth)):
    """Get a single job by ID."""
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str, _: bool = Depends(verify_auth)):
    """Cancel a job."""
    job = db.cancel_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str, _: bool = Depends(verify_auth)):
    """Retry a failed or cancelled job."""
    from jobs import get_worker

    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] not in ("error", "cancelled"):
        raise HTTPException(status_code=400, detail="Can only retry failed or cancelled jobs")

    db.reset_job_for_retry(job_id)

    # Re-enqueue
    worker = get_worker()
    if worker:
        worker.enqueue(job_id)
    else:
        db.fail_job(job_id, "Job worker not available")

    return db.get_job(job_id)


class CreateJobRequest(BaseModel):
    job_type: str
    source_type: str
    source_ref: str
    source_title: str | None = None
    config: dict = {}


@app.post("/api/jobs")
async def create_single_job(
    request: CreateJobRequest,
    _: bool = Depends(verify_auth),
):
    """Create a single job."""
    from jobs import get_worker

    if request.job_type not in db.JOB_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown job type: {request.job_type}")

    job = db.create_job(
        job_type=request.job_type,
        config=request.config,
        source_type=request.source_type,
        source_ref=request.source_ref,
        source_title=request.source_title,
    )

    worker = get_worker()
    if worker:
        worker.enqueue(job["id"])
    else:
        db.fail_job(job["id"], "Job worker not available")

    return job


class BatchJobRequest(BaseModel):
    urls: list[str]
    job_type: str = "summarize"
    config: dict = {}


@app.post("/api/jobs/batch")
async def create_batch_jobs(
    request: BatchJobRequest,
    _: bool = Depends(verify_auth),
):
    """Create multiple jobs from a list of URLs."""
    from jobs import get_worker

    if not request.urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    batch_id = str(uuid.uuid4())
    jobs = []

    for url in request.urls:
        # Determine source type from URL
        source_type = "url"
        if "youtube.com" in url or "youtu.be" in url:
            source_type = "youtube"

        job = db.create_job(
            job_type=request.job_type,
            config=request.config,
            source_type=source_type,
            source_ref=url,
            batch_id=batch_id,
        )
        jobs.append(job)

        # Enqueue job
        worker = get_worker()
        if worker:
            worker.enqueue(job["id"])

    return {
        "batch_id": batch_id,
        "job_count": len(jobs),
        "jobs": jobs,
    }


@app.delete("/api/jobs/batch/{batch_id}")
async def cancel_batch(batch_id: str, _: bool = Depends(verify_auth)):
    """Cancel all jobs in a batch."""
    count = db.cancel_batch(batch_id)
    return {"cancelled": count}


# ── Extraction Cache API ──────────────────────────────────────────────────────

@app.get("/api/cache/{content_hash}")
async def get_cache_entry(content_hash: str, _: bool = Depends(verify_auth)):
    """Check if content is cached."""
    cache = db.get_extraction_cache(content_hash)
    if cache is None:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return {
        "cached": True,
        "content_hash": cache["content_hash"],
        "source_type": cache["source_type"],
        "title": cache.get("title"),
        "created_at": cache["created_at"],
        "accessed_at": cache["accessed_at"],
        "text_length": len(cache.get("extracted_text", "")),
    }


@app.delete("/api/cache/{content_hash}")
async def invalidate_cache(content_hash: str, _: bool = Depends(verify_auth)):
    """Delete a cache entry (force refresh)."""
    deleted = db.delete_extraction_cache(content_hash)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return {"deleted": True}


@app.get("/api/cache")
async def get_cache_stats(_: bool = Depends(verify_auth)):
    """Get cache statistics."""
    stats = db.get_cache_stats()
    return stats


class CacheLookupRequest(BaseModel):
    source_type: str
    source_ref: str


@app.post("/api/cache/lookup")
async def lookup_cache(request: CacheLookupRequest, _: bool = Depends(verify_auth)):
    """Look up cache by source type and ref (computes hash)."""
    from jobs import compute_content_hash

    content_hash = compute_content_hash(request.source_type, request.source_ref)
    cache = db.get_extraction_cache(content_hash)

    if cache is None:
        return {"cached": False, "content_hash": content_hash}

    return {
        "cached": True,
        "content_hash": content_hash,
        "title": cache.get("title"),
        "created_at": cache["created_at"],
        "accessed_at": cache["accessed_at"],
        "text_length": len(cache.get("extracted_text", "")),
    }


@app.get("/api/audio/{job_id}")
async def get_audio(job_id: str, _: bool = Depends(verify_auth)):
    # Check DB jobs first
    db_job = db.get_job(job_id)
    if db_job and db_job.get("input_file"):
        audio_path = AUDIO_CACHE / db_job["input_file"]
        if audio_path.exists():
            filename = _sanitize_filename(db_job.get("source_title") or audio_path.name)
            return FileResponse(audio_path, media_type="audio/mpeg", filename=filename)

    # Fall back to in-memory jobs
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    audio_path = Path(job.get("audio_path", ""))
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    filename = _sanitize_filename(job.get("filename") or audio_path.name)
    return FileResponse(audio_path, media_type="audio/mpeg", filename=filename)


def _transcription_job(job_id: str) -> dict:
    """A transcription as a plain dict, from the DB job queue or the legacy
    in-memory store: {status, result, segments, filename, audio_path, db}."""
    db_job = db.get_job(job_id)
    if db_job:
        meta = db_job.get("result_meta") or {}
        return {
            "status":     db_job["status"],
            "result":     db_job.get("result") or "",
            "segments":   meta.get("segments") or [],
            "filename":   db_job.get("source_title") or db_job.get("source_ref") or "",
            "audio_path": str(AUDIO_CACHE / db_job["input_file"]) if db_job.get("input_file") else "",
            "db":         True,
        }
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {**job, "db": False}


@app.get("/api/export/{job_id}")
async def export_txt(job_id: str, _: bool = Depends(verify_auth)):
    job = _transcription_job(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Transcription not complete")

    stem = _sanitize_filename(Path(job.get("filename") or "transcription").stem)
    return PlainTextResponse(
        job["result"],
        headers={"Content-Disposition": f'attachment; filename="{stem}.txt"'},
    )


def _fmt_srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms  = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_vtt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms  = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _get_job_segments(job_id: str) -> tuple[dict, list[dict]]:
    """Return (job, segments) — falls back to sidecar for segments if needed."""
    job = _transcription_job(job_id)
    if job.get("status") != "done":
        raise HTTPException(status_code=400, detail="Transcription not complete")
    segments = job.get("segments") or []
    # If job was restored from sidecar (server restart), load segments from disk
    if not segments:
        sidecar = AUDIO_CACHE / f"{job_id}.json"
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text())
                segments = meta.get("segments", [])
            except Exception:
                pass
    return job, segments


@app.get("/api/export/{job_id}/srt")
async def export_srt(job_id: str, _: bool = Depends(verify_auth)):
    job, segments = _get_job_segments(job_id)
    if not segments:
        raise HTTPException(status_code=400, detail="No segment timestamps available for this transcription")

    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    content = "\n".join(lines)
    stem = _sanitize_filename(Path(job.get("filename") or "subtitles").stem)
    return PlainTextResponse(
        content,
        headers={"Content-Disposition": f'attachment; filename="{stem}.srt"'},
    )


@app.get("/api/export/{job_id}/vtt")
async def export_vtt(job_id: str, _: bool = Depends(verify_auth)):
    job, segments = _get_job_segments(job_id)
    if not segments:
        raise HTTPException(status_code=400, detail="No segment timestamps available for this transcription")

    lines: list[str] = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_fmt_vtt_time(seg['start'])} --> {_fmt_vtt_time(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    content = "\n".join(lines)
    stem = _sanitize_filename(Path(job.get("filename") or "subtitles").stem)
    return PlainTextResponse(
        content,
        media_type="text/vtt",
        headers={"Content-Disposition": f'attachment; filename="{stem}.vtt"'},
    )


# ── Audio clip extraction ───────────────────────────────────────────────────

class ClipRequest(BaseModel):
    start:  float       # seconds
    end:    float       # seconds
    format: str = "mp3" # mp3 | wav | m4a


@app.post("/api/clip/{job_id}")
async def extract_clip(job_id: str, req: ClipRequest, _: bool = Depends(verify_auth)):
    """Extract a time-range clip from an uploaded audio file using ffmpeg."""
    job = _transcription_job(job_id)

    audio_path = Path(job.get("audio_path", ""))
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    if req.end <= req.start:
        raise HTTPException(status_code=400, detail="end must be greater than start")

    allowed_formats = {"mp3", "wav", "m4a", "flac"}
    fmt = req.format.lower()
    if fmt not in allowed_formats:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")

    clip_id = str(uuid.uuid4())[:8]
    clip_name = f"{job_id}_clip_{clip_id}.{fmt}"
    clip_path = AUDIO_CACHE / clip_name

    codec_map = {"mp3": "libmp3lame", "wav": "pcm_s16le", "m4a": "aac", "flac": "flac"}
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(req.start),
        "-i", str(audio_path),
        "-t", str(req.end - req.start),
        "-c:a", codec_map[fmt],
        "-vn",
        str(clip_path),
    ]
    try:
        await asyncio.to_thread(subprocess.run, cmd, check=True, capture_output=True, timeout=600)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=f"ffmpeg error: {exc.stderr.decode()[:200]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="ffmpeg timed out")

    return {"clip_id": clip_id, "filename": clip_name, "job_id": job_id}


@app.get("/api/clip/{job_id}/{clip_id}/download")
async def download_clip(job_id: str, clip_id: str, _: bool = Depends(verify_auth)):
    """Download a previously extracted clip."""
    # IDs are server-generated; reject anything that could act as a glob pattern.
    if not all(c.isalnum() or c == "-" for c in job_id + clip_id):
        raise HTTPException(status_code=404, detail="Clip not found")
    matches = list(AUDIO_CACHE.glob(f"{job_id}_clip_{clip_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Clip not found")
    clip_path = matches[0]
    stem = clip_path.stem
    return FileResponse(clip_path, filename=stem + clip_path.suffix)


# ── Speaker Diarization ────────────────────────────────────────────────────

@app.get("/api/diarize/status")
async def diarize_status(_: bool = Depends(verify_auth)):
    """Return whether pyannote.audio is installed and a token is configured."""
    import diarization as diarz
    available, reason = diarz.check_available()
    hf_token = _settings.get("hf_token", "")
    return {
        "available": available,
        "reason": reason,
        "token_configured": bool(hf_token),
    }


@app.post("/api/diarize/{job_id}")
async def diarize_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_auth),
):
    """
    Run speaker diarization on the audio from a completed transcription job.
    Returns the diarization result (list of speaker segments) synchronously.
    The job's transcript segments are merged with speaker labels and stored.
    """
    job = _transcription_job(job_id)
    if job.get("status") != "done":
        raise HTTPException(status_code=400, detail="Transcription must be complete before diarizing")

    audio_path = Path(job.get("audio_path", ""))
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    hf_token = _settings.get("hf_token", "")

    import diarization as diarz

    available, reason = diarz.check_available()
    if not available:
        raise HTTPException(status_code=503, detail=reason)
    if not hf_token:
        raise HTTPException(
            status_code=400,
            detail="HuggingFace token not configured — set it in Settings → Security."
        )

    try:
        raw_diarization = await asyncio.get_event_loop().run_in_executor(
            None, diarz.diarize, audio_path, hf_token
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Diarization failed: {exc}")

    # Merge speaker labels into existing transcript segments
    segments = job.get("segments", [])
    merged = diarz.merge_with_transcript(raw_diarization, segments)

    if job["db"]:
        db.update_job_result_meta(job_id, {"segments": merged, "diarization": raw_diarization})
    else:
        with _lock:
            _jobs[job_id]["segments"] = merged
            _jobs[job_id]["diarization"] = raw_diarization

    # Persist merged segments to sidecar
    sidecar = AUDIO_CACHE / f"{job_id}.json"
    if sidecar.exists():
        try:
            meta = json.loads(sidecar.read_text())
            meta["segments"] = merged
            meta["diarization"] = raw_diarization
            sidecar.write_text(json.dumps(meta))
        except Exception:
            pass

    return {"segments": merged, "diarization": raw_diarization}


@app.get("/api/files")
async def list_files(_: bool = Depends(verify_auth)):
    """Return metadata for all audio files currently in the cache."""
    files = []
    for sidecar in AUDIO_CACHE.glob("*.json"):
        try:
            meta = json.loads(sidecar.read_text())
            if (AUDIO_CACHE / meta["audio_file"]).exists():
                files.append(meta)
        except Exception:
            pass
    files.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return files


class RetranscribeRequest(BaseModel):
    enhance_normalize: bool = False
    enhance_denoise:   bool = False
    enhance_isolate:   bool = False
    enhance_separate:  bool = False
    enhance_upsample:  bool = False


@app.post("/api/retranscribe/{job_id}")
async def retranscribe(
    job_id: str,
    background_tasks: BackgroundTasks,
    req: RetranscribeRequest = RetranscribeRequest(),
    _: bool = Depends(verify_auth),
):
    if _engine_status != "ready":
        raise HTTPException(status_code=503, detail="Engine is still loading — please wait.")

    sidecar = AUDIO_CACHE / f"{job_id}.json"
    if not sidecar.exists():
        raise HTTPException(status_code=404, detail="File not found")

    meta       = json.loads(sidecar.read_text())
    audio_path = AUDIO_CACHE / meta["audio_file"]
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    opts = EnhancementOptions(
        normalize=req.enhance_normalize,
        denoise  =req.enhance_denoise,
        isolate  =req.enhance_isolate,
        separate =req.enhance_separate,
        upsample =req.enhance_upsample,
    )

    job = db.create_job(
        job_type="transcribe",
        config={"enhancement": {
            "normalize": opts.normalize, "denoise": opts.denoise, "isolate": opts.isolate,
            "separate": opts.separate, "upsample": opts.upsample,
        }},
        source_type="file",
        source_ref=meta.get("filename"),
        source_title=meta.get("filename"),
        input_file=meta["audio_file"],
    )
    from jobs import get_worker
    worker = get_worker()
    if worker:
        worker.enqueue(job["id"])
    else:
        db.fail_job(job["id"], "Job worker not available")
    return {"job_id": job["id"]}


# ── Audio Enhancement ──────────────────────────────────────────────────────

@app.post("/api/enhance")
async def enhance_audio(
    background_tasks: BackgroundTasks,
    file:              UploadFile = File(...),
    enhance_normalize: bool       = Form(False),
    enhance_denoise:   bool       = Form(False),
    enhance_isolate:   bool       = Form(False),
    enhance_separate:  bool       = Form(False),
    enhance_upsample:  bool       = Form(False),
    _: bool = Depends(verify_auth),
):
    """Upload an audio file and run the enhancement pipeline (no transcription)."""
    suffix = Path(file.filename or "audio").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    contents = await file.read()
    size_mb  = len(contents) / (1024 * 1024)
    max_mb   = int(_settings.get("max_upload_size_mb", "500"))

    if max_mb > 0 and size_mb > max_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {size_mb:.1f} MB. Maximum: {max_mb} MB",
        )

    job_id     = str(uuid.uuid4())
    audio_path = AUDIO_CACHE / f"{job_id}{suffix}"

    with open(audio_path, "wb") as f:
        f.write(contents)

    sidecar = AUDIO_CACHE / f"{job_id}.json"
    sidecar.write_text(json.dumps({
        "job_id":      job_id,
        "filename":    file.filename,
        "audio_file":  audio_path.name,
        "size":        audio_path.stat().st_size,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "type":        "enhance",
    }))

    opts = EnhancementOptions(
        normalize=enhance_normalize,
        denoise  =enhance_denoise,
        isolate  =enhance_isolate,
        separate =enhance_separate,
        upsample =enhance_upsample,
    )

    with _lock:
        _jobs[job_id] = {
            "status":        "pending",
            "status_detail": "",
            "result":        None,
            "error":         None,
            "filename":      file.filename,
            "audio_path":    str(audio_path),
            "enhanced_path": None,
        }

    background_tasks.add_task(_run_enhancement, job_id, audio_path, opts)
    return {"job_id": job_id}


@app.get("/api/enhance/{job_id}/download")
async def download_enhanced(job_id: str, _: bool = Depends(verify_auth)):
    """Download the enhanced audio file produced by a completed enhance job."""
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Enhancement not complete")

    enhanced_path = Path(job.get("enhanced_path") or "")
    if not enhanced_path.exists():
        raise HTTPException(status_code=404, detail="Enhanced file not found")

    stem   = _sanitize_filename(Path(job.get("filename") or "audio").stem)
    suffix = enhanced_path.suffix
    return FileResponse(
        enhanced_path,
        media_type="application/octet-stream",
        filename=f"{stem}_enhanced{suffix}",
    )


@app.get("/api/enhance/{job_id}/original")
async def download_original_for_enhance(job_id: str, _: bool = Depends(verify_auth)):
    """Serve the original (pre-enhancement) audio for A/B comparison."""
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    audio_path = Path(job.get("audio_path") or "")
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    filename = _sanitize_filename(job.get("filename") or audio_path.name)
    return FileResponse(audio_path, media_type="audio/mpeg", filename=filename)


class ReenhanceRequest(BaseModel):
    enhance_normalize: bool = False
    enhance_denoise:   bool = False
    enhance_isolate:   bool = False
    enhance_separate:  bool = False
    enhance_upsample:  bool = False


@app.post("/api/reenhance/{job_id}")
async def reenhance(
    job_id: str,
    background_tasks: BackgroundTasks,
    req: ReenhanceRequest = ReenhanceRequest(),
    _: bool = Depends(verify_auth),
):
    """Re-run enhancement on an existing file with different settings."""
    sidecar = AUDIO_CACHE / f"{job_id}.json"
    if not sidecar.exists():
        raise HTTPException(status_code=404, detail="File not found")

    meta       = json.loads(sidecar.read_text())
    audio_path = AUDIO_CACHE / meta["audio_file"]
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    opts = EnhancementOptions(
        normalize=req.enhance_normalize,
        denoise  =req.enhance_denoise,
        isolate  =req.enhance_isolate,
        separate =req.enhance_separate,
        upsample =req.enhance_upsample,
    )

    new_job_id  = str(uuid.uuid4())
    new_sidecar = AUDIO_CACHE / f"{new_job_id}.json"
    new_sidecar.write_text(json.dumps({
        "job_id":        new_job_id,
        "filename":      meta.get("filename"),
        "audio_file":    meta["audio_file"],   # reuse same original
        "size":          meta.get("size"),
        "uploaded_at":   datetime.now(timezone.utc).isoformat(),
        "type":          "enhance",
        "original_job":  job_id,
    }))

    with _lock:
        _jobs[new_job_id] = {
            "status":        "pending",
            "status_detail": "",
            "result":        None,
            "error":         None,
            "filename":      meta.get("filename"),
            "audio_path":    str(audio_path),
            "enhanced_path": None,
        }

    background_tasks.add_task(_run_enhancement, new_job_id, audio_path, opts)
    return {"job_id": new_job_id}


# ── Interactive Audio Pipeline ─────────────────────────────────────────────

_PIPELINE_VALID_STEPS = {"normalize", "denoise", "isolate", "separate", "upsample"}

_pipeline_sessions: dict[str, dict] = {}


def _run_pipeline_step(session_id: str, step: str) -> None:
    """Background task: apply a single enhancement step to the pipeline current audio."""
    with _lock:
        session = _pipeline_sessions.get(session_id)
    if not session:
        return

    try:
        current_file = Path(session["current_file"])
        step_index   = len(session["steps"])
        out_file     = AUDIO_CACHE / f"{session_id}_step{step_index}{current_file.suffix or '.wav'}"

        AudioPipeline().run_single_step(current_file, step, out_file)

        step_record = {
            "step":        step,
            "output_file": out_file.name,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }

        with _lock:
            _pipeline_sessions[session_id]["steps"].append(step_record)
            _pipeline_sessions[session_id]["current_file"]  = str(out_file)
            _pipeline_sessions[session_id]["status"]        = "idle"
            _pipeline_sessions[session_id]["status_detail"] = ""

    except Exception as exc:
        traceback.print_exc()
        with _lock:
            _pipeline_sessions[session_id]["status"] = "error"
            _pipeline_sessions[session_id]["error"]  = str(exc) or repr(exc)


@app.post("/api/pipeline")
async def create_pipeline(
    file: UploadFile = File(...),
    _: bool = Depends(verify_auth),
):
    """Create a new interactive pipeline session by uploading an audio file."""
    suffix = Path(file.filename or "audio").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    contents = await file.read()
    size_mb  = len(contents) / (1024 * 1024)
    max_mb   = int(_settings.get("max_upload_size_mb", "500"))
    if max_mb > 0 and size_mb > max_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {size_mb:.1f} MB. Maximum: {max_mb} MB",
        )

    session_id = str(uuid.uuid4())
    audio_path = AUDIO_CACHE / f"{session_id}_original{suffix}"
    with open(audio_path, "wb") as f:
        f.write(contents)

    session = {
        "session_id":    session_id,
        "filename":      file.filename,
        "original_file": audio_path.name,
        "current_file":  str(audio_path),
        "steps":         [],
        "transcription": None,
        "status":        "idle",
        "status_detail": "",
        "error":         None,
    }
    with _lock:
        _pipeline_sessions[session_id] = session

    return {"session_id": session_id, "filename": file.filename}


@app.get("/api/pipeline/{session_id}")
async def get_pipeline_session(session_id: str, _: bool = Depends(verify_auth)):
    """Return the current state of a pipeline session."""
    with _lock:
        session = _pipeline_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Pipeline session not found")
    return session


class PipelineStepRequest(BaseModel):
    step: str  # "normalize" | "denoise" | "isolate" | "upsample"


@app.post("/api/pipeline/{session_id}/step")
async def apply_pipeline_step(
    session_id: str,
    req: PipelineStepRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_auth),
):
    """Apply a single named enhancement step to the pipeline's current audio."""
    if req.step not in _PIPELINE_VALID_STEPS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid step: {req.step!r}. Must be one of: {', '.join(sorted(_PIPELINE_VALID_STEPS))}",
        )

    with _lock:
        session = _pipeline_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Pipeline session not found")
    if session["status"] == "processing":
        raise HTTPException(status_code=409, detail="A step is already in progress")

    with _lock:
        _pipeline_sessions[session_id]["status"]        = "processing"
        _pipeline_sessions[session_id]["status_detail"] = f"Applying {req.step}…"
        _pipeline_sessions[session_id]["error"]         = None

    background_tasks.add_task(_run_pipeline_step, session_id, req.step)
    return {"status": "processing", "step": req.step}


@app.get("/api/pipeline/{session_id}/audio")
async def get_pipeline_audio(
    session_id: str,
    step: str = Query(default="current"),
    _: bool = Depends(verify_auth),
):
    """
    Serve audio for a pipeline session.
    ?step=current (default) — latest processed audio
    ?step=original          — the original uploaded file
    ?step=0, 1, 2, ...     — output of step N
    """
    with _lock:
        session = _pipeline_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Pipeline session not found")

    if step == "original":
        audio_path = AUDIO_CACHE / session["original_file"]
    elif step == "current":
        audio_path = Path(session["current_file"])
    else:
        try:
            idx   = int(step)
            steps = session["steps"]
            if idx < 0 or idx >= len(steps):
                raise HTTPException(status_code=404, detail=f"Step {idx} not found")
            audio_path = AUDIO_CACHE / steps[idx]["output_file"]
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid step parameter: {step!r}")

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(audio_path, media_type="audio/mpeg")


@app.delete("/api/pipeline/{session_id}/step")
async def undo_pipeline_step(session_id: str, _: bool = Depends(verify_auth)):
    """Remove the last enhancement step and revert to the previous audio state."""
    with _lock:
        session = _pipeline_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Pipeline session not found")
    if session["status"] == "processing":
        raise HTTPException(status_code=409, detail="Cannot undo while a step is in progress")
    if not session["steps"]:
        raise HTTPException(status_code=400, detail="No steps to undo")

    with _lock:
        steps   = _pipeline_sessions[session_id]["steps"]
        removed = steps.pop()
        (AUDIO_CACHE / removed["output_file"]).unlink(missing_ok=True)
        if steps:
            _pipeline_sessions[session_id]["current_file"] = str(AUDIO_CACHE / steps[-1]["output_file"])
        else:
            _pipeline_sessions[session_id]["current_file"] = str(AUDIO_CACHE / session["original_file"])
        _pipeline_sessions[session_id]["error"] = None
        steps_remaining = len(steps)

    return {"status": "ok", "steps_remaining": steps_remaining}


@app.post("/api/pipeline/{session_id}/transcribe")
async def transcribe_pipeline_audio(
    session_id: str,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_auth),
):
    """Transcribe the pipeline's current audio using the configured Whisper engine."""
    if _engine_status != "ready":
        raise HTTPException(status_code=503, detail="Engine is still loading — please wait.")

    with _lock:
        session = _pipeline_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Pipeline session not found")
    if session["status"] == "processing":
        raise HTTPException(status_code=409, detail="A step is still in progress")

    current_file = Path(session["current_file"])
    if not current_file.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    job_id     = str(uuid.uuid4())
    audio_path = AUDIO_CACHE / f"{job_id}{current_file.suffix}"
    shutil.copy2(current_file, audio_path)

    sidecar = AUDIO_CACHE / f"{job_id}.json"
    sidecar.write_text(json.dumps({
        "job_id":           job_id,
        "filename":         session.get("filename"),
        "audio_file":       audio_path.name,
        "size":             audio_path.stat().st_size,
        "uploaded_at":      datetime.now(timezone.utc).isoformat(),
        "pipeline_session": session_id,
    }))

    db.create_job(
        job_id=job_id,
        job_type="transcribe",
        config={},
        source_type="file",
        source_ref=session.get("filename"),
        source_title=session.get("filename"),
        input_file=audio_path.name,
    )
    from jobs import get_worker
    worker = get_worker()
    if worker:
        worker.enqueue(job_id)
    else:
        db.fail_job(job_id, "Job worker not available")

    with _lock:
        _pipeline_sessions[session_id]["transcription"] = job_id

    return {"job_id": job_id}


@app.delete("/api/pipeline/{session_id}")
async def delete_pipeline_session(session_id: str, _: bool = Depends(verify_auth)):
    """Delete a pipeline session and clean up all its audio files."""
    with _lock:
        session = _pipeline_sessions.pop(session_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail="Pipeline session not found")

    # Delete original and all step output files
    for name in [session["original_file"]] + [s["output_file"] for s in session.get("steps", [])]:
        (AUDIO_CACHE / name).unlink(missing_ok=True)

    return {"status": "ok"}


@app.get("/api/pipeline/{session_id}/download")
async def download_pipeline_audio(session_id: str, _: bool = Depends(verify_auth)):
    """Download the current (latest) processed audio from a pipeline session."""
    with _lock:
        session = _pipeline_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Pipeline session not found")

    audio_path = Path(session["current_file"])
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    stem   = _sanitize_filename(Path(session.get("filename") or "audio").stem)
    suffix = audio_path.suffix
    steps  = session.get("steps", [])
    label  = f"_pipeline_{len(steps)}steps" if steps else "_original"
    return FileResponse(
        audio_path,
        media_type="application/octet-stream",
        filename=f"{stem}{label}{suffix}",
    )


# ── YouTube Download Tool ──────────────────────────────────────────────────

_yt_download_jobs: dict[str, dict] = {}


class YouTubeDownloadRequest(BaseModel):
    url:           str
    mode:          str = "audio"   # "video" | "audio"
    video_quality: str = "best"    # "best" | "2160" | "1080" | "720" | "480" | "360"
    video_format:  str = "mp4"     # "mp4" | "webm" | "mkv"
    audio_format:  str = "mp3"     # "mp3" | "m4a" | "flac" | "wav" | "ogg" | "opus"
    audio_quality: str = "192"     # "128" | "192" | "256" | "320" | "best"


def _run_yt_download(job_id: str, req: YouTubeDownloadRequest) -> None:
    """Background task: download a YouTube video or audio file."""
    from extractors.youtube import download_video, download_audio, _VALID_VIDEO_FORMATS, _VALID_AUDIO_FORMATS, _VALID_VIDEO_QUALITIES

    def _status(detail: str) -> None:
        with _lock:
            _yt_download_jobs[job_id]["status_detail"] = detail

    tmpdir = Path(tempfile.mkdtemp())
    try:
        if req.mode == "video":
            fmt = req.video_format if req.video_format in _VALID_VIDEO_FORMATS else "mp4"
            quality = req.video_quality if req.video_quality in _VALID_VIDEO_QUALITIES else "best"
            _status(f"Downloading {quality}p {fmt.upper()} video…")
            output_path = download_video(req.url, tmpdir, quality=quality, fmt=fmt, cookies=_settings.get("youtube_cookies") or None)
        else:
            fmt = req.audio_format if req.audio_format in _VALID_AUDIO_FORMATS else "mp3"
            _status(f"Downloading {fmt.upper()} audio…")
            output_path = download_audio(req.url, tmpdir, fmt=fmt, quality=req.audio_quality, cookies=_settings.get("youtube_cookies") or None)

        # Move to stable cache location
        dest = AUDIO_CACHE / f"{job_id}_{output_path.name}"
        shutil.move(str(output_path), dest)

        with _lock:
            _yt_download_jobs[job_id]["status"]       = "done"
            _yt_download_jobs[job_id]["status_detail"] = ""
            _yt_download_jobs[job_id]["output_file"]   = str(dest)
            _yt_download_jobs[job_id]["filename"]      = output_path.name

    except Exception as exc:
        with _lock:
            _yt_download_jobs[job_id]["status"] = "error"
            _yt_download_jobs[job_id]["error"]  = str(exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.get("/api/youtube/info")
async def youtube_info(url: str = Query(...), _: bool = Depends(verify_auth)):
    """Fetch YouTube video metadata without downloading."""
    from extractors.youtube import get_video_info
    try:
        info = await asyncio.to_thread(get_video_info, url, _settings.get("youtube_cookies") or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return info


@app.post("/api/youtube/download")
async def youtube_download(
    req: YouTubeDownloadRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_auth),
):
    """Start a YouTube download job."""
    job_id = str(uuid.uuid4())
    with _lock:
        _yt_download_jobs[job_id] = {
            "status":        "pending",
            "status_detail": "",
            "output_file":   None,
            "filename":      None,
            "error":         None,
        }
    background_tasks.add_task(_run_yt_download, job_id, req)
    return {"job_id": job_id}


@app.get("/api/youtube/{job_id}")
async def youtube_job_status(job_id: str, _: bool = Depends(verify_auth)):
    """Poll the status of a YouTube download job."""
    with _lock:
        job = _yt_download_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Download job not found")
    return job


@app.get("/api/youtube/{job_id}/file")
async def youtube_download_file(job_id: str, _: bool = Depends(verify_auth)):
    """Download the completed file from a YouTube download job."""
    with _lock:
        job = _yt_download_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Download job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Download not complete")

    output_path = Path(job["output_file"])
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    filename = _sanitize_filename(job.get("filename") or output_path.name)
    return FileResponse(output_path, media_type="application/octet-stream", filename=filename)


# ── SPA catch-all — must be the last route registered ─────────────────────
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str, _: bool = Depends(verify_auth)):
    # Show loading/error page while the engine is initializing.
    if _engine_status != "ready":
        if _engine_status == "error":
            return HTMLResponse(_loading_page(_engine_message, is_error=True), status_code=500)
        return HTMLResponse(_loading_page(_engine_message))

    # Serve real static files (favicon, assets/, etc.) — protect against traversal.
    if full_path:
        candidate = (_STATIC_DIR / full_path).resolve()
        try:
            if candidate.is_relative_to(_STATIC_DIR.resolve()) and candidate.is_file():
                return FileResponse(candidate)
        except (OSError, ValueError):
            pass

    # All other paths → React SPA entry point.
    index = _STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)

    return HTMLResponse(
        "Frontend not built. Run: <code>cd frontend && npm install && npm run build</code>",
        status_code=503,
    )
