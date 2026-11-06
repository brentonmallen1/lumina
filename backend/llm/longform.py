"""
Long-form processing for content that does not fit the context window.

Only used when ``runner.generate_for_mode`` estimates that the prompt exceeds
the runtime's input budget. Two strategies:

  * Prose modes (free text): map each part to dense notes, then run the real
    mode prompt over the combined notes (reducing again if the notes are
    themselves too long).
  * Structured modes (JSON schema): run the mode on every part with the same
    schema and merge the parsed objects in code.

The source header (title, description, chapters) is repeated for every part,
so each pass keeps the global context.
"""

from __future__ import annotations

import json
import re
from typing import AsyncIterator

from .prompts import render_template

NOTES_SYSTEM = (
    "You condense one part of a longer source into dense, faithful notes for a later step. "
    "Never invent anything. Preserve every name, number, ranking, list item, product or card name, "
    "quote, and [mm:ss] timestamp exactly as given."
)

NOTES_TEMPLATE = (
    "This is part {part} of {total} of a longer source. Write detailed notes covering everything in "
    "this part, in order, as bullet points. Keep timestamps in [mm:ss] form next to the points they "
    "belong to. Do not summarize away list items or specifics.\n\n{content}"
)

REDUCE_PREAMBLE = (
    "Note: the source was too long to read in one pass, so it was condensed into sequential notes "
    "(part 1 to {total}). Treat the notes as the full content.\n\n"
)

MAX_REDUCE_ROUNDS = 3


def split_body(text: str, max_chars: int, overlap_chars: int = 0) -> list[str]:
    """Split on line boundaries (then sentences, then hard cuts) into ≤ max_chars parts."""
    max_chars = max(1000, int(max_chars))
    if len(text) <= max_chars:
        return [text]

    units: list[str] = []
    for line in text.splitlines(keepends=True):
        if len(line) <= max_chars:
            units.append(line)
            continue
        for sent in re.split(r"(?<=[.!?])\s+", line):
            while len(sent) > max_chars:
                units.append(sent[:max_chars])
                sent = sent[max_chars:]
            if sent:
                units.append(sent + " ")

    parts: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) > max_chars:
            parts.append(current)
            tail = current[-overlap_chars:] if overlap_chars else ""
            current = tail + unit
        else:
            current += unit
    if current.strip():
        parts.append(current)
    return parts


def _norm_key(item) -> str:
    if isinstance(item, dict):
        for k in ("name", "title", "card", "text", "question"):
            if isinstance(item.get(k), str) and item[k].strip():
                return re.sub(r"[^a-z0-9]+", "", item[k].lower())
        return json.dumps(item, sort_keys=True)
    return re.sub(r"[^a-z0-9]+", "", str(item).lower())


def merge_structured(results: list) -> object:
    """Merge per-part JSON results: concatenate lists (de-duplicated by a
    normalised name/title), keep the first non-empty scalar, merge dicts."""
    results = [r for r in results if r is not None]
    if not results:
        return None
    if all(isinstance(r, list) for r in results):
        seen: set[str] = set()
        out = []
        for r in results:
            for item in r:
                k = _norm_key(item)
                if k not in seen:
                    seen.add(k)
                    out.append(item)
        return out
    if all(isinstance(r, dict) for r in results):
        merged: dict = {}
        keys: list[str] = []
        for r in results:
            for k in r:
                if k not in keys:
                    keys.append(k)
        for k in keys:
            vals = [r[k] for r in results if k in r]
            if any(isinstance(v, list) for v in vals):
                merged[k] = merge_structured([v for v in vals if isinstance(v, list)])
            elif any(isinstance(v, dict) for v in vals):
                merged[k] = merge_structured([v for v in vals if isinstance(v, dict)])
            else:
                merged[k] = next((v for v in vals if v not in (None, "", 0)), vals[0])
        return merged
    return results[0]


def _part_chars(rt, *fixed: str) -> int:
    from .runner import CHARS_PER_TOKEN, estimate_tokens
    overhead = sum(estimate_tokens(f) for f in fixed) + 400
    return int(max(2000, (rt.input_budget - overhead) * CHARS_PER_TOKEN))


