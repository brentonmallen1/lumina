"""
LLM endpoints: summarize (text / file / URL / image), chat, translate, and
recipe JSON-LD conversion.

Every endpoint is a thin SSE wrapper over ``llm.runner`` so context sizing,
thinking, budgets, and JSON validation behave identically to the job queue.
Auth is applied at include time (see main.py: ``include_router(...,
dependencies=[Depends(verify_auth)])``).

SSE events (``data: {...}``):
  {"phase": str, "detail": str}     progress (extracting | transcribing | thinking)
  {"reasoning": str}                model reasoning chunk (native Ollama thinking)
  {"text": str}                     answer chunk
  {"reset": true}                   discard streamed text (structured-output retry)
  {"warning": str}                  non-fatal problem (truncation, invalid JSON…)
  {"extracted_content": str}        full source text, for chat
  {"result": str, "meta": {...}}    authoritative final result
  {"error": str}                    terminal error
  [DONE]
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

import db
from llm.context import budget_chars, build_system_prompt, chat_output_tokens, prepare_messages
from llm.prompts import RECIPE_JSONLD_PROMPT, RECIPE_JSONLD_SCHEMA
from llm.runner import (
    LLMConfigError,
    build_source_header,
    compose_document,
    parse_json_result,
    resolve_runtime,
    run_mode,
    stream_pass,
)

router = APIRouter(prefix="/api")

SSE_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Keep the final "result" meta small; the UI only needs a few fields.
_RESULT_META_KEYS = ("mode", "model", "num_ctx", "output_type", "longform", "parts", "stats")


def sse(payload: dict | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload)}\n\n"


def sse_response(gen: AsyncIterator[str], cleanup: Path | None = None) -> StreamingResponse:
    background = BackgroundTask(cleanup.unlink, missing_ok=True) if cleanup else None
    return StreamingResponse(gen, media_type="text/event-stream", headers=SSE_HEADERS, background=background)


async def events_to_sse(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    """Map runner events to the SSE protocol above (without the trailing [DONE])."""
    async for ev in events:
        kind = ev["type"]
        if kind == "text":
            yield sse({"text": ev["text"]})
        elif kind == "thinking":
            yield sse({"reasoning": ev["text"]})
        elif kind == "status":
            yield sse({"phase": "thinking", "detail": ev["detail"]})
        elif kind == "warning":
            yield sse({"warning": ev["message"]})
        elif kind == "reset":
            yield sse({"reset": True})
        elif kind == "result":
            meta = {k: v for k, v in (ev.get("meta") or {}).items() if k in _RESULT_META_KEYS}
            yield sse({"result": ev["text"], "meta": meta})


async def _mode_stream(content: str, mode: str, model: str | None, *, header: str = "",
                       source_meta: dict | None = None, images: list[str] | None = None,
                       extracted: str | None = None, options: dict | None = None) -> AsyncIterator[str]:
    try:
        rt = await resolve_runtime(model_override=model)
    except LLMConfigError as exc:
        yield sse({"error": str(exc)})
        yield sse("[DONE]")
        return

    if extracted is not None:
        yield sse({"extracted_content": extracted})

    if mode == "transcript":
        yield sse({"text": extracted if extracted is not None else content})
        yield sse("[DONE]")
        return

    yield sse({"phase": "thinking", "detail": f"Processing with {mode} mode…"})
    try:
        async for line in events_to_sse(run_mode(
            content, mode, rt, header=header, source_meta=source_meta, images=images, options=options,
        )):
            yield line
    except Exception as exc:
        yield sse({"error": str(exc) or repr(exc)})
    yield sse("[DONE]")


async def _with_extraction(extract_coro_fn, mode: str, model: str | None,
                           options: dict | None = None) -> AsyncIterator[str]:
    """Run an extraction (forwarding its status as SSE phases), then the mode.

    ``extract_coro_fn(on_status)`` must return ``(content, source_meta)``.
    The extraction task is cancelled if the client disconnects.
    """
    q: asyncio.Queue = asyncio.Queue()

    async def on_status(phase: str, detail: str) -> None:
        q.put_nowait({"phase": phase, "detail": detail})

    task = asyncio.create_task(extract_coro_fn(on_status))
    task.add_done_callback(lambda _t: q.put_nowait(None))
    try:
        while True:
            item = await q.get()
            if item is None:
                break
            yield sse(item)
        try:
            content, source_meta = task.result()
        except Exception as exc:
            yield sse({"error": f"Extraction failed: {exc}"})
            yield sse("[DONE]")
            return
    finally:
        if not task.done():
            task.cancel()

    header = build_source_header(source_meta)
    async for line in _mode_stream(
        content, mode, model, header=header, source_meta=source_meta,
        extracted=compose_document(header, content), options=options,
    ):
        yield line


def _max_upload_bytes() -> int:
    try:
        return int(db.get_setting("max_upload_size_mb", "500")) * 1024 * 1024
    except ValueError:
        return 500 * 1024 * 1024


async def _save_upload(file: UploadFile, suffix: str) -> Path:
    """Stream an upload to a temp file, enforcing the configured size limit."""
    limit = _max_upload_bytes()
    size = 0
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        path = Path(tmp.name)
        try:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=f"File exceeds the {limit // (1024 * 1024)} MB upload limit")
                tmp.write(chunk)
        except BaseException:
            tmp.close()
            path.unlink(missing_ok=True)
            raise
    return path


# ── Summarize: plain text ─────────────────────────────────────────────────────

class SummarizeRequest(BaseModel):
    content: str
    mode: str = "summary"
    model: str | None = None
    title: str | None = None
    options: dict | None = None     # mode-specific inputs, e.g. {"decklist": "..."}


@router.post("/summarize")
async def summarize_content(req: SummarizeRequest):
    header = build_source_header({"title": req.title}) if req.title else ""
    return sse_response(_mode_stream(req.content, req.mode, req.model, header=header, options=req.options))


# ── Summarize: uploaded file (audio / video / PDF) ────────────────────────────

@router.post("/summarize/file")
async def summarize_file(
    source:            str        = Form(...),         # "audio" | "pdf"
    mode:              str        = Form("summary"),
    file:              UploadFile = File(...),
    enhance_normalize: bool       = Form(False),
    enhance_denoise:   bool       = Form(False),
    enhance_isolate:   bool       = Form(False),
    enhance_separate:  bool       = Form(False),
    enhance_upsample:  bool       = Form(False),
):
    from audio import AudioPipeline, EnhancementOptions

    if source not in ("audio", "pdf"):
        raise HTTPException(status_code=400, detail=f"Unknown source type: {source}")

    filename = Path(file.filename or "upload")
    suffix = filename.suffix.lower()
    title = filename.stem or None
    tmp = await _save_upload(file, suffix)

    opts = EnhancementOptions(
        normalize=enhance_normalize, denoise=enhance_denoise, isolate=enhance_isolate,
        separate=enhance_separate, upsample=enhance_upsample,
    )

    async def stream():
        try:
            if source == "pdf":
                from extractors.pdf import PDFExtractor
                try:
                    rt = await resolve_runtime()
                except LLMConfigError as exc:
                    yield sse({"error": str(exc)})
                    yield sse("[DONE]")
                    return
                if rt.supports_vision:
                    yield sse({"phase": "extracting", "detail": "Rendering PDF pages for vision model…"})
                    async def _noop(_p, _d): return None
                    try:
                        images = await PDFExtractor().extract_images(tmp, _noop)
                    except Exception as exc:
                        images = []
                        yield sse({"warning": f"Could not render PDF pages ({exc}); using text extraction."})
                    if images:
                        # Also extract text (best effort) so chat has something to work with.
                        try:
                            text = await PDFExtractor().extract(tmp, _noop)
                        except Exception:
                            text = None
                        header = build_source_header({"title": title})
                        async for line in _mode_stream(
                            f"[PDF with {len(images)} page(s) attached as images]", mode, None,
                            header=header, images=images,
                            extracted=compose_document(header, text) if text else None,
                        ):
                            yield line
                        return

                async def extract_pdf(on_status):
                    return await PDFExtractor().extract(tmp, on_status), {"title": title}

                async for line in _with_extraction(extract_pdf, mode, None):
                    yield line
                return

            from extractors.audio import AudioExtractor
            from extractors.video import VideoExtractor
            from transcriber import get_engine

            async def extract_audio(on_status):
                engine = await asyncio.to_thread(get_engine)
                pipeline = AudioPipeline() if opts.any_active else None
                cls = VideoExtractor if suffix in VIDEO_EXTENSIONS else AudioExtractor
                text = await cls(engine=engine, pipeline=pipeline, options=opts).extract(tmp, on_status)
                return text, {"title": title}

            async for line in _with_extraction(extract_audio, mode, None):
                yield line
        finally:
            tmp.unlink(missing_ok=True)

    return sse_response(stream(), cleanup=tmp)


# ── Summarize: URL (YouTube / webpage) ────────────────────────────────────────

class SummarizeUrlRequest(BaseModel):
    source: str             # "youtube" | "url"
    url: str
    mode: str = "summary"
    model: str | None = None
    prefer_captions: bool = True
    refresh: bool = False
    options: dict | None = None


@router.post("/summarize/url")
async def summarize_url(req: SummarizeUrlRequest):
    from sources import extract_source

    if req.source not in ("youtube", "url"):
        raise HTTPException(status_code=400, detail=f"Unknown source type: {req.source}")

    async def extract(on_status):
        return await extract_source(
            req.source, req.url,
            config={"prefer_captions": req.prefer_captions, "refresh": req.refresh},
            on_status=on_status,
        )

    return sse_response(_with_extraction(extract, req.mode, req.model, req.options))


# ── Summarize: image (vision LLM) ─────────────────────────────────────────────

@router.post("/summarize/image")
async def summarize_image(mode: str = Form("summary"), file: UploadFile = File(...)):
    import base64

    suffix = Path(file.filename or "image").suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {suffix}. Allowed: jpg, jpeg, png, webp, gif",
        )
    tmp = await _save_upload(file, suffix)

    async def stream():
        try:
            b64 = base64.b64encode(tmp.read_bytes()).decode()
        finally:
            tmp.unlink(missing_ok=True)
        async for line in _mode_stream("the provided image", mode, None, images=[b64]):
            yield line

    return sse_response(stream(), cleanup=tmp)


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    content:  str                  # source document text to chat about
    messages: list[dict]           # conversation history: [{role, content}, ...]
    model:    str | None = None


@router.post("/chat")
async def chat_endpoint(req: ChatRequest):
    async def stream():
        try:
            rt = await resolve_runtime(model_override=req.model)
        except LLMConfigError as exc:
            yield sse({"error": str(exc)})
            yield sse("[DONE]")
            return

        system_prompt, was_truncated = build_system_prompt(req.content, int(budget_chars(rt) * 0.85))
        if was_truncated:
            yield sse({"notice": "The source is larger than this model's context window, so only the first part is included."})

        try:
            messages, notice = await prepare_messages(system_prompt, req.messages, rt)
        except Exception as exc:
            yield sse({"error": f"Context preparation failed: {exc}"})
            yield sse("[DONE]")
            return
        if notice:
            yield sse({"notice": notice})

        try:
            async for ev in rt.client.chat_stream(
                messages, rt.model,
                think=rt.think_param(None),
                options=rt.options(0.6, chat_output_tokens(rt)),
            ):
                if ev.kind == "text":
                    yield sse({"text": ev.text})
                elif ev.kind == "thinking":
                    yield sse({"reasoning": ev.text})
        except Exception as exc:
            yield sse({"error": str(exc)})
        yield sse("[DONE]")

    return sse_response(stream())


# ── Translate ─────────────────────────────────────────────────────────────────

class TranslateRequest(BaseModel):
    text:            str
    target_language: str
    source_language: str = "auto"


@router.post("/translate")
async def translate_text(req: TranslateRequest):
    async def stream():
        try:
            rt = await resolve_runtime()
        except LLMConfigError as exc:
            yield sse({"error": str(exc)})
            yield sse("[DONE]")
            return
        src = "" if req.source_language == "auto" else f" from {req.source_language}"
        prompt = (
            f"Translate the following text{src} to {req.target_language}.\n"
            "Output ONLY the translation — no explanations, no introductory phrases. "
            "Preserve markdown formatting.\n\n"
            f"{req.text}"
        )
        try:
            async for ev in stream_pass(
                rt, system="You are a professional translator. Provide accurate, natural translations.",
                prompt=prompt, temperature=0.3, think=rt.think_param(False),
                forward_thinking=False,
            ):
                if ev["type"] == "text":
                    yield sse({"text": ev["text"]})
                elif ev["type"] == "warning":
                    yield sse({"warning": ev["message"]})
        except Exception as exc:
            yield sse({"error": str(exc)})
        yield sse("[DONE]")

    return sse_response(stream())


# ── Recipe JSON-LD export ─────────────────────────────────────────────────────

class RecipeJsonLDRequest(BaseModel):
    recipe_markdown: str
    source_url: str | None = None   # added as the recipe's url
    image: str | None = None        # e.g. the video thumbnail


@router.post("/recipe/jsonld")
async def convert_recipe_to_jsonld(req: RecipeJsonLDRequest):
    """Recipe Markdown → normalized schema.org/Recipe JSON-LD.

    Lumina's own Recipe Markdown is parsed in code; other Markdown falls back
    to the LLM. The ``X-Converted-By`` header says which (code | llm).
    """
    from fastapi.responses import JSONResponse
    from recipes.convert import ConversionError, markdown_to_recipe

    try:
        recipe, method = await markdown_to_recipe(req.recipe_markdown, req.source_url, req.image)
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return JSONResponse(recipe, headers={"X-Converted-By": method})


class RecipeMarkdownRequest(BaseModel):
    recipe: dict | str


@router.post("/recipe/markdown")
async def convert_recipe_to_markdown(req: RecipeMarkdownRequest):
    """schema.org/Recipe JSON-LD → Markdown (in code, instant)."""
    from recipes.markdown import to_markdown

    data = req.recipe
    if isinstance(data, str):
        data = parse_json_result(data)
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="That isn't valid recipe JSON.")
    return {"markdown": to_markdown(data)}
