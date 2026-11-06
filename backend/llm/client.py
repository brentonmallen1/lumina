"""
Ollama HTTP client.

Thin async wrapper around the Ollama REST API. Model-agnostic: thinking is
requested through Ollama's native top-level ``think`` parameter (Ollama
returns the reasoning in a separate ``thinking`` field), so no model-specific
prompt tokens are injected.

Key Ollama endpoints:
  GET  /             — health check ("Ollama is running")
  GET  /api/tags     — list installed models
  POST /api/show     — model details (context length, capabilities)
  POST /api/generate — single-turn completion
  POST /api/chat     — multi-turn chat

Streaming methods yield ``LLMEvent`` objects:
  kind="thinking"  text = reasoning chunk
  kind="text"      text = answer chunk
  kind="done"      stats = {prompt_eval_count, eval_count, done_reason, ...}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx


@dataclass
class LLMEvent:
    kind: str                      # "thinking" | "text" | "done"
    text: str = ""
    stats: dict = field(default_factory=dict)


# Sampling defaults (gemma-family recommendations). Callers override temperature per mode.
DEFAULT_SAMPLING = {"top_p": 0.95, "top_k": 64}


def build_options(
    *,
    num_ctx: int | None = None,
    num_predict: int | None = None,
    temperature: float | None = None,
) -> dict:
    """Build an Ollama ``options`` dict containing only valid Ollama options."""
    options: dict = dict(DEFAULT_SAMPLING)
    options["temperature"] = 1.0 if temperature is None else temperature
    if num_ctx:
        options["num_ctx"] = int(num_ctx)
    if num_predict:
        options["num_predict"] = int(num_predict)
    return options


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── Connection ─────────────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """Return {"ok": bool, "message": str}."""
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{self.base_url}/")
                r.raise_for_status()
                return {"ok": True, "message": "Connected"}
        except httpx.ConnectError:
            return {"ok": False, "message": f"Connection refused — is Ollama running at {self.base_url}?"}
        except httpx.TimeoutException:
            return {"ok": False, "message": "Request timed out"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    # ── Models ─────────────────────────────────────────────────────────────────

    async def list_models(self) -> list[dict]:
        """Return [{name, size, parameter_size}] or [] if Ollama is unreachable."""
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                data = r.json()
        except Exception:
            return []

        return [
            {
                "name":           m.get("name", ""),
                "size":           m.get("size", 0),
                "parameter_size": (m.get("details") or {}).get("parameter_size", ""),
            }
            for m in data.get("models", [])
        ]

    async def show(self, model: str) -> dict | None:
        """Raw /api/show payload, or None if unavailable."""
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(f"{self.base_url}/api/show", json={"model": model})
                r.raise_for_status()
                return r.json()
        except Exception:
            return None

    async def get_model_info(self, model: str) -> dict | None:
        """Return {context_length, parameter_size, capabilities} or None."""
        data = await self.show(model)
        if data is None:
            return None
        return parse_model_info(data)

    # ── Generation ─────────────────────────────────────────────────────────────

    async def generate_stream(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
        *,
        images: list[str] | None = None,
        think: bool | str | None = None,
        options: dict | None = None,
        format: dict | str | None = None,
    ) -> AsyncIterator[LLMEvent]:
        """Streaming /api/generate. Yields LLMEvent (thinking/text/done)."""
        payload: dict = {
            "model":   model,
            "prompt":  prompt,
            "stream":  True,
            "options": options or build_options(),
        }
        if system:
            payload["system"] = system
        if images:
            payload["images"] = images
        if think is not None:
            payload["think"] = think
        if format is not None:
            payload["format"] = format

        async for event in self._stream("/api/generate", payload, chat=False):
            yield event

    async def chat_stream(
        self,
        messages: list[dict],
        model: str,
        *,
        think: bool | str | None = None,
        options: dict | None = None,
        format: dict | str | None = None,
    ) -> AsyncIterator[LLMEvent]:
        """Streaming /api/chat. Yields LLMEvent (thinking/text/done)."""
        payload: dict = {
            "model":    model,
            "messages": messages,
            "stream":   True,
            "options":  options or build_options(),
        }
        if think is not None:
            payload["think"] = think
        if format is not None:
            payload["format"] = format

        async for event in self._stream("/api/chat", payload, chat=True):
            yield event

    async def generate(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
        *,
        images: list[str] | None = None,
        think: bool | str | None = None,
        options: dict | None = None,
        format: dict | str | None = None,
    ) -> str:
        """Collect a full /api/generate answer (reasoning is discarded)."""
        parts: list[str] = []
        async for ev in self.generate_stream(
            prompt, model, system, images=images, think=think, options=options, format=format
        ):
            if ev.kind == "text":
                parts.append(ev.text)
        return "".join(parts)

    async def _stream(self, path: str, payload: dict, *, chat: bool) -> AsyncIterator[LLMEvent]:
        # Read timeout applies between chunks, so long generations are fine as
        # long as tokens keep arriving; connect is bounded separately.
        timeout = httpx.Timeout(connect=10.0, read=max(self.timeout, 30.0), write=60.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{self.base_url}{path}", json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(_ollama_error(response.status_code, body))
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise RuntimeError(f"Ollama error: {chunk['error']}")
                    src = chunk.get("message", {}) if chat else chunk
                    thinking = src.get("thinking") or ""
                    text = src.get("content", "") if chat else src.get("response", "")
                    if thinking:
                        yield LLMEvent("thinking", thinking)
                    if text:
                        yield LLMEvent("text", text)
                    if chunk.get("done"):
                        yield LLMEvent("done", stats={
                            k: chunk.get(k)
                            for k in ("done_reason", "prompt_eval_count", "eval_count",
                                      "total_duration", "eval_duration")
                            if k in chunk
                        })
                        break


# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_model_info(data: dict) -> dict:
    """Extract the fields Lumina cares about from an /api/show payload."""
    model_info = data.get("model_info") or {}
    ctx_key = next((k for k in model_info if k.endswith("context_length")), None)
    ctx = model_info.get(ctx_key) if ctx_key else None
    thinking = data.get("thinking") or {}
    return {
        "context_length":  int(ctx) if ctx else None,
        # num_ctx baked into the Modelfile (e.g. a "-128k" variant) — the
        # model author's intended default, which may be below the architecture max.
        "modelfile_num_ctx": _modelfile_param(data.get("parameters") or "", "num_ctx"),
        "parameter_size":  (data.get("details") or {}).get("parameter_size"),
        "capabilities":    list(data.get("capabilities") or []),
        # e.g. [False, True] for gemma4, ["low", "medium", "high"] for gpt-oss
        "thinking_values": list(thinking.get("values") or []),
    }


def _modelfile_param(parameters: str, name: str) -> int | None:
    for line in parameters.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == name:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def _ollama_error(status: int, body: str) -> str:
    try:
        msg = json.loads(body).get("error") or body
    except Exception:
        msg = body
    return f"Ollama returned {status}: {msg.strip()[:500]}"