async def run_longform(
    *,
    rt,
    mode: str,
    system: str,
    template: str,
    meta: dict,
    header: str,
    body: str,
    think: bool | None,
    forward_text: bool = True,
) -> AsyncIterator[dict]:
    from .runner import compose_document, estimate_tokens, parse_json_result, stream_pass

    schema = meta.get("format")

    # ── Structured: map with the same schema, merge in code ────────────────
    if schema:
        part_chars = _part_chars(rt, system, template, header)
        parts = split_body(body, part_chars, overlap_chars=min(1500, part_chars // 20))
        yield {"type": "status", "detail": f"Content is long — processing in {len(parts)} parts…"}
        results = []
        for i, part in enumerate(parts, 1):
            yield {"type": "status", "detail": f"Extracting from part {i} of {len(parts)}…"}
            doc = compose_document(header, f"(Part {i} of {len(parts)})\n{part}")
            async for ev in stream_pass(
                rt, system=system, prompt=render_template(template, doc),
                temperature=meta.get("temperature"), think=think, format=schema,
                forward_text=False, forward_thinking=False,
            ):
                if ev["type"] == "pass_done":
                    results.append(parse_json_result(ev["text"]))
                elif ev["type"] == "warning":
                    yield ev
        merged = merge_structured(results)
        if merged is None:
            yield {"type": "warning", "message": "The model did not return valid JSON for any part."}
            yield {"type": "result", "text": "", "reasoning": "", "meta": {"parts": len(parts)}}
            return
        yield {
            "type": "result",
            "text": json.dumps(merged, indent=2, ensure_ascii=False),
            "reasoning": "",
            "meta": {"parts": len(parts), "data": merged},
        }
        return

    # ── Prose: map to notes, reduce with the real prompt ───────────────────
    current = body
    rounds = 0
    total_parts = 0
    while True:
        doc = compose_document(header, current)
        if estimate_tokens(system) + estimate_tokens(render_template(template, doc)) <= rt.input_budget:
            break
        if rounds >= MAX_REDUCE_ROUNDS:
            yield {"type": "warning", "message": "Content is extremely long; some detail may be lost."}
            break
        rounds += 1
        part_chars = _part_chars(rt, NOTES_SYSTEM, NOTES_TEMPLATE, header)
        parts = split_body(current, part_chars, overlap_chars=min(1000, part_chars // 25))
        total_parts = len(parts)
        yield {"type": "status", "detail": f"Content is long — reading it in {len(parts)} parts…"}
        notes: list[str] = []
        for i, part in enumerate(parts, 1):
            yield {"type": "status", "detail": f"Reading part {i} of {len(parts)}…"}
            notes_prompt = (
                NOTES_TEMPLATE.replace("{part}", str(i)).replace("{total}", str(len(parts)))
                .replace("{content}", compose_document(header, part))
            )
            async for ev in stream_pass(
                rt, system=NOTES_SYSTEM, prompt=notes_prompt, temperature=0.3,
                think=False if think is not None else None,
                num_predict=min(rt.output_budget, 4096),
                forward_text=False, forward_thinking=False,
            ):
                if ev["type"] == "pass_done":
                    notes.append(f"### Part {i}\n{ev['text'].strip()}")
        current = REDUCE_PREAMBLE.replace("{total}", str(len(parts))) + "\n\n".join(notes)

    yield {"type": "status", "detail": "Writing the final result…"}
    final_text, reasoning, stats = "", "", {}
    async for ev in stream_pass(
        rt, system=system, prompt=render_template(template, compose_document(header, current)),
        temperature=meta.get("temperature"), think=think,
        forward_text=forward_text, forward_thinking=forward_text,
    ):
        if ev["type"] == "pass_done":
            final_text, reasoning, stats = ev["text"], ev["reasoning"], ev["stats"]
        else:
            yield ev
    yield {
        "type": "result",
        "text": final_text,
        "reasoning": reasoning,
        "meta": {"parts": total_parts, "reduce_rounds": rounds, "stats": stats},
    }
