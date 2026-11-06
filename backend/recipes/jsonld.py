"""
schema.org/Recipe JSON-LD normalization.

LLM output is close to valid but not reliably so. ``normalize_recipe`` turns
whatever the model produced into a clean Recipe object that recipe importers
(Mealie uses the ``recipe-scrapers`` library) accept:

  * guaranteed ``@context`` / ``@type`` / ``name``
  * ``recipeIngredient`` as a list of strings
  * ``recipeInstructions`` as ``HowToStep`` objects (sections flattened)
  * ISO 8601 durations ("1 hour 15 minutes" → "PT1H15M")
  * the source ``url``, an ``image`` (e.g. the YouTube thumbnail) and the
    ``author`` when the source provides them
  * empty / null fields removed
"""

from __future__ import annotations

import re

_DURATION_RE = re.compile(r"^P(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+S)?)?$")
_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)\b",
    re.I,
)


def iso_duration(value) -> str | None:
    """Coerce "15 minutes", "1 hr 30 min", 45, "PT1H" … to ISO 8601 (or None)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        minutes = int(value)
        return f"PT{minutes // 60}H{minutes % 60}M" if minutes >= 60 else f"PT{minutes}M"
    text = str(value).strip()
    if _DURATION_RE.match(text.upper()) and text.upper() not in ("P", "PT"):
        return text.upper()
    totals = {"D": 0.0, "H": 0.0, "M": 0.0, "S": 0.0}
    found = False
    for num, unit in _UNIT_RE.findall(text):
        found = True
        key = {"d": "D", "h": "H", "m": "M", "s": "S"}[unit[0].lower()]
        totals[key] += float(num)
    if not found:
        digits = re.fullmatch(r"\s*(\d+)\s*", text)
        if not digits:
            return None
        totals["M"] = float(digits.group(1))
    # Carry fractional hours into minutes (e.g. "1.5 hours").
    totals["M"] += (totals["H"] % 1) * 60
    totals["H"] = int(totals["H"])
    days, hours, minutes, seconds = int(totals["D"]), int(totals["H"]), int(round(totals["M"])), int(totals["S"])
    hours += minutes // 60
    minutes %= 60
    out = "P" + (f"{days}D" if days else "")
    time = (f"{hours}H" if hours else "") + (f"{minutes}M" if minutes else "") + (f"{seconds}S" if seconds else "")
    return out + ("T" + time if time else "") if (days or time) else None


def _text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("name") or "")
    return str(value).strip() if value is not None else ""


def _steps(value) -> list[dict]:
    """Instructions in any common shape → [{"@type": "HowToStep", "text": ...}]."""
    if value is None:
        return []
    if isinstance(value, str):
        lines = [re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", l).strip() for l in value.splitlines()]
        return [{"@type": "HowToStep", "text": l} for l in lines if l]
    if isinstance(value, dict):
        value = [value]
    steps: list[dict] = []
    for item in value:
        if isinstance(item, dict) and (item.get("@type") == "HowToSection" or "itemListElement" in item):
            steps.extend(_steps(item.get("itemListElement")))
            continue
        text = _text(item)
        if text:
            step = {"@type": "HowToStep", "text": text}
            if isinstance(item, dict) and item.get("name") and item.get("name") != text:
                step["name"] = _text(item["name"])
            steps.append(step)
    return steps


def _strings(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [l for l in value.splitlines()]
    return [s for s in (_text(v) for v in value) if s]


def normalize_recipe(data: dict, source_meta: dict | None = None) -> dict:
    """Return a clean schema.org Recipe dict. ``source_meta`` may carry
    ``url``, ``thumbnail``, ``uploader`` and ``title`` from the source."""
    if isinstance(data, dict) and isinstance(data.get("@graph"), list):
        data = next((n for n in data["@graph"] if isinstance(n, dict) and "Recipe" in str(n.get("@type"))), data)
    data = dict(data or {})
    meta = source_meta or {}

    recipe: dict = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": _text(data.get("name")) or meta.get("title") or "Untitled recipe",
    }
    for key in ("description", "recipeCategory", "recipeCuisine", "keywords"):
        val = data.get(key)
        if isinstance(val, list):
            val = ", ".join(_strings(val))
        if val:
            recipe[key] = _text(val)

    for key in ("prepTime", "cookTime", "totalTime"):
        dur = iso_duration(data.get(key))
        if dur:
            recipe[key] = dur
    if "totalTime" not in recipe and ("prepTime" in recipe or "cookTime" in recipe):
        total = sum(_minutes(recipe.get(k)) for k in ("prepTime", "cookTime"))
        if total:
            recipe["totalTime"] = iso_duration(total)

    yld = data.get("recipeYield")
    if isinstance(yld, list):
        yld = next((y for y in yld if y), None)
    if yld not in (None, ""):
        recipe["recipeYield"] = _text(yld) if not isinstance(yld, (int, float)) else f"{yld} servings"

    recipe["recipeIngredient"] = _strings(data.get("recipeIngredient") or data.get("ingredients"))
    recipe["recipeInstructions"] = _steps(data.get("recipeInstructions") or data.get("instructions"))

    image = data.get("image") or meta.get("thumbnail")
    if isinstance(image, dict):
        image = image.get("url")
    if isinstance(image, list):
        image = next((i if isinstance(i, str) else (i or {}).get("url") for i in image), None)
    if isinstance(image, str) and image.startswith(("http://", "https://")):
        recipe["image"] = image

    url = data.get("url") or meta.get("url")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        recipe["url"] = url
        if "image" not in recipe:
            # Every YouTube video has a thumbnail at a predictable address.
            from jobs.cache import extract_youtube_video_id
            vid = extract_youtube_video_id(url)
            if vid:
                recipe["image"] = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

    author = data.get("author") or meta.get("uploader")
    if isinstance(author, str) and author.strip():
        recipe["author"] = {"@type": "Person", "name": author.strip()}
    elif isinstance(author, dict) and author.get("name"):
        recipe["author"] = {"@type": author.get("@type", "Person"), "name": _text(author["name"])}

    if isinstance(data.get("nutrition"), dict):
        nutrition = {k: v for k, v in data["nutrition"].items() if v not in (None, "")}
        if nutrition:
            recipe["nutrition"] = {"@type": "NutritionInformation", **nutrition}

    return recipe


def _minutes(duration: str | None) -> int:
    if not duration:
        return 0
    m = re.match(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", duration)
    if not m:
        return 0
    d, h, mi = (int(x or 0) for x in m.groups())
    return d * 1440 + h * 60 + mi


def is_empty_recipe(recipe: dict) -> bool:
    return not recipe.get("recipeIngredient") and not recipe.get("recipeInstructions")
