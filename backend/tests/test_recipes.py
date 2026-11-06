"""Recipe JSON-LD normalization and the Mealie integration (Mealie mocked)."""

import asyncio
import json

import httpx
import pytest

from recipes.jsonld import is_empty_recipe, iso_duration, normalize_recipe

# Real model output that Mealie imported with no steps: HowToStep @type missing.
USER_RECIPE = {
    "name": "Fettuccine with Cherry Tomato Butter Sauce",
    "recipeIngredient": ["3 pints fresh cherry tomatoes", "1 medium onion, diced"],
    "recipeInstructions": [{"text": "Heat a large pan."}, {"text": "Add the tomatoes."}],
    "@context": "https://schema.org",
    "@type": "Recipe",
    "prepTime": "PT10M",
    "cookTime": "PT35M",
    "recipeYield": "4 servings",
}


def test_steps_get_howtostep_type():
    r = normalize_recipe(USER_RECIPE)
    assert r["recipeInstructions"] == [
        {"@type": "HowToStep", "text": "Heat a large pan."},
        {"@type": "HowToStep", "text": "Add the tomatoes."},
    ]
    assert r["@context"] == "https://schema.org" and r["@type"] == "Recipe"
    assert r["totalTime"] == "PT45M"  # derived from prep + cook when missing


def test_source_meta_adds_url_image_author():
    r = normalize_recipe(USER_RECIPE, {
        "url": "https://www.youtube.com/watch?v=abc",
        "thumbnail": "https://i.ytimg.com/vi/abc/maxresdefault.jpg",
        "uploader": "Some Chef",
    })
    assert r["url"] == "https://www.youtube.com/watch?v=abc"
    assert r["image"].endswith("maxresdefault.jpg")
    assert r["author"] == {"@type": "Person", "name": "Some Chef"}


def test_instruction_shapes():
    r = normalize_recipe({
        "name": "X",
        "recipeIngredient": "1 egg\n2 cups flour\n",
        "recipeInstructions": [
            "Whisk.",
            {"@type": "HowToSection", "name": "Bake", "itemListElement": [{"text": "Bake 20 min."}]},
        ],
    })
    assert r["recipeIngredient"] == ["1 egg", "2 cups flour"]
    assert [s["text"] for s in r["recipeInstructions"]] == ["Whisk.", "Bake 20 min."]

    numbered = normalize_recipe({"name": "Y", "recipeInstructions": "1. Mix\n2) Bake\n- Serve"})
    assert [s["text"] for s in numbered["recipeInstructions"]] == ["Mix", "Bake", "Serve"]


def test_graph_and_nulls_removed():
    r = normalize_recipe({"@graph": [{"@type": "WebPage"}, {"@type": "Recipe", "name": "G",
                          "description": None, "prepTime": None, "recipeIngredient": ["a"]}]})
    assert r["name"] == "G" and "description" not in r and "prepTime" not in r


@pytest.mark.parametrize("value,expected", [
    ("15 minutes", "PT15M"), ("1 hour 30 min", "PT1H30M"), ("1.5 hours", "PT1H30M"),
    ("pt20m", "PT20M"), (90, "PT1H30M"), ("45", "PT45M"), ("about a while", None), ("", None),
])
def test_iso_duration(value, expected):
    assert iso_duration(value) == expected


def test_empty_recipe_detected():
    assert is_empty_recipe(normalize_recipe({"name": "Nothing"}))


# ── Mealie client ────────────────────────────────────────────────────────────

def _mock_mealie(monkeypatch, handler):
    from integrations import mealie
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(mealie.httpx, "AsyncClient", factory)


