"""
LLM mode runner — the single path every summarize/extract mode goes through.

Used by both the streaming SSE endpoints and the background job handler so
the two can never drift apart again. Responsibilities:

  * Resolve a ``Runtime`` for the configured model: client, context window
    (per-model, defaulting to the model's own maximum), output budget, and
    capabilities (thinking / vision) discovered via ``/api/show``.
  * Build the prompt (source header + content) with safe templating.
  * Decide between a single pass and the long-form (map-reduce) path when the
    content would not fit the context window.
  * Stream typed events, validate structured (JSON) output, and run any
    mode-specific post-processing pipeline (e.g. MTG card resolution).

Events yielded by ``run_mode`` (plain dicts):
  {"type": "status",   "detail": str}
  {"type": "thinking", "text": str}
  {"type": "text",     "text": str}
  {"type": "reset"}                       — discard streamed text (retry)
  {"type": "warning",  "message": str}
  {"type": "result",   "text": str, "reasoning": str, "meta": dict}   — always last
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable

from .client import LLMEvent, OllamaClient, build_options
from .prompts import get_mode_meta, get_prompt, render_template

logger = logging.getLogger(__name__)

# Used when Ollama can't tell us the model's context length.
FALLBACK_CONTEXT = 32_768
DEFAULT_OUTPUT_BUDGET = 32_768
# Rough-but-conservative token estimate (transcripts tokenize denser than prose).
CHARS_PER_TOKEN = 3.5
# Tokens held back for chat templates, special tokens, and estimation error.
SAFETY_TOKENS = 512

_VISION_NAME_HINTS = (
    "llava", "bakllava", "moondream", "gemma3", "gemma4", "minicpm-v",
    "llama3.2-vision", "qwen2-vl", "qwen2.5-vl", "qwen2.5vl", "qwen3-vl",
)


class LLMConfigError(RuntimeError):
    """Raised when the LLM is not configured (no model selected, etc.)."""


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


# ── Model profiles ────────────────────────────────────────────────────────────

@dataclass
class ModelProfile:
    name: str
    context_length: int | None = None      # architecture maximum
    modelfile_num_ctx: int | None = None   # num_ctx set in the Modelfile, if any
    capabilities: set[str] = field(default_factory=set)
    parameter_size: str | None = None
    thinking_values: list = field(default_factory=list)

    @property
    def default_context(self) -> int | None:
        return self.modelfile_num_ctx or self.context_length


_PROFILE_TTL = 300.0
_profile_cache: dict[tuple[str, str], tuple[float, ModelProfile]] = {}


async def get_model_profile(client: OllamaClient, model: str) -> ModelProfile:
    """Fetch (and cache for a few minutes) a model's context length and capabilities."""
    key = (client.base_url, model)
    hit = _profile_cache.get(key)
    if hit and time.monotonic() - hit[0] < _PROFILE_TTL:
        return hit[1]
    info = await client.get_model_info(model)
    profile = ModelProfile(name=model)
    if info:
        profile.context_length = info.get("context_length")
        profile.modelfile_num_ctx = info.get("modelfile_num_ctx")
        profile.capabilities = set(info.get("capabilities") or [])
        profile.parameter_size = info.get("parameter_size")
        profile.thinking_values = list(info.get("thinking_values") or [])
        _profile_cache[key] = (time.monotonic(), profile)
    return profile


def clear_profile_cache() -> None:
    _profile_cache.clear()


# ── Runtime ───────────────────────────────────────────────────────────────────

