"""
Speaker diarization using pyannote.audio.

Requires:
  - pyannote.audio >= 3.0  (optional extra: uv sync --extra diarization)
  - A HuggingFace access token with access to the pyannote/speaker-diarization-3.1 model
    (user must accept model terms at https://huggingface.co/pyannote/speaker-diarization-3.1)
"""

from __future__ import annotations

from pathlib import Path


def check_available() -> tuple[bool, str]:
    """Return (available, reason) — whether diarization can be run."""
    try:
        import pyannote.audio  # noqa: F401
        return True, ""
    except ImportError:
        return False, "pyannote.audio is not installed (run: uv sync --extra diarization)"


def diarize(audio_path: str | Path, hf_token: str) -> list[dict]:
    """
    Run speaker diarization on an audio file.

    Returns a list of segments: [{"speaker": str, "start": float, "end": float}]
    """
    available, reason = check_available()
    if not available:
        raise RuntimeError(reason)
    if not hf_token:
        raise RuntimeError(
            "HuggingFace token is required for diarization. "
            "Set it in Settings → Security → HuggingFace Token."
        )

    from pyannote.audio import Pipeline
    import torch

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )
    pipeline = pipeline.to(device)

    diarization = pipeline(str(audio_path))

    segments: list[dict] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "speaker": speaker,
            "start":   round(turn.start, 3),
            "end":     round(turn.end, 3),
        })
    return segments


def merge_with_transcript(
    diarization: list[dict],
    transcript_segments: list[dict],
) -> list[dict]:
    """
    Assign speaker labels to transcript segments by mid-point overlap.

    Modifies transcript_segments in place, adding a "speaker" field to each segment.
    Returns the updated list.
    """
    for seg in transcript_segments:
        mid = (seg["start"] + seg["end"]) / 2
        seg["speaker"] = None
        for d in diarization:
            if d["start"] <= mid <= d["end"]:
                seg["speaker"] = d["speaker"]
                break
    return transcript_segments
