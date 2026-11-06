"""
MTG precon-upgrade pipeline (mode ``mtg_precon``).

Combines every available source, most authoritative first:

  1. An upgraded decklist — pasted by the user, or linked in the description
     (Archidekt API; Moxfield best-effort). Explicit Adds/Cuts sections are
     used verbatim; otherwise the list is diffed against the original precon.
  2. The original precon list from MTGJSON (identified from the LLM's
     precon/commander name or the video title).
  3. The LLM's extraction from transcript + chapters + description, which also
     supplies the per-card reason, timestamp and swap pairing.

Every card name is then canonicalised (precon/deck lists first, then
Scryfall) and enriched with a Scryfall link, image and USD price. Cards that
don't line up with the precon (a "cut" that isn't in it, an "add" that's
already there) are flagged rather than silently dropped.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from llm.runner import ModeContext, generate_for_mode, register_pipeline

from . import decklists, precons, scryfall
from .names import is_basic_land, match_known, name_key

logger = logging.getLogger(__name__)


def _diff(upgraded: list[str], original: list[str]) -> tuple[list[str], list[str]]:
    """(added, removed) between two card-name lists, ignoring basic lands."""
    up = {name_key(n): n for n in upgraded if not is_basic_land(n)}
    orig = {name_key(n): n for n in original if not is_basic_land(n)}
    added = [n for k, n in up.items() if k not in orig]
    removed = [n for k, n in orig.items() if k not in up]
    return added, removed


def _index_llm(cards: list[dict]) -> dict[str, dict]:
    return {name_key(c.get("name", "")): c for c in cards if c.get("name")}


async def _gather_decklist(ctx: ModeContext, warnings: list[str]) -> decklists.Decklist | None:
    pasted = (ctx.options or {}).get("decklist")
    if pasted and pasted.strip():
        deck = decklists.parse_pasted(pasted)
        if deck.main or deck.cuts:
            return deck
        warnings.append("The pasted decklist couldn't be read — expected lines like \"1 Sol Ring\".")

    links = decklists.find_deck_links(ctx.source_meta.get("description") or "")
    for site, deck_id in links:
        try:
            if site == "archidekt":
                return await decklists.fetch_archidekt(deck_id)
            return await decklists.fetch_moxfield(deck_id)
        except Exception as exc:
            logger.info(f"Deck fetch failed for {site}:{deck_id}: {exc}")
            if site == "moxfield":
                warnings.append(
                    f"Found a Moxfield decklist (moxfield.com/decks/{deck_id}) but Moxfield doesn't allow "
                    "automated access. For exact results, export it from Moxfield and paste it into "
                    "\"Upgraded decklist\"."
                )
            else:
                warnings.append(f"Couldn't load the linked Archidekt deck ({exc}).")
    return None


async def _find_precon(llm: dict, ctx: ModeContext, warnings: list[str]) -> precons.Precon | None:
    try:
        index = await precons.load_index()
        entry = precons.match_precon(index, llm.get("precon_name"), ctx.source_meta.get("title"))
        if entry is None:
            return None
        return await precons.load_precon(entry)
    except Exception as exc:
        logger.warning(f"Precon lookup failed: {exc}")
        warnings.append("Couldn't load the original precon list from MTGJSON.")
        return None


def _card_entry(name: str, llm_card: dict | None, card: dict | None, flags: list[str]) -> dict:
    llm_card = llm_card or {}
    return {
        "name":         (card or {}).get("name") or name,
        "reason":       llm_card.get("reason") or None,
        "timestamp":    llm_card.get("timestamp") or None,
        "replaces":     llm_card.get("replaces") or None,
        "scryfall_uri": (card or {}).get("scryfall_uri"),
        "image":        (card or {}).get("image"),
        "price_usd":    (card or {}).get("price_usd"),
        "type_line":    (card or {}).get("type_line"),
        "verified":     card is not None,
        "flags":        flags,
    }


@register_pipeline("mtg_precon")
async def mtg_precon_pipeline(ctx: ModeContext) -> AsyncIterator[dict]:
    warnings: list[str] = []

    # ── 1. LLM extraction (reasons, timestamps, swaps; the lists as fallback) ──
    llm: dict = {}
    reasoning = ""
    result_meta: dict = {}
    async for ev in generate_for_mode(ctx):
        if ev["type"] == "result":
            llm = (ev.get("meta") or {}).get("data") or {}
            reasoning = ev.get("reasoning", "")
            result_meta = {k: v for k, v in (ev.get("meta") or {}).items() if k != "data"}
        elif ev["type"] == "text":
            continue  # raw JSON isn't shown; the enriched result replaces it
        else:
            yield ev
    if not isinstance(llm, dict):
        llm = {}

    # ── 2. Decklist + precon ───────────────────────────────────────────────
    yield {"type": "status", "detail": "Looking for the decklist and the original precon…"}
    deck = await _gather_decklist(ctx, warnings)
    precon = await _find_precon(llm, ctx, warnings)

    llm_in, llm_out = llm.get("cards_in") or [], llm.get("cards_out") or []
    if deck and deck.has_explicit_changes:
        adds, cuts, basis = deck.adds, deck.cuts, f"{deck.source} decklist (Adds/Cuts)"
    elif deck and deck.main and precon:
        adds, cuts = _diff(deck.main, precon.cards)
        basis = f"{deck.source} decklist compared with the original precon"
    else:
        adds = [c["name"] for c in llm_in if c.get("name")]
        cuts = [c["name"] for c in llm_out if c.get("name")]
        basis = "video transcript"
        if deck and deck.main and not precon:
            warnings.append("Found the upgraded decklist but not the original precon, so the lists come from the video.")

    # ── 3. Canonical names: known lists first, then Scryfall ───────────────
    yield {"type": "status", "detail": "Checking card names with Scryfall…"}
    known = list({*(precon.cards if precon else []), *(deck.main if deck else []), *(deck.cuts if deck else [])})
    corrected: dict[str, str] = {}  # corrected name → what the source said

    def fix(n: str, pool: list[str], loose: bool = False) -> str:
        hit = match_known(n, pool) or (match_known(n, pool, cutoff=0.5, margin=0.08) if loose else None)
        # Record real corrections only — not a dropped leading "The".
        if hit and name_key(hit).removeprefix("the") != name_key(n).removeprefix("the"):
            corrected[hit] = n
        return hit or n

    adds = [fix(n, known) for n in adds]
    # A cut must come from the precon, so a looser match against it is safe
    # (fixes caption errors like "King Prahv" → "Kang Prime").
    cuts = [fix(n, precon.cards, loose=True) if precon else fix(n, known) for n in cuts]
    swaps_raw = [(c.get("replaces"), c.get("name")) for c in llm_in if c.get("replaces") and c.get("name")]

    names = list({*adds, *cuts, *(r for r, _ in swaps_raw), *(n for _, n in swaps_raw)})
    try:
        resolved = await scryfall.resolve_cards(names)
    except Exception as exc:
        logger.warning(f"Scryfall resolution failed: {exc}")
        warnings.append("Scryfall was unreachable, so card names weren't verified and prices are missing.")
        resolved = {}

    def canonical(n: str) -> str:
        return (resolved.get(n) or {}).get("name") or n

    precon_keys = {name_key(n) for n in precon.cards} if precon else set()
    llm_in_ix, llm_out_ix = _index_llm(llm_in), _index_llm(llm_out)

    def llm_lookup(ix: dict, n: str) -> dict | None:
        if n in corrected:
            hit = ix.get(name_key(corrected[n]))
            if hit:
                return hit
        return ix.get(name_key(n)) or ix.get(name_key(canonical(n))) or next(
            (v for k, v in ix.items() if match_known(v["name"], [n, canonical(n)])), None)

    cards_in, cards_out = [], []
    def correction_flag(n: str) -> list[str]:
        return [f"corrected from \u201c{corrected[n]}\u201d"] if n in corrected else []

    for n in dict.fromkeys(adds):
        flags = correction_flag(n)
        if name_key(canonical(n)) in precon_keys:
            flags.append("already in the precon")
        if n not in resolved or resolved.get(n) is None:
            flags.append("not found on Scryfall")
        cards_in.append(_card_entry(n, llm_lookup(llm_in_ix, n), resolved.get(n), flags))
    for n in dict.fromkeys(cuts):
        flags = correction_flag(n)
        if precon and name_key(canonical(n)) not in precon_keys:
            flags.append("not in the precon list")
        if n not in resolved or resolved.get(n) is None:
            flags.append("not found on Scryfall")
        cards_out.append(_card_entry(n, llm_lookup(llm_out_ix, n), resolved.get(n), flags))

    in_keys = {name_key(c["name"]) for c in cards_in}
    out_keys = {name_key(c["name"]) for c in cards_out}
    swaps = [
        {"out": canonical(r), "in": canonical(n)}
        for r, n in swaps_raw
        if name_key(canonical(r)) in out_keys and name_key(canonical(n)) in in_keys
    ]

    mentions = [
        {"name": canonical(m["name"]) if m.get("name") in resolved else m.get("name"), "reason": m.get("reason")}
        for m in llm.get("honorable_mentions") or [] if m.get("name")
    ]

    total = sum(c["price_usd"] or 0 for c in cards_in)
    priced = sum(1 for c in cards_in if c["price_usd"] is not None)
    if len(cards_in) != len(cards_out):
        warnings.append(f"{len(cards_in)} cards added but {len(cards_out)} cut — double-check the lists.")

    commander = llm.get("commander") or (precon.commander[0] if precon and precon.commander else None) \
        or (deck.commander[0] if deck and deck.commander else None)
    result = {
        "precon": {
            "name": precon.name if precon else llm.get("precon_name"),
            "set_code": precon.code if precon else None,
            "matched": precon is not None,
        },
        "commander": commander,
        "budget": llm.get("budget"),
        "basis": basis,
        "decklist_url": deck.url if deck else None,
        "cards_in": cards_in,
        "cards_out": cards_out,
        "swaps": swaps,
        "honorable_mentions": mentions,
        "totals": {"add_cost_usd": round(total, 2), "priced_cards": priced},
        "import_text": {
            "add": "\n".join(f"1 {c['name']}" for c in cards_in),
            "remove": "\n".join(f"1 {c['name']}" for c in cards_out),
        },
        "warnings": warnings,
    }
    # Warnings travel inside the result (the MTG view shows them), not as
    # separate events, so they aren't displayed twice.
    yield {
        "type": "result",
        "text": json.dumps(result, indent=2, ensure_ascii=False),
        "reasoning": reasoning,
        "meta": {**result_meta, "data": result},
    }