def test_mealie_create_recipe_posts_jsonld(monkeypatch):
    from integrations import mealie
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path == "/api/recipes/create/html-or-json":
            seen["auth"] = request.headers["Authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(201, json="fettuccine-with-cherry-tomato-butter-sauce")
        if request.url.path == "/api/users/self":
            return httpx.Response(200, json={"groupSlug": "home", "username": "b"})
        return httpx.Response(404)

    _mock_mealie(monkeypatch, handler)
    recipe = normalize_recipe(USER_RECIPE)
    out = asyncio.run(mealie.create_recipe("https://mealie.local/", "tok", recipe, "https://youtu.be/x"))
    assert out == {"slug": "fettuccine-with-cherry-tomato-butter-sauce",
                   "url": "https://mealie.local/g/home/r/fettuccine-with-cherry-tomato-butter-sauce"}
    assert seen["auth"] == "Bearer tok"
    sent = json.loads(seen["body"]["data"])
    assert sent["recipeInstructions"][0]["@type"] == "HowToStep"
    assert seen["body"]["url"] == "https://youtu.be/x" and seen["body"]["includeTags"] is False


def test_mealie_bad_token_message(monkeypatch):
    from integrations import mealie

    def handler(request):
        if request.url.path == "/api/app/about":
            return httpx.Response(200, json={"version": "v2.8.0"})
        return httpx.Response(401, json={"detail": "Not authenticated"})

    _mock_mealie(monkeypatch, handler)
    with pytest.raises(mealie.MealieError, match="API token"):
        asyncio.run(mealie.test_connection("https://mealie.local", "bad"))


def test_mealie_url_validation():
    from integrations import mealie
    with pytest.raises(mealie.MealieError):
        asyncio.run(mealie.test_connection("mealie.local", "t"))


# ── Linked recipe pages ──────────────────────────────────────────────────────

DESCRIPTION = """For 50% OFF go to https://www.brightcellars.com/sipandfeast for wine!
WATCH MORE PASTA! https://youtube.com/playlist?list=PL0
SUPPORT ON PATREON: https://www.patreon.com/sipandfeast
********** THIS IS THE PRINT RECIPE **********
FETTUCCINE WITH CHERRY TOMATO BUTTER SAUCE PRINT RECIPE:
https://www.sipandfeast.com/fettuccine-cherry-tomato-butter-sauce/
"""


def test_candidate_links_pick_the_recipe_page_only():
    from recipes.linked import candidate_links
    links = candidate_links(DESCRIPTION, "Fettuccine with Cherry Tomato Butter Sauce")
    assert links == ["https://www.sipandfeast.com/fettuccine-cherry-tomato-butter-sauce/"]
    assert candidate_links("no links here") == []


def test_find_recipe_node_in_graph():
    from recipes.linked import find_recipe_node
    html = ('<html><script type="application/ld+json">{"@graph": [{"@type": "WebSite"},'
            '{"@type": ["Recipe"], "name": "Pasta", "recipeIngredient": ["a"], '
            '"recipeInstructions": [{"@type": "HowToStep", "text": "Boil."}]}]}</script></html>')
    node = find_recipe_node(html)
    assert node["name"] == "Pasta"
    assert find_recipe_node("<html><script type='application/ld+json'>{bad json</script></html>") is None


def test_fetch_linked_recipe_reports_blocked(monkeypatch):
    from recipes import linked
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda req: httpx.Response(403))
        return real(*args, **kwargs)

    monkeypatch.setattr(linked.httpx, "AsyncClient", factory)
    out = asyncio.run(linked.fetch_linked_recipe(["https://example.com/recipe"]))
    assert out.recipe is None and out.error == "doesn't allow automated requests"


# ── Markdown ⇄ JSON-LD ───────────────────────────────────────────────────────

def test_round_trip_json_markdown_json():
    from recipes.markdown import from_markdown, to_markdown
    src = normalize_recipe({**USER_RECIPE, "description": "Easy pasta.", "url": "https://example.com/r"})
    md = to_markdown(src)
    assert "**Prep time:** 10 minutes" in md and "## Ingredients" in md and "1. Heat a large pan." in md
    back = from_markdown(md)
    for key in ("name", "description", "recipeIngredient", "recipeInstructions", "prepTime",
                "cookTime", "totalTime", "recipeYield", "url"):
        assert back[key] == src[key], key


def test_from_markdown_handles_model_variations():
    from recipes.markdown import from_markdown
    md = """# Weeknight Curry

A quick, mild curry.

**Prep time:** 10 minutes
**Cook time:** 1 hour 5 min
**Servings:** 4

## Ingredients

### For the sauce
* 2 tbsp **oil**
* 1 onion, diced

## Instructions

1. Heat the oil.
2. Add the onion and cook
   until soft.
- Serve.

## Notes

- Freezes well.
"""
    r = from_markdown(md)
    assert r["name"] == "Weeknight Curry" and r["description"] == "A quick, mild curry."
    assert r["prepTime"] == "PT10M" and r["cookTime"] == "PT1H5M" and r["recipeYield"] == "4"
    assert r["recipeIngredient"] == ["2 tbsp oil", "1 onion, diced"]
    assert [s["text"] for s in r["recipeInstructions"]] == [
        "Heat the oil.", "Add the onion and cook until soft.", "Serve."]


def test_from_markdown_rejects_non_recipes():
    from recipes.markdown import from_markdown
    assert from_markdown("# Summary\n\nJust prose, no recipe.") is None
    assert from_markdown("No recipe detected in this content.") is None


def test_youtube_url_gives_thumbnail_image():
    r = normalize_recipe({**USER_RECIPE}, {"url": "https://youtu.be/uCQvpRnqYxM"})
    assert r["image"] == "https://i.ytimg.com/vi/uCQvpRnqYxM/hqdefault.jpg"
    assert "image" not in normalize_recipe({**USER_RECIPE}, {"url": "https://example.com/r"})
