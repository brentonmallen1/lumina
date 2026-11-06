"""
Third-party integrations. Currently: Mealie (send recipes straight to your
Mealie server). Auth is applied at include time in main.py.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db
from integrations import mealie
from recipes.jsonld import is_empty_recipe, normalize_recipe

router = APIRouter(prefix="/api/integrations")


class MealieTestRequest(BaseModel):
    # Optional overrides so Settings can test values before saving them.
    url: str | None = None
    token: str | None = None


def _mealie_config(url: str | None = None, token: str | None = None) -> tuple[str, str]:
    from main import _SECRET_MASK  # avoid import cycle at module load
    url = url or db.get_setting("mealie_url", "")
    if not token or token == _SECRET_MASK:
        token = db.get_setting("mealie_api_token", "")
    if not url:
        raise HTTPException(status_code=400, detail="Mealie isn't configured — add its URL in Settings → Integrations.")
    return url, token


@router.post("/mealie/test")
async def mealie_test(req: MealieTestRequest):
    url, token = _mealie_config(req.url, req.token)
    try:
        return await mealie.test_connection(url, token)
    except mealie.MealieError as exc:
        return {"ok": False, "message": str(exc)}


class MealieRecipeRequest(BaseModel):
    recipe: dict | str              # schema.org Recipe (object or JSON text)
    source_url: str | None = None   # where the recipe came from (YouTube/page URL)
    image: str | None = None        # fallback image URL (e.g. video thumbnail)


@router.post("/mealie/recipes")
async def mealie_create_recipe(req: MealieRecipeRequest):
    url, token = _mealie_config()
    data = req.recipe
    if isinstance(data, str):
        from llm.runner import parse_json_result
        data = parse_json_result(data)
        if not isinstance(data, dict):
            raise HTTPException(status_code=422, detail="That isn't valid recipe JSON.")
    recipe = normalize_recipe(data, {"url": req.source_url, "thumbnail": req.image})
    if is_empty_recipe(recipe):
        raise HTTPException(status_code=422, detail="This recipe has no ingredients or steps to import.")
    try:
        return await mealie.create_recipe(url, token, recipe, source_url=recipe.get("url"))
    except mealie.MealieError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
