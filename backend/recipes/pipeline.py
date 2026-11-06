"""
Pipelines for the recipe modes.

Both modes first look for a recipe page linked from the video description
(see recipes/linked.py):

  * ``recipe_jsonld`` — if the page carries a complete schema.org Recipe, that
    *is* the result (normalized); the LLM isn't needed. Otherwise the model
    extracts from the transcript and the output is normalized
    (recipes/jsonld.py) so importers like Mealie accept it.
  * ``recipe`` (Markdown) — the page's recipe data is added to the content as
    authoritative structured data, then the model writes the Markdown.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import AsyncIterator
from urllib.parse import urlparse

from llm.runner import ModeContext, generate_for_mode, register_pipeline

from .jsonld import is_empty_recipe, normalize_recipe
from .linked import candidate_links, fetch_linked_recipe


async def _linked_recipe(ctx: ModeContext) -> AsyncIterator[dict]:
    """Yield status/warning events, then {"type": "linked", "recipe", "url"} or nothing."""
    links = candidate_links(ctx.source_meta.get("description"), ctx.source_meta.get("title"))
    if not links:
        return
    yield {"type": "status", "detail": "Checking the recipe page linked in the description…"}
    found = await fetch_linked_recipe(links)
    if found is None:
        return
    host = urlparse(found.url).netloc.removeprefix("www.")
    if found.recipe:
        yield {"type": "status", "detail": f"Using the creator's recipe from {host}"}
        yield {"type": "linked", "recipe": found.recipe, "url": found.url}
    elif found.error == "doesn't allow automated requests":
        yield {"type": "warning", "message": (
            f"The linked recipe page ({host}) doesn't allow automated requests, so this recipe was "
            f"rebuilt from the video. For the exact recipe, open {found.url} with the URL source."
        )}


@register_pipeline("recipe_jsonld")
async def recipe_jsonld_pipeline(ctx: ModeContext) -> AsyncIterator[dict]:
    async for ev in _linked_recipe(ctx):
        if ev["type"] != "linked":
            yield ev
            continue
        recipe = normalize_recipe(ev["recipe"], {**ctx.source_meta, "url": ev["url"]})
        if not is_empty_recipe(recipe):
            yield {
                "type": "result",
                "text": json.dumps(recipe, indent=2, ensure_ascii=False),
                "reasoning": "",
                "meta": {"mode": ctx.mode, "output_type": "json:recipe", "data": recipe,
                         "recipe_source": ev["url"]},
            }
            return

    async for ev in generate_for_mode(ctx):
        if ev["type"] != "result":
            yield ev
            continue
        data = (ev.get("meta") or {}).get("data")
        if isinstance(data, dict):
            recipe = normalize_recipe(data, ctx.source_meta)
            ev = {**ev, "text": json.dumps(recipe, indent=2, ensure_ascii=False),
                  "meta": {**ev.get("meta", {}), "data": recipe}}
        yield ev


@register_pipeline("recipe")
async def recipe_markdown_pipeline(ctx: ModeContext) -> AsyncIterator[dict]:
    linked = None
    async for ev in _linked_recipe(ctx):
        if ev["type"] == "linked":
            linked = ev
        else:
            yield ev
    if linked:
        structured = json.dumps(normalize_recipe(linked["recipe"]), indent=2, ensure_ascii=False)
        ctx = replace(ctx, content=(
            f"Structured data (schema.org) from the creator's recipe page {linked['url']}:\n"
            f"{structured}\n\nVideo transcript:\n{ctx.content}"
        ))
    async for ev in generate_for_mode(ctx):
        yield ev
