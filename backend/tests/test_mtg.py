"""MTG precon-upgrade mode tests (network and LLM mocked)."""

import asyncio
import json

import pytest

from mtg import decklists, pipeline, precons, scryfall
from mtg.names import is_basic_land, match_known, name_key


def run(coro):
    return asyncio.run(coro)


# ── Names ────────────────────────────────────────────────────────────────────

def test_name_key_and_basics():
    assert name_key("Lim-Dûl's Vault") == name_key("lim dul's vault")
    assert name_key("Delver of Secrets // Insectile Aberration") == name_key("Delver of Secrets")
    assert is_basic_land("Snow-Covered Island") and not is_basic_land("Command Tower")


def test_match_known_fixes_caption_errors():
    known = ["Sol Ring", "Arcane Signet", "Kang Prime"]
    assert match_known("soul ring", known) == "Sol Ring"
    assert match_known("arcane signit", known) == "Arcane Signet"
    assert match_known("King Prahv", known) is None
    assert match_known("King Prahv", known, cutoff=0.5, margin=0.08) == "Kang Prime"
    # Two near-identical candidates: refuse to guess.
    assert match_known("Kang Prim", ["Kang Prime", "Kang Primo"], cutoff=0.5, margin=0.08) is None


# ── Deck sources ─────────────────────────────────────────────────────────────

def test_find_deck_links_in_order():
    desc = ("Patreon https://patreon.com/x\nDeck: https://moxfield.com/decks/vDaN0--gqkar5oLWqlIp2Q\n"
            "Also https://archidekt.com/decks/28130622/cz_773 and https://www.archidekt.com/commandzone")
    assert decklists.find_deck_links(desc) == [("moxfield", "vDaN0--gqkar5oLWqlIp2Q"), ("archidekt", "28130622")]


def _arch_card(name, cats):
    return {"categories": cats, "card": {"oracleCard": {"name": name}}}


def test_parse_archidekt_adds_and_cuts():
    data = {
        "name": "CZ upgrade",
        "categories": [{"name": "Cuts", "includedInDeck": False}, {"name": "Adds", "includedInDeck": True}],
        "cards": [
            _arch_card("Spock", ["Commander"]),
            _arch_card("Sol Ring", ["Artifact"]),
            _arch_card("Horizon Explorer", ["Adds"]),
            _arch_card("Sun Titan", ["Cuts", "Creature"]),
            _arch_card("Maybe Card", ["Maybeboard"]),
        ],
    }
    deck = decklists.parse_archidekt(data, "1")
    assert deck.commander == ["Spock"]
    assert deck.adds == ["Horizon Explorer"]
    assert deck.cuts == ["Sun Titan", "Maybe Card"]
    assert "Sun Titan" not in deck.main and "Horizon Explorer" in deck.main


def test_parse_pasted_sections_and_set_codes():
    text = """Commander
1 Doctor Doom, King of Latveria (MSC) 1

Deck
1 Sol Ring (TRC) 499
2x Island
1 Reanimate *F*

SIDEBOARD:
1 Skullclamp
"""
    deck = decklists.parse_pasted(text)
    assert deck.commander == ["Doctor Doom, King of Latveria"]
    assert "Sol Ring" in deck.main and "Reanimate" in deck.main and "Island" in deck.main
    assert deck.cuts == ["Skullclamp"]
    assert deck.has_explicit_changes


# ── Precons ──────────────────────────────────────────────────────────────────

INDEX = [
    {"name": "Doom Prevails", "code": "MSC", "fileName": "DoomPrevails_MSC", "releaseDate": "2026-06-26", "type": "Commander Deck"},
    {"name": "Doom Prevails Collector's Edition", "code": "MSC", "fileName": "DoomPrevailsCollectorSEdition_MSC", "releaseDate": "2026-06-26", "type": "Commander Deck"},
    {"name": "Blood Rites", "code": "LCC", "fileName": "BloodRites_LCC", "releaseDate": "2023-11-17", "type": "Commander Deck"},
]


def test_match_precon_prefers_exact_and_non_collector():
    m = precons.match_precon(INDEX, None, "Doom Prevails — 10 In / 10 Out (Budget $50) | Commander Precon Upgrade Guide")
    assert m["fileName"] == "DoomPrevails_MSC"
    assert precons.match_precon(INDEX, "Blood Rite")["name"] == "Blood Rites"  # LLM typo → fuzzy
    assert precons.match_precon(INDEX, "Landing Party") is None


def test_diff_ignores_basics():
    added, removed = pipeline._diff(["A", "B", "Island", "New"], ["A", "B", "Old", "Island", "Forest"])
    assert added == ["New"] and removed == ["Old"]


# ── Full pipeline ────────────────────────────────────────────────────────────

