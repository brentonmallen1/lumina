"""
Original precon decklists from MTGJSON (https://mtgjson.com).

``DeckList.json`` (index of every product decklist) is cached for 7 days;
individual deck files never change, so they are cached indefinitely.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from dataclasses import dataclass, field

import httpx

from . import cache
from .names import name_key

logger = logging.getLogger(__name__)

BASE = "https://mtgjson.com/api/v5"
HEADERS = {"User-Agent": "Lumina/0.2 (self-hosted content tool)"}
INDEX_TTL = 7 * 24 * 3600
COMMANDER_TYPES = {"Commander Deck", "MTGO Commander Deck"}


@dataclass
class Precon:
    name: str
    code: str
    file_name: str
    release_date: str | None = None
    commander: list[str] = field(default_factory=list)
    cards: list[str] = field(default_factory=list)   # every card name, commander included

    @property
    def url(self) -> str:
        return f"https://mtgjson.com/api/v5/decks/{self.file_name}.json"


async def _get(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60.0, headers=HEADERS, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def load_index() -> list[dict]:
    raw = cache.read_file("DeckList.json", max_age=INDEX_TTL)
    if raw is None:
        try:
            raw = await _get(f"{BASE}/DeckList.json")
            cache.write_file("DeckList.json", raw)
        except Exception as exc:
            logger.warning(f"MTGJSON index download failed: {exc}")
            raw = cache.read_file("DeckList.json")  # stale is better than nothing
            if raw is None:
                return []
    data = json.loads(raw).get("data") or []
    return [d for d in data if d.get("type") in COMMANDER_TYPES]


def _clean_title(text: str) -> str:
    text = re.sub(r"\b(precon|upgrade|guide|commander|edh|mtg|magic|the gathering|deck|budget|"
                  r"collector'?s edition|cards? in|cards? out)\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def match_precon(index: list[dict], *hints: str | None) -> dict | None:
    """Pick the precon whose name best matches any hint (LLM-extracted name, video title).

    Exact name containment wins (newest release first, non-collector edition
    preferred); otherwise fuzzy similarity with a conservative cutoff.
    """
    hints = [h for h in hints if h]
    if not index or not hints:
        return None
    ranked = sorted(index, key=lambda d: (d.get("releaseDate") or ""), reverse=True)
    ranked.sort(key=lambda d: "collector" in d.get("name", "").lower())

    for hint in hints:
        hk = name_key(hint)
        for d in ranked:
            dk = name_key(d.get("name", ""))
            if len(dk) >= 5 and dk in hk:
                return d

    best, best_score = None, 0.0
    for hint in hints:
        hk = name_key(_clean_title(hint))
        for d in ranked:
            score = difflib.SequenceMatcher(None, hk, name_key(d.get("name", ""))).ratio()
            if score > best_score:
                best, best_score = d, score
    return best if best_score >= 0.8 else None


async def load_precon(entry: dict) -> Precon:
    file_name = entry["fileName"]
    raw = cache.read_file(f"deck_{file_name}.json")
    if raw is None:
        raw = await _get(f"{BASE}/decks/{file_name}.json")
        cache.write_file(f"deck_{file_name}.json", raw)
    data = json.loads(raw).get("data") or {}
    commander = [c["name"] for c in data.get("commander") or [] if c.get("name")]
    main = [c["name"] for c in data.get("mainBoard") or [] if c.get("name")]
    return Precon(
        name=data.get("name") or entry.get("name"),
        code=data.get("code") or entry.get("code"),
        file_name=file_name,
        release_date=data.get("releaseDate") or entry.get("releaseDate"),
        commander=commander,
        cards=commander + main,
    )

