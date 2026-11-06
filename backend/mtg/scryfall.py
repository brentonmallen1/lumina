"""
Scryfall client: canonical card names, links, prices, type lines.

Resolution order for each name:
  1. Batch exact lookup via POST /cards/collection (75 names per request)
  2. GET /cards/named?fuzzy= for whatever wasn't found (handles typos)
Cards whose returned printing has no USD price get one extra search for the
cheapest priced printing. Results are cached in SQLite for 24 hours.

Scryfall asks for a descriptive User-Agent, an Accept header, and ~10
requests/second at most; we space requests by 100 ms.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from . import cache
from .names import name_key

logger = logging.getLogger(__name__)

API = "https://api.scryfall.com"
HEADERS = {"User-Agent": "Lumina/0.2 (self-hosted content tool)", "Accept": "application/json"}
CACHE_TTL = 24 * 3600
_MIN_INTERVAL = 0.1

_lock = asyncio.Lock()
_last_request = 0.0


async def _request(client: httpx.AsyncClient, method: str, path: str, **kw) -> httpx.Response:
    global _last_request
    async with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request = time.monotonic()
        return await client.request(method, f"{API}{path}", **kw)


def _summarize(card: dict) -> dict:
    faces = card.get("card_faces") or []
    images = card.get("image_uris") or (faces[0].get("image_uris") if faces else None) or {}
    prices = card.get("prices") or {}
    usd = prices.get("usd") or prices.get("usd_foil") or prices.get("usd_etched")
    return {
        "name":         card.get("name"),
        "scryfall_uri": (card.get("scryfall_uri") or "").split("?")[0] or None,
        "image":        images.get("normal") or images.get("small"),
        "price_usd":    float(usd) if usd else None,
        "type_line":    card.get("type_line"),
        "mana_cost":    card.get("mana_cost") or (faces[0].get("mana_cost") if faces else None),
    }


async def _cheapest_price(client: httpx.AsyncClient, name: str) -> float | None:
    try:
        r = await _request(client, "GET", "/cards/search", params={
            "q": f'!"{name}" usd>0', "order": "usd", "dir": "asc", "unique": "prints",
        })
        if r.status_code != 200:
            return None
        data = r.json().get("data") or []
        usd = (data[0].get("prices") or {}).get("usd") if data else None
        return float(usd) if usd else None
    except Exception:
        return None


async def resolve_cards(names: list[str]) -> dict[str, dict | None]:
    """Map each input name → card summary (or None if Scryfall has no match)."""
    wanted = {name_key(n): n for n in names if n and n.strip()}
    out: dict[str, dict | None] = {}

    for key in list(wanted):
        hit = cache.get_card(key, CACHE_TTL)
        if hit is not None:
            out[wanted.pop(key)] = hit or None

    if not wanted:
        return out

    async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
        pending = list(wanted.items())
        found: dict[str, dict] = {}

        # 1. Batched exact-name lookup
        for i in range(0, len(pending), 75):
            batch = pending[i:i + 75]
            try:
                r = await _request(client, "POST", "/cards/collection",
                                   json={"identifiers": [{"name": n} for _, n in batch]})
                r.raise_for_status()
                cards = r.json().get("data") or []
            except Exception as exc:
                logger.warning(f"Scryfall collection lookup failed: {exc}")
                cards = []
            by_key = {}
            for c in cards:
                by_key[name_key(c.get("name", ""))] = c
                for face in c.get("card_faces") or []:  # "Delver of Secrets" matches the DFC
                    by_key.setdefault(name_key(face.get("name", "")), c)
            for key, original in batch:
                if key in by_key:
                    found[key] = _summarize(by_key[key])

        # 2. Fuzzy lookup for the rest
        for key, original in pending:
            if key in found:
                continue
            try:
                r = await _request(client, "GET", "/cards/named", params={"fuzzy": original})
                if r.status_code == 200:
                    found[key] = _summarize(r.json())
            except Exception as exc:
                logger.warning(f"Scryfall fuzzy lookup failed for {original!r}: {exc}")

        # 3. Prices for new printings that don't have one yet
        for key, summary in found.items():
            if summary.get("price_usd") is None and summary.get("name"):
                summary["price_usd"] = await _cheapest_price(client, summary["name"])

    for key, original in pending:
        card = found.get(key)
        cache.set_card(key, card or {})
        out[original] = card
    return out
