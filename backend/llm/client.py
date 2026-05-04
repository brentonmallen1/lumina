"""
Ollama HTTP client.

Wraps the Ollama REST API with async methods. Designed around gemma4 but
works with any model served by Ollama.

Key Ollama endpoints:
  GET  /             — health check ("Ollama is running")
  GET  /api/tags     — list installed models
  POST /api/generate — text completion (streaming or non-streaming)
  POST /api/chat     — multi-turn chat (streaming or non-streaming)

gemma4 notes:
  - Thinking mode: prepend <|think|> to the system prompt to enable chain-of-thought
  - Recommended sampling: temperature=1.0, top_p=0.95, top_k=64
  - Context windows: 128K (E2B/E4B variants), 256K (26B/31B variants)
  - Visual token budgets: 70, 140, 280, 560, 1120 (for image/document processing)
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 120.0):
        # Strip trailing slash so we can always do base_url + "/path"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── Connection ─────────────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """
        Verify that Ollama is reachable.
        Returns {"ok": True, "message": "Connected"} or {"ok": False, "message": "<error>"}.
        """
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
        """
        Fetch the list of locally installed models from Ollama.
        Returns a list of dicts: {name, size, parameter_size}.
        Returns an empty list if Ollama is unreachable.
        """
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                data = r.json()
        except Exception:
            return []

        models = []
        for m in data.get("models", []):
            details = m.get("details", {})
            models.append({
                "name":           m.get("name", ""),
                "size":           m.get("size", 0),
                "parameter_size": details.get("parameter_size", ""),
            })
        return models

    async def get_model_info(self, model: str) -> dict | None:
        """
        Fetch detailed model info including context_length via /api/show.
        Returns {context_length, parameter_size} or None if unavailable.
        """
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(f"{self.base_url}/api/show", json={"name": model})
                r.raise_for_status()
                data = r.json()
                model_info = data.get("model_info", {})
                ctx_key = next((k for k in model_info if "context_length" in k), None)
                return {
                    "context_length": model_info.get(ctx_key) if ctx_key else None,
                    "parameter_size": data.get("details", {}).get("parameter_size"),
                }
        except Exception:
            return None

    # ── Generation ─────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
        images: list[str] | None = None,
        thinking_enabled: bool = True,
        token_budget: int = 280,
        num_ctx: int | None = None,
    ) -> str:
        """
        Non-streaming text completion.

        For gemma4:
          - thinking_enabled=True prepends <|think|> to the system prompt so the
            model shows its reasoning before the final answer.
          - token_budget controls visual token allocation (70/140/280/560/1120)
            for image/document tasks; included in options for future multimodal use.
          - images: optional list of base64-encoded image strings for vision models.

        Returns the generated response text.
        """
        system_prompt = _build_system_prompt(system, thinking_enabled)
        options = _build_options(token_budget=token_budget, num_ctx=num_ctx)

        payload: dict = {
            "model":  model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if system_prompt is not None:
            payload["system"] = system_prompt
        if images:
            payload["images"] = images

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}/api/generate", json=payload)
            r.raise_for_status()
            return r.json().get("response", "")

    async def generate_stream(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
        images: list[str] | None = None,
        thinking_enabled: bool = True,
        token_budget: int = 280,
        num_ctx: int | None = None,
    ) -> AsyncIterator[str]:
        """
        Streaming text completion — yields response text chunks as they arrive.
        The final (done=True) chunk is not yielded.

        images: optional list of base64-encoded image strings for vision models.
        """
        system_prompt = _build_system_prompt(system, thinking_enabled)
        options = _build_options(token_budget=token_budget, num_ctx=num_ctx)

        payload: dict = {
            "model":  model,
            "prompt": prompt,
            "stream": True,
            "options": options,
        }
        if system_prompt is not None:
            payload["system"] = system_prompt
        if images:
            payload["images"] = images

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    text = chunk.get("response", "")
                    if text:
                        yield text
                    if chunk.get("done"):
                        break


    # ── Chat ───────────────────────────────────────────────────────────────────

    async def chat_stream(
        self,
        messages: list[dict],
        model: str,
        num_ctx: int | None = None,
    ) -> AsyncIterator[str]:
        """
        Multi-turn streaming chat via /api/chat.

        `messages` is a list of {"role": "system"|"user"|"assistant", "content": "..."}.
        Yields response text chunks as they arrive.
        """
        payload = {
            "model":    model,
            "messages": messages,
            "stream":   True,
            "options":  _build_options(token_budget=280, num_ctx=num_ctx),
        }

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    text = chunk.get("message", {}).get("content", "")
                    if text:
                        yield text
                    if chunk.get("done"):
                        break

    async def generate_sync(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
    ) -> str:
        """Non-streaming single-turn completion. Used for internal summarization tasks."""
        return await self.generate(
            prompt=prompt,
            model=model,
            system=system,
            thinking_enabled=False,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_system_prompt(system: str | None, thinking_enabled: bool) -> str | None:
    """
    Prepend the gemma4 thinking token when enabled.
    The <|think|> token must appear at the very start of the system prompt.
    """
    if system is None and not thinking_enabled:
        return None
    base = system or ""
    if thinking_enabled:
        return f"<|think|>{base}" if base else "<|think|>"
    return base or None


def _build_options(token_budget: int, num_ctx: int | None) -> dict:
    """
    gemma4 recommended sampling parameters + optional context window override.
    Visual token budget is passed through for future multimodal support.
    """
    options: dict = {
        "temperature": 1.0,
        "top_p":       0.95,
        "top_k":       64,
        # Store token_budget for multimodal requests (Phase 4)
        "token_budget": token_budget,
    }
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    return options
