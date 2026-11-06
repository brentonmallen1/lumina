"""
Caption / transcript formatting.

Turns YouTube caption tracks (json3 preferred, WebVTT fallback) and
Whisper-style segments into a timestamped transcript:

    [0:00] first ~30 seconds of speech …
    [0:31] next paragraph …

Timestamps let the LLM cite moments, map content to chapters, and let the UI
link straight into the video. Rolling auto-caption cues (where each cue
repeats the previous line) are de-duplicated against the *previous* cue only,
so genuinely repeated phrases elsewhere in the video are kept.
"""

from __future__ import annotations

import json
import re

PARAGRAPH_SECONDS = 30.0


def fmt_ts(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
    return re.sub(r"\s+", " ", text).strip()


# ── json3 (YouTube's native timed-text format) ────────────────────────────────

def parse_json3(raw: str | bytes) -> list[tuple[float, str]]:
    """Return [(start_seconds, text)] from a YouTube json3 caption track."""
    data = json.loads(raw)
    out: list[tuple[float, str]] = []
    for ev in data.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        text = _clean("".join(s.get("utf8", "") for s in segs))
        if not text:
            continue
        out.append((ev.get("tStartMs", 0) / 1000.0, text))
    return out


# ── WebVTT ────────────────────────────────────────────────────────────────────

_TS_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")


def _vtt_seconds(ts: str) -> float:
    m = _TS_RE.search(ts)
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000


def parse_vtt(vtt_text: str) -> list[tuple[float, str]]:
    """Return [(start_seconds, text)] from WebVTT, removing rolling-cue repeats."""
    out: list[tuple[float, str]] = []
    prev_lines: list[str] = []
    for block in re.split(r"\n{2,}", vtt_text.strip()):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "Kind:", "Language:")):
            continue
        timing = next((l for l in lines if "-->" in l), None)
        if timing is None:
            continue
        start = _vtt_seconds(timing.split("-->")[0])
        text_lines = [
            _clean(re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", l))
            for l in lines[lines.index(timing) + 1:]
        ]
        text_lines = [l for l in text_lines if l]
        # Auto captions roll: cue N repeats cue N-1's last line(s) on top.
        new_lines = [l for l in text_lines if l not in prev_lines]
        prev_lines = text_lines
        if new_lines:
            out.append((start, " ".join(new_lines)))
    return out


# ── Dedupe + paragraphs ───────────────────────────────────────────────────────

def dedupe_rolling(segments: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Drop text that merely repeats the end of the previous segment."""
    out: list[tuple[float, str]] = []
    prev = ""  # previous segment's full text (before trimming)
    for start, text in segments:
        full = text
        if text == prev:
            continue
        if prev and text.startswith(prev):
            text = text[len(prev):].strip()
        prev = full
        if text:
            out.append((start, text))
    return out


def to_paragraphs(segments: list[tuple[float, str]], seconds: float = PARAGRAPH_SECONDS) -> str:
    """Group segments into ~``seconds``-long paragraphs prefixed with [m:ss]."""
    paras: list[str] = []
    cur: list[str] = []
    cur_start: float | None = None
    for start, text in segments:
        if cur_start is None:
            cur_start = start
        elif start - cur_start >= seconds and cur:
            paras.append(f"[{fmt_ts(cur_start)}] {' '.join(cur)}")
            cur, cur_start = [], start
        cur.append(text)
    if cur and cur_start is not None:
        paras.append(f"[{fmt_ts(cur_start)}] {' '.join(cur)}")
    return "\n".join(paras)


def segments_from_engine(result) -> list[tuple[float, str]]:
    """Normalise a transcription engine result (dict with segments, or str)."""
    if isinstance(result, str):
        return [(0.0, result.strip())] if result.strip() else []
    segs = result.get("segments") or []
    out = [(float(s.get("start", 0) or 0), (s.get("text") or "").strip()) for s in segs]
    out = [(t, x) for t, x in out if x]
    if not out and result.get("text"):
        out = [(0.0, result["text"].strip())]
    return out


def caption_track_to_text(raw: str | bytes, ext: str) -> str:
    segments = parse_json3(raw) if ext == "json3" else parse_vtt(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
    return to_paragraphs(dedupe_rolling(segments))
