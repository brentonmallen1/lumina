"""Tests for the LLM client/runner core (no real Ollama needed)."""

import asyncio
import json

import httpx
import pytest

from llm import client as client_mod
from llm.client import LLMEvent, OllamaClient
from llm.longform import merge_structured, split_body
from llm.prompts import render_template
from llm.runner import (
    ModelProfile,
    Runtime,
    build_source_header,
    parse_json_result,
    resolve_num_ctx,
    run_mode,
)


def run(coro):
    return asyncio.run(coro)


# ── Templates ────────────────────────────────────────────────────────────────

def test_render_template_handles_braces_and_escapes():
    assert render_template('JSON: {"a": 1} {content}', "X{y}") == 'JSON: {"a": 1} X{y}'
    assert render_template("{{literal}} {content}", "C") == "{literal} C"


def test_render_template_appends_when_placeholder_missing():
    out = render_template("Summarize this.", "BODY")
    assert out.endswith("BODY") and out.startswith("Summarize this.")


# ── Context resolution ──────────────────────────────────────────────────────

def test_num_ctx_defaults_to_model_max():
    p = ModelProfile(name="gemma4:e4b", context_length=131072)
    assert resolve_num_ctx({}, "gemma4:e4b", p) == 131072


def test_num_ctx_override_and_cap():
    p = ModelProfile(name="m", context_length=262144)
    settings = {"ollama_context_overrides": json.dumps({"m": 65536})}
    assert resolve_num_ctx(settings, "m", p) == 65536
    settings["ollama_context_cap"] = "32768"
    assert resolve_num_ctx(settings, "m", p) == 32768


def test_num_ctx_fallback_when_unknown():
    assert resolve_num_ctx({}, "m", ModelProfile(name="m")) == 32768


# ── Source header ────────────────────────────────────────────────────────────

def test_source_header_includes_chapters_and_description():
    h = build_source_header({
        "title": "Top 3 things",
        "uploader": "Chan",
        "duration": 3725,
        "upload_date": "20260102",
        "chapters": [{"start_time": 0, "title": "Intro"}, {"start_time": 75, "title": "#3"}],
        "description": "desc",
    })
    assert "Title: Top 3 things" in h
    assert "Duration: 1:02:05" in h
    assert "Published: 2026-01-02" in h
    assert "[1:15] #3" in h
    assert h.rstrip().endswith("## Content")


# ── Client payloads ──────────────────────────────────────────────────────────

def _mock_ollama(monkeypatch, lines, captured):
    def handler(request: httpx.Request):
        captured.append(json.loads(request.content))
        body = "\n".join(json.dumps(l) for l in lines)
        return httpx.Response(200, text=body)

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", factory)


def test_generate_stream_sends_native_think_and_splits_thinking(monkeypatch):
    captured = []
    _mock_ollama(monkeypatch, [
        {"thinking": "hmm", "response": ""},
        {"response": "Hello"},
        {"response": "", "done": True, "done_reason": "stop", "prompt_eval_count": 10},
    ], captured)

    async def go():
        c = OllamaClient("http://x")
        return [e async for e in c.generate_stream("p", "m", "sys", think=True, options={"num_ctx": 4096})]

    events = run(go())
    assert [e.kind for e in events] == ["thinking", "text", "done"]
    payload = captured[0]
    assert payload["think"] is True
    assert payload["system"] == "sys"  # no <|think|> injection
    assert "token_budget" not in payload["options"]
    assert payload["options"]["num_ctx"] == 4096


# ── Runner ───────────────────────────────────────────────────────────────────

