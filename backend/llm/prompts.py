"""
Default summarization prompt templates.

Each mode has a system prompt and a user template with a `{content}` placeholder.
These are the built-in defaults; they are seeded into the DB, where users can
override them from the Prompts page. Runtime properties that are *not*
user-editable (temperature, thinking, JSON schema, renderer) live in MODE_META.
"""

PROMPTS: dict[str, dict[str, str]] = {
    "summary": {
        "name": "Summary",
        "system": (
            "You are a precise summarization assistant. "
            "Create clear, well-structured summaries that capture the essential meaning and key details. "
            "Be concise but comprehensive. Use natural prose.\n\n"
            "Support your summary with citations and direct quotes:\n"
            "- Use bracketed numbers [1], [2] for inline citations\n"
            "- Use blockquotes for important direct quotes: > \"exact words\"\n"
            "- End with a References section listing each citation's source text\n\n"
            "Example:\n"
            "The project achieved its goals [1]. As the lead noted:\n"
            "> \"This exceeded all expectations.\"\n\n"
            "---\n\n"
            "**References**\n"
            "1. \"Project completed 2 weeks ahead of schedule\""
        ),
        "template": (
            "Summarize the following content clearly and concisely.\n\n"
            "If source information (title, chapters, description) is provided at the top, use it to understand "
            "the structure and subject. If the title or content indicates a \"top X\", ranked, or numbered list, "
            "include a **List Items** section after the summary with each item and a brief description.\n\n"
            "{content}"
        ),
    },
    "key_points": {
        "name": "Key Points",
        "system": (
            "You are an expert at extracting the most important information from content. "
            "Identify the key ideas, insights, facts, and takeaways. "
            "Be specific and actionable.\n\n"
            "For each key point, include a citation [1] referencing the source text. "
            "Use blockquotes for notable direct quotes: > \"exact words\"\n"
            "End with a References section listing each numbered citation's source text."
        ),
        "template": (
            "Extract the key points from the following content as a clear numbered list. "
            "Focus on the most important ideas, insights, and takeaways:\n\n"
            "{content}"
        ),
    },
    "mind_map": {
        "name": "Mind Map",
        "system": (
            "You are an expert at organizing information into clear hierarchical mind maps. "
            "Output ONLY a markdown outline — no prose, no preamble, no explanation. "
            "Use a single # heading for the central topic, ## for main branches, "
            "### for sub-branches, and - bullets for leaf nodes. "
            "Keep labels short (2-6 words). Group related ideas together."
        ),
        "template": (
            "Create a mind map outline for the following content.\n\n"
            "Rules:\n"
            "- Start with exactly ONE # heading (the central topic)\n"
            "- Use ## for 3-6 main branches\n"
            "- Use ### and - bullets for details under each branch\n"
            "- Labels must be short (2-6 words each)\n"
            "- Output ONLY the markdown outline, nothing else\n\n"
            "{content}"
        ),
    },
    "action_items": {
        "name": "Action Items",
        "system": (
            "You are an expert at identifying actionable tasks and next steps from any content. "
            "Extract concrete, specific actions — things someone must actually do. "
            "Ignore background context and focus only on tasks with a clear owner or outcome."
        ),
        "template": (
            "Extract all action items, tasks, and next steps from the following content. "
            "Format as a numbered list. Each item should be concrete and start with a verb. "
            "Group by owner or category if relevant:\n\n"
            "{content}"
        ),
    },
    "q_and_a": {
        "name": "Q&A",
        "system": (
            "You are an expert at generating insightful questions and clear answers from content. "
            "Create a concise Q&A that captures the key ideas, facts, and concepts. "
            "Questions should be natural and informative; answers should be direct and complete.\n\n"
            "Support answers with citations [1] and direct quotes where relevant. "
            "Use blockquotes for direct quotes: > \"exact words\"\n"
            "End with a References section listing the source text for each citation."
        ),
        "template": (
            "Generate a Q&A from the following content. "
            "Format as a numbered list of question-and-answer pairs. "
            "Cover the most important topics and concepts:\n\n"
            "{content}"
        ),
    },
    "tldr": {
        "name": "TL;DR",
        "system": (
            "You are a summarization assistant. Produce ultra-brief, scannable summaries. "
            "No filler, no citations, no lengthy prose — only the core ideas."
        ),
        "template": (
            "Summarize the following in 250 words or less as a bulleted list of core ideas.\n"
            "- One bullet per idea, kept to one sentence\n"
            "- No citations, quotes, or filler phrases\n"
            "- If this is a \"top X\" or ranked list, list the items\n"
            "- Prioritize the most actionable or surprising takeaways\n\n"
            "{content}"
        ),
    },
    "extract_list": {
        "name": "Extract List",
        "system": (
            "You extract ranked or enumerated lists (top-X countdowns, rankings, 'N best/worst', "
            "numbered tips) from content. You are exhaustive and precise: every item, in the "
            "original order, with the exact names used in the content. You output JSON only."
        ),
        "template": (
            "Find the ranked or numbered list in the content below.\n\n"
            "Use every signal available:\n"
            "- The title often states the count (\"Top 15 …\") — set expected_count from it.\n"
            "- Chapters, when present, frequently name each list item; use them to confirm items and timestamps.\n"
            "- In transcripts, items are announced with phrases like \"number 7\", \"at number 3\", "
            "\"coming in at\", \"and the number one spot goes to\".\n"
            "- The description sometimes repeats the full list.\n\n"
            "Rules:\n"
            "- Include EVERY item; do not stop early. Keep the order used in the content "
            "(countdowns stay countdowns).\n"
            "- rank: the number the content gives the item (null if unnumbered).\n"
            "- title: the item's name exactly as said/written (fix obvious caption misspellings of proper nouns).\n"
            "- detail: one sentence on what it is or why it ranked there.\n"
            "- timestamp: the [m:ss] marker where the item is introduced, as \"m:ss\" (null if unknown).\n"
            "- Put bonus / honorable-mention items in honorable_mentions, not items.\n"
            "- If there is no list, return found=false and empty arrays.\n\n"
            "{content}"
        ),
    },
    "recipe": {
        "name": "Recipe",
        "system": (
            "You extract and format recipes from content. "
            "Output a clean, well-structured recipe in markdown format. "
            "Be precise about quantities, temperatures, and timings. "
            "If the content is not a recipe, say so clearly."
        ),
        "template": (
            "Extract and format the recipe from the following content.\n\n"
            "Look for recipe data in these places (in order of priority):\n"
            "1. 'Structured data (schema.org)' section — authoritative ingredients/instructions from the webpage\n"
            "2. The 'Description' under Source information — a video description often has the official ingredients list\n"
            "3. Main content/transcript — spoken or written recipe details\n\n"
            "Cross-reference all sources. Note any discrepancies (e.g., different quantities, missing items).\n\n"
            "Accuracy rules:\n"
            "- Ingredients: include every ingredient with its quantity, unit AND preparation exactly as given "
            "(e.g. \"1 medium onion, diced\", \"2 cloves garlic, minced\"). Include ingredients that only appear "
            "in the steps (e.g. pasta water, salt for the water). Never invent a quantity — leave it out if unstated.\n"
            "- Steps: include EVERY step in the order it is done, one action per step, including small ones "
            "(adding butter, reserving pasta water, resting). Do not merge, summarize away, or skip steps. "
            "Keep the heat levels, temperatures and times that are mentioned.\n"
            "- Check before answering: every ingredient must appear in at least one step (say when and how it is "
            "added), and every ingredient used in a step must be in the ingredient list.\n"
            "- When structured data or a written recipe is present, follow it exactly and use the transcript only "
            "for tips; otherwise reconstruct the recipe from the transcript in the order it is cooked.\n\n"
            "Output the recipe in this exact markdown format:\n\n"
            "# [Recipe Title]\n\n"
            "[1-2 sentence description of the dish]\n\n"
            "**Prep time:** [X minutes]  \n"
            "**Cook time:** [X minutes]  \n"
            "**Servings:** [X servings]\n\n"
            "## Ingredients\n\n"
            "- [quantity] [ingredient]\n"
            "- [quantity] [ingredient]\n"
            "...\n\n"
            "## Instructions\n\n"
            "1. [Step with temperatures, times, and specific details]\n"
            "2. [Next step]\n"
            "...\n\n"
            "## Notes\n\n"
            "- [Any tips, variations, or discrepancies between sources]\n\n"
            "If the content does not contain a recipe, respond: \"No recipe detected in this content.\"\n\n"
            "{content}"
        ),
    },
    "recipe_jsonld": {
        "name": "Recipe (JSON-LD)",
        "system": (
            "You extract recipes and output them as schema.org/Recipe JSON-LD. "
            "Output ONLY valid JSON — no markdown code blocks, no explanation. "
            "Be precise about quantities, temperatures, and timings. "
            "Use ISO 8601 duration format for times (e.g., PT15M for 15 minutes, PT1H for 1 hour)."
        ),
        "template": (
            "Extract the recipe from the following content and output it as schema.org/Recipe JSON-LD.\n\n"
            "Look for recipe data in these places (in order of priority):\n"
            "1. 'Structured data (schema.org)' section — authoritative ingredients/instructions from the webpage\n"
            "2. The 'Description' under Source information — a video description often has the official ingredients list\n"
            "3. Main content/transcript — spoken or written recipe details\n\n"
            "Accuracy rules:\n"
            "- Ingredients: include every ingredient with its quantity, unit AND preparation exactly as given "
            "(e.g. \"1 medium onion, diced\", \"2 cloves garlic, minced\"). Include ingredients that only appear "
            "in the steps (e.g. pasta water, salt for the water). Never invent a quantity — leave it out if unstated.\n"
            "- Steps: include EVERY step in the order it is done, one action per step, including small ones "
            "(adding butter, reserving pasta water, resting). Do not merge, summarize away, or skip steps. "
            "Keep the heat levels, temperatures and times that are mentioned.\n"
            "- Check before answering: every ingredient must appear in at least one step (say when and how it is "
            "added), and every ingredient used in a step must be in the ingredient list.\n"
            "- When structured data or a written recipe is present, follow it exactly and use the transcript only "
            "for tips; otherwise reconstruct the recipe from the transcript in the order it is cooked.\n\n"
            "Output a single JSON object with these exact fields:\n"
            '- "@context": "https://schema.org"\n'
            '- "@type": "Recipe"\n'
            '- "name": recipe title (string)\n'
            '- "description": 1-2 sentence description (string)\n'
            '- "prepTime": ISO 8601 duration like "PT15M" (string or null)\n'
            '- "cookTime": ISO 8601 duration like "PT1H" (string or null)\n'
            '- "totalTime": sum of prep + cook time (string or null)\n'
            '- "recipeYield": servings like "4 servings" (string or null)\n'
            '- "recipeIngredient": array of ingredient strings\n'
            '- "recipeInstructions": array of {{"@type": "HowToStep", "text": "..."}} — every step must include "@type": "HowToStep"\n\n'
            "If the content does not contain a recipe, output: "
            '{{"@context": "https://schema.org", "@type": "Recipe", "name": "No recipe detected", "description": "No recipe was found in this content.", "recipeIngredient": [], "recipeInstructions": []}}\n\n'
            "Output ONLY the JSON object, nothing else.\n\n"
            "{content}"
        ),
    },
    "mtg_precon": {
        "name": "MTG Precon Upgrade",
        "system": (
            "You are a Magic: The Gathering Commander expert. You read precon upgrade guides "
            "(videos or articles) and extract exactly which cards the author adds to the precon and "
            "which cards they cut. You know card names precisely and correct transcription errors "
            "(e.g. 'soul ring' → 'Sol Ring', 'arcane signit' → 'Arcane Signet'). You output JSON only."
        ),
        "template": (
            "Extract the precon upgrade from the content below.\n\n"
            "Use every signal:\n"
            "- Chapters often label each change (\"Cut 01\", \"Add 03\", \"Cards to Add\", \"Cards to Cut\") "
            "and give its timestamp.\n"
            "- The description may list the cards or the budget.\n"
            "- In the transcript, cuts sound like \"we're taking out\", \"cutting\", \"this goes\"; adds sound like "
            "\"we're adding\", \"bringing in\", \"my first pickup\".\n\n"
            "Rules:\n"
            "- cards_in: every card added to the deck. cards_out: every card removed from the precon.\n"
            "- Do NOT include cards that are only mentioned, compared, or listed as honorable mentions / "
            "'if you have a bigger budget' options — put those in honorable_mentions.\n"
            "- name: the exact official English card name.\n"
            "- reason: one short sentence, from the content, on why it's added or cut.\n"
            "- timestamp: the [m:ss] marker where the card is discussed, as \"m:ss\" (null if unknown).\n"
            "- replaces (cards_in only): the cut card it directly replaces, if the author pairs them; else null.\n"
            "- precon_name: the precon's product name (e.g. \"Doom Prevails\"); commander: the commander card name.\n"
            "- budget: the stated upgrade budget (e.g. \"$50\"), or null.\n\n"
            "{content}"
        ),
    },
    "meeting_minutes": {
        "name": "Meeting Minutes",
        "system": (
            "You are an expert meeting note-taker. Extract structured meeting minutes from transcripts. "
            "Your output must follow this exact format:\n\n"
            "## Meeting Minutes\n\n"
            "**Date:** [Infer from context or state \"Not specified\"]\n"
            "**Attendees:** [List names mentioned, or \"Not specified\"]\n\n"
            "### Key Discussion Points\n"
            "- [Main topics discussed]\n\n"
            "### Decisions Made\n"
            "- [Concrete decisions reached]\n\n"
            "### Action Items\n"
            "- [ ] [Task] — Owner: [Name if mentioned]\n\n"
            "### Next Steps\n"
            "- [Follow-up items, future meeting topics]\n\n"
            "Be concise. Only include items explicitly discussed. Do not invent attendees or decisions.\n\n"
            "Include citations [1] for decisions and commitments. "
            "Use blockquotes for notable direct quotes: > \"exact words spoken\"\n"
            "End with a References section with the exact source text for each citation."
        ),
        "template": (
            "Generate meeting minutes from the following transcript:\n\n"
            "{content}"
        ),
    },
}

