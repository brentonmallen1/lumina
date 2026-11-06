"""
Upgraded-deck sources: deck links in the video description, and decklists the
user pastes.

  * Archidekt — public JSON API. Decks often carry explicit "Adds" / "Cuts"
    categories (e.g. The Command Zone), which are used verbatim.
  * Moxfield — no public API; a plain request is tried once and, when it is
    refused (usually), the user is told to paste the list instead.
  * Pasted text — Moxfield/Archidekt/MTGA export format ("1 Card Name"), with
    optional section headers (Commander, Deck, Sideboard, Cuts, Adds, …).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Lumina/0.2 (self-hosted content tool)", "Accept": "application/json"}

ARCHIDEKT_RE = re.compile(r"https?://(?:www\.)?archidekt\.com/(?:api/)?decks/(\d+)", re.I)
MOXFIELD_RE = re.compile(r"https?://(?:www\.)?moxfield\.com/decks/([A-Za-z0-9_-]{6,})", re.I)


@dataclass
class Decklist:
    source: str                                  # "archidekt" | "moxfield" | "pasted"
    url: str | None = None
    name: str | None = None
    commander: list[str] = field(default_factory=list)
    main: list[str] = field(default_factory=list)   # the upgraded deck (incl. commander)
    adds: list[str] = field(default_factory=list)   # explicit "Adds" section, if any
    cuts: list[str] = field(default_factory=list)   # explicit "Cuts"/sideboard section, if any

    @property
    def has_explicit_changes(self) -> bool:
        return bool(self.adds or self.cuts)


def find_deck_links(text: str) -> list[tuple[str, str]]:
    """[(site, id)] in order of appearance, de-duplicated."""
    found: list[tuple[int, str, str]] = []
    for m in ARCHIDEKT_RE.finditer(text or ""):
        found.append((m.start(), "archidekt", m.group(1)))
    for m in MOXFIELD_RE.finditer(text or ""):
        found.append((m.start(), "moxfield", m.group(1)))
    seen, out = set(), []
    for _, site, deck_id in sorted(found):
        if (site, deck_id) not in seen:
            seen.add((site, deck_id))
            out.append((site, deck_id))
    return out


# ── Archidekt ─────────────────────────────────────────────────────────────────

_CUT_CATEGORIES = {"cuts", "cut", "out", "removed", "remove", "sideboard", "maybeboard"}
_ADD_CATEGORIES = {"adds", "add", "in", "added", "upgrades", "new"}


def parse_archidekt(data: dict, deck_id: str) -> Decklist:
    excluded = {c.get("name", "").lower() for c in data.get("categories") or [] if c.get("includedInDeck") is False}
    deck = Decklist(source="archidekt", url=f"https://archidekt.com/decks/{deck_id}", name=data.get("name"))
    for entry in data.get("cards") or []:
        name = ((entry.get("card") or {}).get("oracleCard") or {}).get("name")
        if not name:
            continue
        cats = {c.lower() for c in entry.get("categories") or []}
        if cats & _CUT_CATEGORIES or (cats and cats <= excluded):
            deck.cuts.append(name)
            continue
        deck.main.append(name)
        if "commander" in cats:
            deck.commander.append(name)
        if cats & _ADD_CATEGORIES:
            deck.adds.append(name)
    return deck


async def fetch_archidekt(deck_id: str) -> Decklist:
    async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
        r = await client.get(f"https://archidekt.com/api/decks/{deck_id}/")
        r.raise_for_status()
        return parse_archidekt(r.json(), deck_id)


# ── Moxfield (best effort) ────────────────────────────────────────────────────

def parse_moxfield(data: dict, deck_id: str) -> Decklist:
    deck = Decklist(source="moxfield", url=f"https://moxfield.com/decks/{deck_id}", name=data.get("name"))
    boards = data.get("boards") or {}

    def names(board: str) -> list[str]:
        cards = (boards.get(board) or {}).get("cards") or {}
        return [(c.get("card") or {}).get("name") for c in cards.values() if (c.get("card") or {}).get("name")]

    deck.commander = names("commanders")
    deck.main = deck.commander + names("mainboard") + names("companions")
    deck.cuts = names("sideboard") + names("maybeboard")
    return deck


async def fetch_moxfield(deck_id: str) -> Decklist:
    async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
        r = await client.get(f"https://api2.moxfield.com/v3/decks/all/{deck_id}")
        r.raise_for_status()
        return parse_moxfield(r.json(), deck_id)


# ── Pasted text ───────────────────────────────────────────────────────────────

_LINE_RE = re.compile(r"^\s*(\d+)\s*x?\s+(.+?)\s*$", re.I)
_SECTION_RE = re.compile(r"^\s*(?://|#)?\s*([A-Za-z][A-Za-z ]*?)\s*:?\s*(?:\(\d+\))?\s*$")


def parse_pasted(text: str) -> Decklist:
    """Parse "1 Card Name" lines. Section headers route cards into commander /
    main / adds / cuts; set codes like "(TRC) 123" and *F* foil marks are stripped."""
    deck = Decklist(source="pasted")
    section = "main"
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            h = _SECTION_RE.match(line)
            if h:
                label = h.group(1).strip().lower()
                if label in ("commander", "commanders"):
                    section = "commander"
                elif label in _CUT_CATEGORIES:
                    section = "cuts"
                elif label in _ADD_CATEGORIES:
                    section = "adds"
                else:
                    section = "main"
            continue
        name = re.sub(r"\s+\([A-Za-z0-9]{2,6}\)\s*[\w-]*\s*$", "", m.group(2))
        name = re.sub(r"\s*\*[A-Z]+\*\s*$", "", name).strip()
        if not name:
            continue
        if section == "cuts":
            deck.cuts.append(name)
            continue
        deck.main.append(name)
        if section == "commander":
            deck.commander.append(name)
        elif section == "adds":
            deck.adds.append(name)
    return deck
