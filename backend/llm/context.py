"""
Chat context management.

Budgets are derived from the resolved context window of the active model
(see ``runner.Runtime``) rather than fixed character limits:

  1. Source content (highest priority — kept whole when it fits; truncated
     only when it alone exceeds ~85% of the input budget)
  2. Recent messages (kept verbatim)
  3. Old messages (summarized to free up space)
"""

from __future__ import annotations

from .runner import CHARS_PER_TOKEN, Runtime, stream_pass

# Always keep at least this many recent message-pairs verbatim (user + assistant)
MIN_RECENT_PAIRS = 3

# Output reserved for a chat reply (smaller than the summarize budget — chat
# answers are short, and a smaller reservation leaves more room for source).
CHAT_OUTPUT_TOKENS = 8192

_HISTORY_SUMMARY_HEADER = (
    "[Earlier conversation summary]\n"
    "{summary}\n"
    "[End of summary — continuing conversation]\n"
)


def chat_output_tokens(rt: Runtime) -> int:
    return min(CHAT_OUTPUT_TOKENS, rt.output_budget)


def budget_chars(rt: Runtime) -> int:
    """Characters available for system prompt + history in a chat request."""
    tokens = max(1024, rt.num_ctx - chat_output_tokens(rt) - 512)
    return int(tokens * CHARS_PER_TOKEN)


def build_system_prompt(content: str, limit_chars: int) -> tuple[str, bool]:
    """Build the chat system prompt. Returns (system_prompt, was_truncated)."""
    truncated = len(content) > limit_chars
    text = content[:limit_chars] if truncated else content

    prompt = (
        "You are a helpful assistant answering questions about the following content. "
        "Base your answers on this content. If the answer isn't in the content, say so clearly. "
        "When the content has [mm:ss] timestamps, cite them for the parts you rely on.\n\n"
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
    return sum(len(m.get("content", "")) for m in messages)


async def prepare_messages(
    system_prompt: str,
    history: list[dict],
    rt: Runtime,
) -> tuple[list[dict], str | None]:
    """Build the final messages array, compressing old history if needed.

    Returns (messages, compression_notice_or_None).
    """
    budget = budget_chars(rt)
    system_msg = {"role": "system", "content": system_prompt}
    remaining_budget = budget - len(system_prompt)

    if remaining_budget <= 0:
        recent = history[-MIN_RECENT_PAIRS * 2:]
        return [system_msg] + recent, "Content is very large — only the most recent messages are included."

    if estimate_chars(history) <= remaining_budget:
        return [system_msg] + history, None

    keep_count = MIN_RECENT_PAIRS * 2
    to_compress = history[:-keep_count] if len(history) > keep_count else []
    recent = history[-keep_count:] if len(history) > keep_count else history

    if not to_compress:
        return [system_msg] + recent, "Some earlier messages were dropped to fit the context window."

    summary = await _summarize_history(to_compress, rt)
    summary_msg = {"role": "system", "content": _HISTORY_SUMMARY_HEADER.format(summary=summary)}

    compressed = [system_msg, summary_msg] + recent
    if estimate_chars(compressed) > budget:
        return [system_msg] + recent, "Earlier conversation was summarized to fit the context window."

    return compressed, "Earlier conversation was summarized to fit the context window."


async def _summarize_history(turns: list[dict], rt: Runtime) -> str:
    """Compress old chat turns into a brief summary (falls back to a snippet)."""
    transcript = "\n\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in turns
    )
    prompt = (
        "Summarize the following conversation exchange in 3-5 sentences, "
        "preserving key facts, questions asked, and answers given. "
        "Be concise but complete.\n\n"
        f"{transcript}"
    )
    try:
        text = ""
        async for ev in stream_pass(
            rt, system="You are a helpful assistant that summarizes conversations.",
            prompt=prompt, temperature=0.3, think=rt.think_param(False),
            num_predict=1024, forward_text=False, forward_thinking=False,
        ):
            if ev["type"] == "pass_done":
                text = ev["text"]
        return text.strip() or transcript[:500]
    except Exception:
        return transcript[:500] + ("…" if len(transcript) > 500 else "")