AVAILABLE_MODES = list(PROMPTS.keys())


# ── Recipe JSON-LD conversion prompt (not a summarization mode) ────────────

RECIPE_JSONLD_PROMPT = {
    "system": (
        "You are a JSON converter. Convert recipe data to schema.org/Recipe JSON-LD format. "
        "Output ONLY valid JSON — no markdown code blocks, no explanation."
    ),
    "template": """Convert this recipe to schema.org/Recipe JSON-LD format:

{content}

Output a single JSON object with these exact fields:
- "@context": "https://schema.org"
- "@type": "Recipe"
- "name": recipe title (string)
- "description": 1-2 sentence description (string)
- "prepTime": ISO 8601 duration like "PT15M" (string or null)
- "cookTime": ISO 8601 duration like "PT1H" (string or null)
- "totalTime": sum of prep + cook time (string or null)
- "recipeYield": servings like "4 servings" (string or null)
- "recipeIngredient": array of ingredient strings
- "recipeInstructions": array of {{"@type": "HowToStep", "text": "..."}}

Output ONLY the JSON object.""",
}


# ── Per-mode runtime metadata ──────────────────────────────────────────────
#
# Prompt *text* is user-editable (stored in the DB); these runtime properties
# are not. A custom prompt for a built-in mode inherits that mode's metadata.
#
#   temperature  sampling temperature (extraction modes run cool)
#   think        True/False forces thinking on/off; None follows the global setting
#   format       JSON schema passed to Ollama structured outputs (None = free text)
#   output_type  how the frontend renders the result: markdown | mindmap | json:<renderer>

