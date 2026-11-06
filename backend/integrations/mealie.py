"""
Mealie API client (https://docs.mealie.io).

Recipes are created with ``POST /api/recipes/create/html-or-json``. Mealie
treats a body starting with ``{`` as schema.org JSON-LD and runs it through
its normal importer, which also downloads the ``image`` URL. Auth is a Mealie
API token (User → API Tokens) sent as a Bearer token.
"""

from __future__ import annotations

import json

import httpx


class MealieError(RuntimeError):
    pass


def _base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise MealieError("Mealie URL must start with http:// or https://")
    return url.removesuffix("/api")


def _headers(token: str) -> dict:
    if not token:
        raise MealieError("No Mealie API token configured")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _error(r: httpx.Response) -> MealieError:
    try:
        detail = r.json().get("detail")
        if isinstance(detail, dict):
            detail = detail.get("message") or json.dumps(detail)
    except Exception:
        detail = r.text[:200]
    if r.status_code in (401, 403):
        return MealieError("Mealie rejected the API token — create a new one under your Mealie profile → API Tokens.")
    return MealieError(f"Mealie returned {r.status_code}: {detail or r.reason_phrase}")


async def test_connection(url: str, token: str) -> dict:
    """Return {ok, message, version, user} after checking the URL and token."""
    base = _base(url)
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        try:
            about = await client.get(f"{base}/api/app/about")
        except httpx.HTTPError as exc:
            raise MealieError(f"Couldn't reach Mealie at {base}: {exc}") from exc
        if about.status_code != 200:
            raise MealieError(f"{base} doesn't look like a Mealie server (HTTP {about.status_code}).")
        me = await client.get(f"{base}/api/users/self", headers=_headers(token))
        if me.status_code != 200:
            raise _error(me)
    user = me.json()
    version = about.json().get("version", "")
    name = user.get("fullName") or user.get("username") or "user"
    return {"ok": True, "message": f"Connected to Mealie {version} as {name}", "version": version,
            "group_slug": user.get("groupSlug")}


async def create_recipe(url: str, token: str, recipe: dict, source_url: str | None = None) -> dict:
    """Create a recipe from schema.org JSON-LD. Returns {slug, url}."""
    base = _base(url)
    headers = _headers(token)
    body = {"data": json.dumps(recipe, ensure_ascii=False), "includeTags": False}
    if source_url:
        body["url"] = source_url
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True) as client:
        try:
            r = await client.post(f"{base}/api/recipes/create/html-or-json", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise MealieError(f"Couldn't reach Mealie at {base}: {exc}") from exc
        if r.status_code not in (200, 201):
            raise _error(r)
        slug = r.json()
        if not isinstance(slug, str) or not slug:
            raise MealieError("Mealie didn't return a recipe slug.")

        group = None
        try:
            me = await client.get(f"{base}/api/users/self", headers=headers)
            if me.status_code == 200:
                group = me.json().get("groupSlug")
        except httpx.HTTPError:
            pass

    link = f"{base}/g/{group}/r/{slug}" if group else f"{base}/recipe/{slug}"
    return {"slug": slug, "url": link}
