"""Caption parsing / transcript formatting tests."""

import json

from extractors.captions import (
    caption_track_to_text,
    dedupe_rolling,
    fmt_ts,
    parse_json3,
    parse_vtt,
    segments_from_engine,
    to_paragraphs,
)
from extractors.youtube import _pick_caption_track


ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000
number five

00:00:03.000 --> 00:00:05.000
number five
is Sol Ring

00:00:05.000 --> 00:00:07.000
is Sol Ring
and number five again

00:01:10.000 --> 00:01:12.000
number five
"""


def test_vtt_removes_rolling_repeats_but_keeps_real_repeats():
    segs = parse_vtt(ROLLING_VTT)
    texts = [t for _, t in segs]
    assert texts == ["number five", "is Sol Ring", "and number five again", "number five"]
    # The phrase repeated a minute later is kept (old parser dropped it).
    assert segs[-1][0] == 70.0


def test_json3_parsing_and_paragraphs():
    raw = json.dumps({"events": [
        {"tStartMs": 0, "segs": [{"utf8": "Welcome"}, {"utf8": " back"}]},
        {"tStartMs": 1500, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 12000, "segs": [{"utf8": "today we rank"}]},
        {"tStartMs": 31000, "segs": [{"utf8": "number ten"}]},
        {"tStartMs": 40000},
    ]})
    segs = parse_json3(raw)
    assert segs == [(0.0, "Welcome back"), (12.0, "today we rank"), (31.0, "number ten")]
    text = to_paragraphs(segs)
    assert text.splitlines() == ["[0:00] Welcome back today we rank", "[0:31] number ten"]


def test_caption_track_to_text_vtt():
    out = caption_track_to_text(ROLLING_VTT, "vtt")
    assert out.startswith("[0:01] number five is Sol Ring")
    assert "[1:10] number five" in out


def test_dedupe_rolling_prefix():
    assert dedupe_rolling([(0, "a b"), (1, "a b c"), (2, "a b c")]) == [(0, "a b"), (1, "c")]


def test_fmt_ts_hours():
    assert fmt_ts(3725) == "1:02:05"
    assert fmt_ts(65) == "1:05"


def test_segments_from_engine_variants():
    assert segments_from_engine("plain text") == [(0.0, "plain text")]
    assert segments_from_engine({"text": "x", "segments": [{"start": 3.2, "text": " hi "}]}) == [(3.2, "hi")]
    assert segments_from_engine({"text": "fallback", "segments": []}) == [(0.0, "fallback")]


def _track(ext="json3"):
    return [{"ext": "vtt", "url": "v"}, {"ext": ext, "url": "j"}]


def test_pick_prefers_manual_then_original_auto():
    info = {
        "language": "en",
        "subtitles": {"de": _track()},
        "automatic_captions": {"en-orig": _track(), "en": _track(), "de": _track()},
    }
    track, lang, auto = _pick_caption_track(info, None)
    assert (lang, auto, track["ext"]) == ("en-orig", True, "json3")

    info["subtitles"]["en-US"] = _track()
    track, lang, auto = _pick_caption_track(info, None)
    assert (lang, auto) == ("en-US", False)


def test_pick_honours_requested_language():
    info = {"language": "en", "subtitles": {}, "automatic_captions": {"es": _track(), "en-orig": _track()}}
    _, lang, _ = _pick_caption_track(info, "es")
    assert lang == "es"


def test_pick_returns_none_without_tracks():
    assert _pick_caption_track({"subtitles": {}, "automatic_captions": {}}, None) is None