RECIPE_JSONLD_SCHEMA = {
    "type": "object",
    "properties": {
        "@context":           {"type": "string"},
        "@type":              {"type": "string"},
        "name":               {"type": "string"},
        "description":        {"type": "string"},
        "prepTime":           {"type": ["string", "null"]},
        "cookTime":           {"type": ["string", "null"]},
        "totalTime":          {"type": ["string", "null"]},
        "recipeYield":        {"type": ["string", "null"]},
        "recipeIngredient":   {"type": "array", "items": {"type": "string"}},
        "recipeInstructions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"@type": {"type": "string", "enum": ["HowToStep"]}, "text": {"type": "string"}},
                "required": ["@type", "text"],
            },
        },
    },
    # Normalized afterwards anyway (recipes/jsonld.py), but asking for the full
    # shape keeps the model's output closer to valid schema.org.
    "required": ["@context", "@type", "name", "recipeIngredient", "recipeInstructions"],
}

_LIST_ITEM = {
    "type": "object",
    "properties": {
        "rank":      {"type": ["integer", "null"]},
        "title":     {"type": "string"},
        "detail":    {"type": "string"},
        "timestamp": {"type": ["string", "null"]},
    },
    "required": ["title"],
}

EXTRACT_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "found":              {"type": "boolean"},
        "list_title":         {"type": "string"},
        "expected_count":     {"type": ["integer", "null"]},
        "items":              {"type": "array", "items": _LIST_ITEM},
        "honorable_mentions": {"type": "array", "items": _LIST_ITEM},
    },
    "required": ["found", "items"],
}

