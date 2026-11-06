"""Recipe format conversion shared by the API routes."""

from __future__ import annotations

from .jsonld import is_empty_recipe, normalize_recipe
from .markdown import from_markdown


class ConversionError(ValueError):
    pass


async def markdown_to_recipe(markdown: str, source_url: str | None = None, image: str | None = None) -> tuple[dict, str]:
    """Markdown → normalized schema.org Recipe. Returns (recipe, method).

    Lumina's own Recipe Markdown parses in code (method "code"); anything else
    falls back to the LLM (method "llm").
    """
    meta = {"url": source_url, "thumbnail": image}
    parsed = from_markdown(markdown)
    if parsed:
        return normalize_recipe(parsed, meta), "code"

    from llm.prompts import RECIPE_JSONLD_PROMPT, RECIPE_JSONLD_SCHEMA, render_template
    from llm.runner import parse_json_result, resolve_runtime, stream_pass

    rt = await resolve_runtime()
    raw = ""
    async for ev in stream_pass(
        rt, system=RECIPE_JSONLD_PROMPT["system"],
        prompt=render_template(RECIPE_JSONLD_PROMPT["template"], markdown),
        temperature=0.1, think=rt.think_param(False), format=RECIPE_JSONLD_SCHEMA,
        forward_text=False, forward_thinking=False,
    ):
        if ev["type"] == "pass_done":
            raw = ev["text"]
    data = parse_json_result(raw)
    if not isinstance(data, dict):
        raise ConversionError("The model did not return valid recipe JSON.")
    recipe = normalize_recipe(data, meta)
    if is_empty_recipe(recipe):
        raise ConversionError("No ingredients or steps were found in this recipe.")
    return recipe, "llm"
