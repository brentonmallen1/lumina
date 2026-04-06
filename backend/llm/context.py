"""
Chat context management.

Handles the context window budget for multi-turn conversations:
  1. Source content (highest priority — always kept, truncated if huge)
  2. Recent messages (kept verbatim)
  3. Old messages (summarized to free up space)

Token estimation: 1 token ≈ 4 characters (rough but good enough for budget decisions).
"""

from __future__ import annotations

# ── Constants ─────────────────────────────────────────────────────────────────

# Target context budget in characters (~40k chars ≈ 10k tokens, safely under most models)
CONTEXT_BUDGET_CHARS = 40_000

# Max chars to keep for source content before truncating
SOURCE_CONTENT_LIMIT = 32_000

# Always keep at least this many recent message-pairs verbatim (user + assistant)
MIN_RECENT_PAIRS = 3

# History summary header injected when we compress old turns
_HISTORY_SUMMARY_HEADER = (
    "[Earlier conversation summary]\n"
    "{summary}\n"
    "[End of summary — continuing conversation]\n"
)


# ── Public API ────────────────────────────────────────────────────────────────

def build_system_prompt(content: str) -> tuple[str, bool]:
    """
    Build the system prompt for chat from source content.

    Returns (system_prompt, was_truncated).
    Truncates content if it exceeds SOURCE_CONTENT_LIMIT.
    """
    truncated = len(content) > SOURCE_CONTENT_LIMIT
    text = content[:SOURCE_CONTENT_LIMIT] if truncated else content

    prompt = (
        "You are a helpful assistant answering questions about the following content. "
        "Base your answers on this content. If the answer isn't in the content, say so clearly.\n\n"
        "--- BEGIN CONTENT ---\n"
        f"{text}\n"
        "--- END CONTENT ---"
    )
    if truncated:
        prompt += (
            "\n\n[Note: The content was truncated to fit the context window. "
            "You have the first portion of the full document.]"
        )
    return prompt, truncated


def estimate_chars(messages: list[dict]) -> int:
    """Estimate total character count across all messages."""
    return sum(len(m.get("content", "")) for m in messages)


async def prepare_messages(
    system_prompt: str,
    history: list[dict],
    ollama_client,
    model: str,
) -> tuple[list[dict], str | None]:
    """
    Build the final messages array to send to Ollama, compressing old history if needed.

    Args:
        system_prompt: The system message (includes source content).
        history:       All user/assistant turns so far (no system message).
        ollama_client: OllamaClient instance for generating the history summary.
        model:         Model name (used for summary generation).

    Returns:
        (messages, compression_notice)
        - messages: final list ready for /api/chat
        - compression_notice: human-readable notice to show in UI if history was compressed,
          or None if no compression was needed.
    """
    system_msg = {"role": "system", "content": system_prompt}
    system_chars = len(system_prompt)
    remaining_budget = CONTEXT_BUDGET_CHARS - system_chars

    if remaining_budget <= 0:
        # Source content alone fills the budget — only send very recent history
        recent = history[-MIN_RECENT_PAIRS * 2:]
        return [system_msg] + recent, "Content is very large — only the most recent messages are included."

    history_chars = estimate_chars(history)

    if history_chars <= remaining_budget:
        # Everything fits — no compression needed
        return [system_msg] + history, None

    # ── Need to compress ──────────────────────────────────────────────────────
    # Keep the last MIN_RECENT_PAIRS × 2 messages verbatim (pairs of user+assistant)
    keep_count  = MIN_RECENT_PAIRS * 2
    to_compress = history[:-keep_count] if len(history) > keep_count else []
    recent      = history[-keep_count:] if len(history) > keep_count else history

    if not to_compress:
        # Can't compress further — just send recent messages
        return [system_msg] + recent, "Some earlier messages were dropped to fit the context window."

    # Summarize old turns
    summary = await _summarize_history(to_compress, ollama_client, model)
    summary_msg = {
        "role":    "system",
        "content": _HISTORY_SUMMARY_HEADER.format(summary=summary),
    }

    compressed = [system_msg, summary_msg] + recent
    if estimate_chars(compressed) > CONTEXT_BUDGET_CHARS:
        # Still too big after compression — drop the summary too
        return [system_msg] + recent, "Earlier conversation was summarized to fit the context window."

    return compressed, "Earlier conversation was summarized to fit the context window."


# ── Internal ──────────────────────────────────────────────────────────────────

async def _summarize_history(turns: list[dict], ollama_client, model: str) -> str:
    """
    Use the LLM to compress a list of old chat turns into a brief summary.
    Falls back to a simple transcript if the model call fails.
    """
    # Build a simple transcript of the turns to summarize
    transcript_lines = []
    for m in turns:
        role = "User" if m["role"] == "user" else "Assistant"
        transcript_lines.append(f"{role}: {m['content']}")
    transcript = "\n\n".join(transcript_lines)

    prompt = (
        "Summarize the following conversation exchange in 3-5 sentences, "
        "preserving key facts, questions asked, and answers given. "
        "Be concise but complete.\n\n"
        f"{transcript}"
    )

    try:
        summary = await ollama_client.generate_sync(
            prompt=prompt,
            model=model,
            system="You are a helpful assistant that summarizes conversations.",
        )
        return summary.strip() or transcript[:500]
    except Exception:
        # If summarization fails, return a truncated transcript
        return transcript[:500] + ("…" if len(transcript) > 500 else "")