_MTG_CARD = {
    "type": "object",
    "properties": {
        "name":      {"type": "string"},
        "reason":    {"type": "string"},
        "timestamp": {"type": ["string", "null"]},
        "replaces":  {"type": ["string", "null"]},
    },
    "required": ["name"],
}

MTG_PRECON_SCHEMA = {
    "type": "object",
    "properties": {
        "precon_name":        {"type": ["string", "null"]},
        "commander":          {"type": ["string", "null"]},
        "budget":             {"type": ["string", "null"]},
        "cards_in":           {"type": "array", "items": _MTG_CARD},
        "cards_out":          {"type": "array", "items": _MTG_CARD},
        "honorable_mentions": {"type": "array", "items": _MTG_CARD},
    },
    "required": ["cards_in", "cards_out"],
}

DEFAULT_META: dict = {"temperature": 0.7, "think": None, "format": None, "output_type": "markdown"}

MODE_META: dict[str, dict] = {
    "summary":         {"temperature": 0.7},
    "key_points":      {"temperature": 0.6},
    "mind_map":        {"temperature": 0.5, "output_type": "mindmap"},
    "action_items":    {"temperature": 0.4},
    "q_and_a":         {"temperature": 0.6},
    "tldr":            {"temperature": 0.6},
    "extract_list":    {"temperature": 0.2, "format": EXTRACT_LIST_SCHEMA, "output_type": "json:list"},
    "recipe":          {"temperature": 0.3},
    "recipe_jsonld":   {"temperature": 0.1, "format": RECIPE_JSONLD_SCHEMA, "output_type": "json:recipe"},
    "meeting_minutes": {"temperature": 0.4},
    "mtg_precon":      {"temperature": 0.2, "format": MTG_PRECON_SCHEMA, "output_type": "json:mtg"},
}


