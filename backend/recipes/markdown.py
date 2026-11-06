"""
Recipe Markdown ⇄ schema.org JSON-LD, in code.

``to_markdown`` renders a Recipe in the same layout the Recipe mode prompt
asks the model for. ``from_markdown`` parses that layout (and common
variations: ``*``/``-`` bullets, numbered or bulleted steps, sub-headings
inside sections) back into a Recipe dict, or returns None when the text
doesn't look like a recipe — the caller then falls back to the LLM.
"""

from __future__ import annotations

import re

from .jsonld import iso_duration, normalize_recipe

_TIME_LABELS = {"prep": "prepTime", "cook": "cookTime", "total": "totalTime"}


def human_duration(iso: str | None) -> str | None:
    if not iso:
        return None
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", iso)
    if not m:
        return iso
    days, hours, minutes, _secs = (int(x or 0) for x in m.groups())
    hours += days * 24
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " ".join(parts) or None


def to_markdown(recipe: dict) -> str:
    """Render a schema.org Recipe as Markdown."""
    r = normalize_recipe(recipe)
    out = [f"# {r['name']}", ""]
    if r.get("description"):
        out += [r["description"], ""]
    facts = []
    for label, key in (("Prep time", "prepTime"), ("Cook time", "cookTime"), ("Total time", "totalTime")):
        h = human_duration(r.get(key))
        if h:
            facts.append(f"**{label}:** {h}")
    if r.get("recipeYield"):
        facts.append(f"**Servings:** {r['recipeYield']}")
    if facts:
        out += ["  \n".join(facts), ""]
    out += ["## Ingredients", ""] + [f"- {i}" for i in r.get("recipeIngredient", [])] + [""]
    out += ["## Instructions", ""] + [f"{n}. {s['text']}" for n, s in enumerate(r.get("recipeInstructions", []), 1)]
    source = r.get("url")
    if source:
        out += ["", f"Source: {source}"]
    return "\n".join(out).strip() + "\n"


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.*)$")
_FACT = re.compile(r"^\s*\**\s*(prep(?:aration)?|cook(?:ing)?|total|servings|serves|yield)\s*(?:time)?\s*:?\**\s*:?\s*(.+?)\s*$", re.I)


def _strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*|__(.*?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"(?<!\w)[*_](.*?)[*_](?!\w)", r"\1", text)
    return re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text).strip()


def from_markdown(markdown: str) -> dict | None:
    """Parse recipe Markdown into a schema.org Recipe, or None if it isn't one."""
    name, description = None, []
    data: dict = {}
    ingredients: list[str] = []
    steps: list[str] = []
    section = None  # None | "intro" | "ingredients" | "steps" | "other"

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        h = _HEADING.match(line)
        if h:
            title = _strip_md(h.group(2))
            low = title.lower()
            if len(h.group(1)) == 1 and name is None:
                name, section = title, "intro"
            elif re.search(r"ingredient", low):
                section = "ingredients"
            elif re.search(r"instruction|direction|method|steps|preparation", low):
                section = "steps"
            elif section in ("ingredients", "steps") and len(h.group(1)) >= 3:
                pass  # sub-heading inside a section ("### For the sauce") — keep going
            else:
                section = "other"
            continue

        if re.match(r"^\s*(?:source|from)\s*:\s*https?://", line, re.I):
            section = "other"  # trailing "Source: <url>" line ends the recipe body
            continue

        fact = _FACT.match(_strip_md(line).replace("  ", " ")) if section in (None, "intro") else None
        if fact:
            label, value = fact.group(1).lower(), _strip_md(fact.group(2))
            if label.startswith(("serv", "yield")):
                data["recipeYield"] = value
            else:
                key = _TIME_LABELS["prep" if label.startswith("prep") else "cook" if label.startswith("cook") else "total"]
                dur = iso_duration(value)
                if dur:
                    data[key] = dur
            continue

        b = _BULLET.match(line)
        if section == "ingredients":
            if b:
                ingredients.append(_strip_md(b.group(1)))
            elif ingredients and raw.startswith((" ", "\t")):
                ingredients[-1] += " " + _strip_md(line)
        elif section == "steps":
            if b:
                steps.append(_strip_md(b.group(1)))
            elif steps:
                steps[-1] += " " + _strip_md(line)  # wrapped continuation line
            else:
                steps.append(_strip_md(line))
        elif section in (None, "intro") and not b and not line.lstrip().startswith(("Source:", "---")):
            description.append(_strip_md(line))

    if not ingredients or not steps:
        return None
    if "no recipe detected" in (name or "").lower():
        return None
    data.update({
        "name": name or "Untitled recipe",
        "recipeIngredient": ingredients,
        "recipeInstructions": [{"@type": "HowToStep", "text": s} for s in steps],
    })
    if description:
        data["description"] = " ".join(description)
    m = re.search(r"^Source:\s*(https?://\S+)", markdown, re.M)
    if m:
        data["url"] = m.group(1)
    return normalize_recipe(data)