@dataclass
class Runtime:
    client: OllamaClient
    model: str
    profile: ModelProfile
    num_ctx: int
    output_budget: int
    thinking_enabled: bool
    vision_override: bool | None = None

    @property
    def input_budget(self) -> int:
        """Tokens available for system prompt + user prompt in one pass."""
        return max(1024, self.num_ctx - self.output_budget - SAFETY_TOKENS)

    @property
    def supports_thinking(self) -> bool:
        return "thinking" in self.profile.capabilities

    @property
    def supports_vision(self) -> bool:
        if self.vision_override is not None:
            return self.vision_override
        if self.profile.capabilities:
            return "vision" in self.profile.capabilities
        return self.model.lower().startswith(_VISION_NAME_HINTS)

    def think_param(self, mode_think: bool | None = None) -> bool | str | None:
        """Value for Ollama's ``think`` field, or None to omit it.

        Only sent to models that advertise the ``thinking`` capability —
        Ollama rejects ``think`` for models that don't support it. Models with
        named levels (gpt-oss: low/medium/high) can't switch thinking off, so
        "off" maps to their lowest level and "on" to the model default.
        """
        if not self.supports_thinking:
            return None
        want = self.thinking_enabled if mode_think is None else mode_think
        levels = [v for v in self.profile.thinking_values if isinstance(v, str)]
        if levels:
            return None if want else levels[0]
        return bool(want)

    def options(self, temperature: float | None = None, num_predict: int | None = None) -> dict:
        return build_options(
            num_ctx=self.num_ctx,
            num_predict=num_predict or self.output_budget,
            temperature=temperature,
        )


def _parse_int(value, default: int | None = None) -> int | None:
    try:
        v = int(str(value).strip())
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _context_overrides(settings: dict) -> dict[str, int]:
    raw = settings.get("ollama_context_overrides") or "{}"
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return {k: int(v) for k, v in data.items() if _parse_int(v)}


def resolve_num_ctx(settings: dict, model: str, profile: ModelProfile) -> int:
    """Per-model override → Modelfile num_ctx → model's max → fallback; then the optional global cap."""
    ctx = _context_overrides(settings).get(model) or profile.default_context or FALLBACK_CONTEXT
    cap = _parse_int(settings.get("ollama_context_cap"))
    if cap:
        ctx = min(ctx, cap)
    return int(ctx)