class FakeRuntime:
    """Just enough of Runtime for generate_for_mode with a canned LLM answer."""

    def __init__(self, answer: dict):
        from llm.client import LLMEvent
        from llm.runner import ModelProfile

        self.answer = answer
        self.model = "fake"
        self.num_ctx = 131072
        self.output_budget = 32768
        self.input_budget = 98000
        self.profile = ModelProfile(name="fake", capabilities={"completion"})
        rt = self

        class Client:
            base_url = "http://fake"

            async def generate_stream(self, *a, **kw):
                yield LLMEvent("text", json.dumps(rt.answer))
                yield LLMEvent("done", stats={"done_reason": "stop"})

        self.client = Client()

    def think_param(self, _=None):
        return None

    def options(self, *a, **kw):
        return {}


LLM_ANSWER = {
    "precon_name": "Doom Prevails",
    "commander": "Doctor Doom, King of Latveria",
    "budget": "$50",
    "cards_in": [
        {"name": "Reanimate", "reason": "graveyard value", "timestamp": "6:37", "replaces": "Skullclamp"},
        {"name": "Arcane Denial", "reason": "cheap counter", "timestamp": "7:03"},
    ],
    "cards_out": [
        {"name": "Skullclamp", "reason": "no sac outlets", "timestamp": "1:02"},
        {"name": "King Prahv", "reason": "no time counters", "timestamp": "4:15"},
    ],
    "honorable_mentions": [{"name": "Bone Miser"}],
}

PRECON = precons.Precon(
    name="Doom Prevails", code="MSC", file_name="DoomPrevails_MSC",
    commander=["Doctor Doom, King of Latveria"],
    cards=["Doctor Doom, King of Latveria", "Skullclamp", "Kang Prime", "Sol Ring"],
)


@pytest.fixture
def mocked(monkeypatch):
    import db
    monkeypatch.setattr(db, "get_prompt_by_mode", lambda mode: None)

    async def fake_index():
        return INDEX

    async def fake_load(entry):
        return PRECON

    async def fake_resolve(names):
        return {n: {"name": n, "scryfall_uri": f"https://scryfall.com/{name_key(n)}", "price_usd": 1.5,
                    "image": None, "type_line": "Card"} for n in names}

    monkeypatch.setattr(precons, "load_index", fake_index)
    monkeypatch.setattr(precons, "load_precon", fake_load)
    monkeypatch.setattr(scryfall, "resolve_cards", fake_resolve)


def _run_pipeline(source_meta=None, options=None):
    from llm.runner import ModeContext
    ctx = ModeContext(
        mode="mtg_precon", content="[0:00] transcript", header="",
        source_meta=source_meta or {"title": "Doom Prevails upgrade"},
        runtime=FakeRuntime(LLM_ANSWER), options=options,
    )

    async def go():
        return [e async for e in pipeline.mtg_precon_pipeline(ctx)]

    events = run(go())
    assert events[-1]["type"] == "result"
    return json.loads(events[-1]["text"]), events


def test_pipeline_from_transcript(mocked):
    r, events = _run_pipeline()
    assert r["precon"] == {"name": "Doom Prevails", "set_code": "MSC", "matched": True}
    assert r["basis"] == "video transcript"
    assert [c["name"] for c in r["cards_in"]] == ["Reanimate", "Arcane Denial"]
    outs = {c["name"]: c for c in r["cards_out"]}
    assert "Kang Prime" in outs and outs["Kang Prime"]["flags"] == ["corrected from “King Prahv”"]
    assert outs["Kang Prime"]["reason"] == "no time counters"
    assert r["swaps"] == [{"out": "Skullclamp", "in": "Reanimate"}]
    assert r["totals"] == {"add_cost_usd": 3.0, "priced_cards": 2}
    assert r["import_text"]["add"] == "1 Reanimate\n1 Arcane Denial"
    assert not any(e["type"] == "text" for e in events)


def test_pipeline_pasted_decklist_wins(mocked):
    pasted = "1 Doctor Doom, King of Latveria\n1 Sol Ring\n1 Kang Prime\n1 Reanimate\n1 Lightning Greaves\n"
    r, _ = _run_pipeline(options={"decklist": pasted})
    assert r["basis"] == "pasted decklist compared with the original precon"
    assert sorted(c["name"] for c in r["cards_in"]) == ["Lightning Greaves", "Reanimate"]
    assert [c["name"] for c in r["cards_out"]] == ["Skullclamp"]
    # LLM reason still attached to the diffed card
    assert next(c for c in r["cards_in"] if c["name"] == "Reanimate")["timestamp"] == "6:37"


def test_pipeline_flags_cards_inconsistent_with_precon(mocked):
    answer = dict(LLM_ANSWER, cards_in=[{"name": "Sol Ring"}], cards_out=[{"name": "Totally Different Card"}])
    from llm.runner import ModeContext
    ctx = ModeContext(mode="mtg_precon", content="x", header="", source_meta={"title": "Doom Prevails"},
                      runtime=FakeRuntime(answer))

    async def go():
        return [e async for e in pipeline.mtg_precon_pipeline(ctx)]

    r = json.loads(run(go())[-1]["text"])
    assert "already in the precon" in r["cards_in"][0]["flags"]
    assert "not in the precon list" in r["cards_out"][0]["flags"]