class FakeClient:
    """Stands in for OllamaClient.generate_stream; records calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.base_url = "http://fake"

    async def generate_stream(self, prompt, model, system=None, *, images=None, think=None, options=None, format=None):
        self.calls.append({"prompt": prompt, "system": system, "think": think, "options": options, "format": format})
        text = self.responses.pop(0)
        yield LLMEvent("text", text)
        yield LLMEvent("done", stats={"done_reason": "stop"})


def make_rt(client, num_ctx=131072, output=32768, caps=("completion", "thinking")):
    return Runtime(
        client=client, model="gemma4:e4b",
        profile=ModelProfile(name="gemma4:e4b", context_length=num_ctx, capabilities=set(caps)),
        num_ctx=num_ctx, output_budget=output, thinking_enabled=True,
    )


async def _drain(gen):
    return [e async for e in gen]


@pytest.fixture(autouse=True)
def no_db_prompts(monkeypatch):
    # get_prompt() reads the DB first; force the built-in defaults.
    import db
    monkeypatch.setattr(db, "get_prompt_by_mode", lambda mode: None)


def test_run_mode_single_pass_uses_mode_sampling():
    fc = FakeClient(["A summary."])
    events = run(_drain(run_mode("content here", "summary", make_rt(fc))))
    assert events[-1]["type"] == "result"
    assert events[-1]["text"] == "A summary."
    call = fc.calls[0]
    assert call["think"] is True
    assert call["options"]["temperature"] == 0.7
    assert call["options"]["num_ctx"] == 131072
    assert call["options"]["num_predict"] == 32768


def test_think_omitted_for_models_without_capability():
    fc = FakeClient(["x"])
    run(_drain(run_mode("c", "summary", make_rt(fc, caps=("completion",)))))
    assert fc.calls[0]["think"] is None


def test_structured_mode_validates_json():
    fc = FakeClient(['```json\n{"name": "Pie", "recipeIngredient": [], "recipeInstructions": []}\n```'])
    events = run(_drain(run_mode("c", "recipe_jsonld", make_rt(fc))))
    result = events[-1]
    assert json.loads(result["text"])["name"] == "Pie"
    assert result["meta"]["data"]["name"] == "Pie"
    assert fc.calls[0]["format"] is not None
    assert fc.calls[0]["options"]["temperature"] == 0.1
    # Raw JSON isn't streamed to the UI.
    assert not any(e["type"] == "text" for e in events)


def test_structured_mode_retries_without_thinking_on_bad_json():
    fc = FakeClient(["not json", '{"name": "Pie", "recipeIngredient": [], "recipeInstructions": []}'])
    events = run(_drain(run_mode("c", "recipe_jsonld", make_rt(fc))))
    assert len(fc.calls) == 2
    assert fc.calls[1]["think"] is False
    assert json.loads(events[-1]["text"])["name"] == "Pie"


def test_long_content_goes_through_map_reduce():
    # Tiny context so the content can't fit in one pass.
    fc = FakeClient(["notes 1", "notes 2", "notes 3", "notes 4", "notes 5", "notes 6", "FINAL"])
    rt = make_rt(fc, num_ctx=4096, output=1024)
    body = "\n".join(f"[{i:02d}:00] line {i} " + "word " * 120 for i in range(40))
    events = run(_drain(run_mode(body, "summary", rt)))
    result = events[-1]
    assert result["meta"].get("longform") is True
    assert len(fc.calls) >= 3
    assert "notes" in fc.calls[-1]["prompt"]
    for call in fc.calls:  # every call fits the window
        assert len(call["prompt"]) / 3.5 < rt.num_ctx


# ── Longform helpers ─────────────────────────────────────────────────────────

def test_split_body_respects_size_and_lines():
    text = "\n".join("x" * 100 for _ in range(50))
    parts = split_body(text, 1000)
    assert len(parts) > 1
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(parts) == text  # no overlap requested → lossless


def test_merge_structured_dedupes_lists():
    merged = merge_structured([
        {"title": "T", "items": [{"title": "Sol Ring"}, {"title": "Arcane Signet"}]},
        {"title": "", "items": [{"title": "sol ring"}, {"title": "Command Tower"}]},
    ])
    assert merged["title"] == "T"
    assert [i["title"] for i in merged["items"]] == ["Sol Ring", "Arcane Signet", "Command Tower"]


def test_parse_json_result_from_prose():
    assert parse_json_result('Sure! {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
    assert parse_json_result("nope") is None


def test_modelfile_num_ctx_beats_architecture_max():
    p = ModelProfile(name="m", context_length=262144, modelfile_num_ctx=131072)
    assert resolve_num_ctx({}, "m", p) == 131072


def test_think_levels_for_gpt_oss_style_models():
    rt = make_rt(FakeClient([]))
    rt.profile.thinking_values = ["low", "medium", "high"]
    assert rt.think_param(True) is None      # model default
    assert rt.think_param(False) == "low"    # can't disable; use lowest
    rt.profile.thinking_values = [False, True]
    assert rt.think_param(False) is False


def test_parse_model_info_reads_modelfile_and_thinking():
    from llm.client import parse_model_info
    info = parse_model_info({
        "model_info": {"gemma4.context_length": 262144},
        "parameters": "num_ctx                        131072\ntemperature 1",
        "capabilities": ["completion", "thinking"],
        "thinking": {"values": [False, True], "default": True},
    })
    assert info["context_length"] == 262144
    assert info["modelfile_num_ctx"] == 131072
    assert info["thinking_values"] == [False, True]
