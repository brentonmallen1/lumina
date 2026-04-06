"""
Default summarization prompt templates.

Each mode has a system prompt and a user template with a `{content}` placeholder.
These are hardcoded defaults; a CRUD UI for custom prompts is planned for Phase 5.
"""

PROMPTS: dict[str, dict[str, str]] = {
    "summary": {
        "name": "Summary",
        "system": (
            "You are a precise summarization assistant. "
            "Create clear, well-structured summaries that capture the essential meaning and key details. "
            "Be concise but comprehensive. Use natural prose."
        ),
        "template": (
            "Summarize the following content clearly and concisely:\n\n"
            "{content}"
        ),
    },
    "key_points": {
        "name": "Key Points",
        "system": (
            "You are an expert at extracting the most important information from content. "
            "Identify the key ideas, insights, facts, and takeaways. "
            "Be specific and actionable."
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
            "You are an expert at organizing information hierarchically. "
            "Create clear, structured mind map outlines using markdown heading and bullet syntax. "
            "Group related concepts together and show relationships between ideas."
        ),
        "template": (
            "Create a hierarchical mind map outline for the following content. "
            "Use markdown headings (##, ###) for main topics and bullets for subtopics:\n\n"
            "{content}"
        ),
    },
}

# Modes available in Phase 3. Q&A and Action Items come in Phase 5.
AVAILABLE_MODES = list(PROMPTS.keys())


def get_prompt(mode: str) -> dict[str, str]:
    """Return the prompt template for a mode, falling back to summary."""
    return PROMPTS.get(mode, PROMPTS["summary"])