async def resolve_runtime(settings: dict | None = None, model_override: str | None = None) -> Runtime:
    if settings is None:
        import db
        settings = db.get_all_settings()

    model = (model_override or settings.get("ollama_model") or "").strip()
    if not model:
        raise LLMConfigError("No Ollama model configured — go to Settings → Ollama to select one.")

    client = OllamaClient(
        base_url=settings.get("ollama_url", "http://localhost:11434"),
        timeout=float(settings.get("ollama_timeout", "120") or 120),
    )
    profile = await get_model_profile(client, model)
    num_ctx = resolve_num_ctx(settings, model, profile)

    output_budget = _parse_int(settings.get("ollama_output_budget"), DEFAULT_OUTPUT_BUDGET)
    # Never let the output reservation swallow more than half the window.
    output_budget = max(1024, min(output_budget, num_ctx // 2))

    vision_override = True if settings.get("ollama_vision_override", "false") == "true" else None

    return Runtime(
        client=client,
        model=model,
        profile=profile,
        num_ctx=num_ctx,
        output_budget=output_budget,
        thinking_enabled=settings.get("ollama_thinking_enabled", "true") == "true",
        vision_override=vision_override,
    )


# ── Source header ─────────────────────────────────────────────────────────────

def _fmt_duration(seconds) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_source_header(meta: dict | None, description_limit: int = 6000) -> str:
    """Standard "Source information" block prepended to the content.

    Recognised keys: title, uploader, duration (seconds), upload_date (YYYYMMDD
    or ISO), url, chapters ([{start_time, title}]), description.
    """
    if not meta:
        return ""
    lines: list[str] = []
    if meta.get("title"):
        lines.append(f"Title: {meta['title']}")
    if meta.get("uploader"):
        lines.append(f"Channel/author: {meta['uploader']}")
    if meta.get("duration"):
        d = _fmt_duration(meta["duration"])
        if d:
            lines.append(f"Duration: {d}")
    date = str(meta.get("upload_date") or "")
    if re.fullmatch(r"\d{8}", date):
        date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    if date:
        lines.append(f"Published: {date}")
    if meta.get("url"):
        lines.append(f"URL: {meta['url']}")
    chapters = meta.get("chapters") or []
    if chapters:
        lines.append("Chapters:")
        for ch in chapters:
            lines.append(f"  [{_fmt_duration(ch.get('start_time', 0))}] {ch.get('title', '').strip()}")
    desc = (meta.get("description") or "").strip()
    if desc:
        if len(desc) > description_limit:
            desc = desc[:description_limit].rstrip() + " …"
        lines.append("Description:")
        lines.append(desc)
    if not lines:
        return ""
    return "## Source information\n" + "\n".join(lines) + "\n\n## Content\n"


def compose_document(header: str, content: str) -> str:
    return f"{header}{content}" if header else content


# ── JSON helpers ──────────────────────────────────────────────────────────────

def extract_json_text(text: str) -> str:
    """Pull a JSON object/array out of an LLM response (code fences, prose)."""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        return text.strip()
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]")) + 1
    return text[start:end] if end > start else text.strip()


def parse_json_result(text: str):
    """Parse LLM JSON output; returns the object or None."""
    try:
        return json.loads(extract_json_text(text))
    except (TypeError, ValueError):
        return None


# ── Mode pipelines (post-processing) ──────────────────────────────────────────

@dataclass
class ModeContext:
    mode: str
    content: str
    header: str
    source_meta: dict
    runtime: Runtime
    images: list[str] | None = None
    options: dict | None = None   # mode-specific inputs (e.g. a pasted decklist)


# mode → async generator(ctx) yielding events (must end with a "result" event)
ModePipeline = Callable[[ModeContext], AsyncIterator[dict]]
MODE_PIPELINES: dict[str, ModePipeline] = {}


def _load_pipelines() -> None:
    """Import modules that register mode pipelines (lazy, avoids import cycles)."""
    import mtg.pipeline  # noqa: F401  (registers "mtg_precon")


def register_pipeline(mode: str):
    def deco(fn: ModePipeline) -> ModePipeline:
        MODE_PIPELINES[mode] = fn
        return fn
    return deco


# ── Single pass ───────────────────────────────────────────────────────────────

async def stream_pass(
    rt: Runtime,
    *,
    system: str,
    prompt: str,
    temperature: float | None,
    think: bool | None,
    format: dict | str | None = None,
    images: list[str] | None = None,
    num_predict: int | None = None,
    forward_text: bool = True,
    forward_thinking: bool = True,
) -> AsyncIterator[dict]:
    """One LLM call. Yields thinking/text events (as requested) and warnings,
    then a final {"type": "pass_done", "text", "reasoning", "stats"}."""
    text_parts: list[str] = []
    think_parts: list[str] = []
    stats: dict = {}
    async for ev in rt.client.generate_stream(
        prompt, rt.model, system,
        images=images,
        think=think,
        options=rt.options(temperature, num_predict),
        format=format,
    ):
        if ev.kind == "text":
            text_parts.append(ev.text)
            if forward_text:
                yield {"type": "text", "text": ev.text}
        elif ev.kind == "thinking":
            think_parts.append(ev.text)
            if forward_thinking:
                yield {"type": "thinking", "text": ev.text}
        elif ev.kind == "done":
            stats = ev.stats

    for warning in truncation_warnings(rt, stats):
        yield {"type": "warning", "message": warning}

    yield {"type": "pass_done", "text": "".join(text_parts), "reasoning": "".join(think_parts), "stats": stats}


def truncation_warnings(rt: Runtime, stats: dict) -> list[str]:
    out: list[str] = []
    if stats.get("done_reason") == "length":
        out.append(
            f"The response hit the output limit ({rt.output_budget:,} tokens) and may be cut off. "
            "Raise the output budget in Settings → Ollama."
        )
    pe = stats.get("prompt_eval_count")
    if pe and pe >= rt.num_ctx - 16:
        out.append(
            f"The input filled the whole context window ({rt.num_ctx:,} tokens), so Ollama may have dropped part of it."
        )
    return out


# ── Public entry point ────────────────────────────────────────────────────────

async def run_mode(
    content: str,
    mode: str,
    rt: Runtime,
    *,
    header: str = "",
    source_meta: dict | None = None,
    images: list[str] | None = None,
    options: dict | None = None,
) -> AsyncIterator[dict]:
    """Run a summarize/extract mode end to end. See module docstring for events."""
    _load_pipelines()
    ctx = ModeContext(
        mode=mode, content=content, header=header,
        source_meta=source_meta or {}, runtime=rt, images=images, options=options,
    )
    pipeline = MODE_PIPELINES.get(mode, default_pipeline)
    async for ev in pipeline(ctx):
        yield ev


async def default_pipeline(ctx: ModeContext) -> AsyncIterator[dict]:
    """Prompt → (single pass | long-form) → JSON validation → result."""
    async for ev in generate_for_mode(ctx):
        yield ev


async def generate_for_mode(
    ctx: ModeContext,
    *,
    mode: str | None = None,
    forward_text: bool = True,
) -> AsyncIterator[dict]:
    """Core generation for a mode, reusable by custom pipelines.

    Ends with {"type": "result", ...}. For JSON modes the result text is the
    validated, pretty-printed JSON and meta["data"] holds the parsed object.
    """
    from . import longform

    mode = mode or ctx.mode
    rt = ctx.runtime
    prompt_data = get_prompt(mode)
    meta = get_mode_meta(mode)
    system = prompt_data.get("system") or ""
    template = prompt_data.get("template") or "{content}"
    think = rt.think_param(meta["think"])
    schema = meta["format"]

    document = compose_document(ctx.header, ctx.content)
    prompt = render_template(template, document)
    needed = estimate_tokens(system) + estimate_tokens(prompt)

    result_meta: dict = {
        "mode": mode,
        "model": rt.model,
        "num_ctx": rt.num_ctx,
        "output_type": meta["output_type"],
        "est_input_tokens": needed,
    }

    if not ctx.images and needed > rt.input_budget:
        result_meta["longform"] = True
        async for ev in longform.run_longform(
            rt=rt, mode=mode, system=system, template=template, meta=meta,
            header=ctx.header, body=ctx.content, think=think,
            forward_text=forward_text,
        ):
            if ev["type"] == "result":
                ev["meta"] = {**result_meta, **ev.get("meta", {})}
            yield ev
        return

    if ctx.images:
        yield {"type": "status", "detail": f"Analyzing {len(ctx.images)} image(s) with {rt.model}…"}

    final_text, reasoning = "", ""
    async for ev in stream_pass(
        rt, system=system, prompt=prompt, temperature=meta["temperature"],
        think=think, format=schema, images=ctx.images,
        # Structured modes don't stream raw JSON, but still surface reasoning.
        forward_text=forward_text and not schema,
        forward_thinking=forward_text,
    ):
        if ev["type"] == "pass_done":
            final_text, reasoning = ev["text"], ev["reasoning"]
            result_meta["stats"] = ev["stats"]
        else:
            yield ev

    if schema:
        data = parse_json_result(final_text)
        if data is None and think:
            # Some model/Ollama combinations ignore `format` while thinking.
            yield {"type": "status", "detail": "Output wasn't valid JSON — retrying with strict structured output…"}
            async for ev in stream_pass(
                rt, system=system, prompt=prompt, temperature=meta["temperature"],
                think=False, format=schema, images=ctx.images,
                forward_text=False, forward_thinking=False,
            ):
                if ev["type"] == "pass_done":
                    final_text = ev["text"]
                    result_meta["stats"] = ev["stats"]
                elif ev["type"] == "warning":
                    yield ev
            data = parse_json_result(final_text)
        if data is None:
            yield {"type": "warning", "message": "The model did not return valid JSON; showing raw output."}
        else:
            final_text = json.dumps(data, indent=2, ensure_ascii=False)
            result_meta["data"] = data

    yield {"type": "result", "text": final_text, "reasoning": reasoning, "meta": result_meta}


async def collect(events: AsyncIterator[dict], on_event: Callable[[dict], Awaitable[None]] | None = None) -> dict:
    """Drain an event stream, returning the final result event."""
    result: dict = {"type": "result", "text": "", "reasoning": "", "meta": {}}
    async for ev in events:
        if ev["type"] == "result":
            result = ev
        if on_event is not None:
            await on_event(ev)
    return result
