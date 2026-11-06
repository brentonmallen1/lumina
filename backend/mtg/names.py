"""Card-name normalisation and fuzzy matching against known card lists."""

from __future__ import annotations

import difflib
import re
import unicodedata

BASIC_LANDS = {
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "snowcoveredplains", "snowcoveredisland", "snowcoveredswamp",
    "snowcoveredmountain", "snowcoveredforest",
}


def name_key(name: str) -> str:
    """Case/punctuation/accents-insensitive key; DFCs keyed by their front face."""
    front = name.split("//")[0]
    norm = unicodedata.normalize("NFKD", front).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", norm.lower())


def is_basic_land(name: str) -> bool:
    return name_key(name) in BASIC_LANDS


def match_known(name: str, known: list[str], cutoff: float = 0.82, margin: float = 0.0) -> str | None:
    """Best match for a (possibly mis-transcribed) name among known card names.

    With ``margin`` > 0 the best candidate must also beat the runner-up by at
    least that much — used for loose matching, where a low cutoff alone would
    happily pick between two equally poor candidates.
    """
    if not known:
        return None
    key = name_key(name)
    by_key = {name_key(k): k for k in known}
    if key in by_key:
        return by_key[key]
    scored = sorted(
        ((difflib.SequenceMatcher(None, key, k).ratio(), k) for k in by_key),
        reverse=True,
    )
    if not scored or scored[0][0] < cutoff:
        return None
    if margin and len(scored) > 1 and scored[0][0] - scored[1][0] < margin:
        return None
    return by_key[scored[0][1]]