def get_mode_meta(mode: str) -> dict:
    """Runtime metadata for a mode (defaults merged with the mode's overrides)."""
    return {**DEFAULT_META, **MODE_META.get(mode, {})}


def render_template(template: str, content: str) -> str:
    """Substitute ``{content}`` into a prompt template.

    Uses plain replacement (never str.format) so user templates containing
    literal braces — JSON examples, code — are safe. ``{{``/``}}`` escapes from
    the built-in templates are unescaped. A template without ``{content}`` gets
    the content appended, so a custom prompt can never silently drop the source.
    """
    marker = "\x00CONTENT\x00"
    if "{content}" in template:
        t = template.replace("{content}", marker)
    else:
        t = template.rstrip() + "\n\n" + marker
    t = t.replace("{{", "{").replace("}}", "}")
    return t.replace(marker, content)


def get_prompt(mode: str) -> dict[str, str]:
    """Return the prompt for a mode.

    Priority: custom DB prompt > default DB prompt > hardcoded fallback.
    Falls back to 'summary' if mode is unknown.
    """
    try:
        import db
        row = db.get_prompt_by_mode(mode)
        if row:
            return {
                "name":     row["name"],
                "system":   row["system_prompt"],
                "template": row["template"],
            }
    except Exception:
        pass  # DB not available — use hardcoded
    return PROMPTS.get(mode, PROMPTS["summary"])
