# HTTP API

Every tool in the UI is an HTTP endpoint on the same port. Interactive OpenAPI docs are served at **`/docs`**. ← [Back to README](../README.md)

## Authentication

- **API key**: set one in Settings → Security (or `API_KEY`), then send `Authorization: Bearer <key>` or `X-API-Key: <key>`. It works whether or not Basic Auth is enabled.
- **Basic Auth**: when `AUTH_ENABLED=true`, standard HTTP Basic credentials also work.
- With neither configured, the API is open. That suits an isolated LAN.

```bash
export LUMINA=http://localhost:8880
export KEY=$(openssl rand -hex 32)   # then paste it into Settings → Security
```

## Streaming (SSE)

The summarize, chat and translate endpoints stream [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events). Each event is `data: <json>`, and the stream ends with `data: [DONE]`.

| Event | Meaning |
|---|---|
| `{"phase", "detail"}` | Progress: `extracting`, `transcribing`, `thinking` |
| `{"reasoning"}` | A chunk of model reasoning (thinking models) |
| `{"text"}` | A chunk of the answer |
| `{"reset": true}` | Discard the streamed text (a structured-output retry is starting) |
| `{"warning"}` / `{"notice"}` | Non-fatal: truncation, output limit, context compression |
| `{"extracted_content"}` | The full source text with its header, for chat |
| `{"result", "meta"}` | The final, authoritative result. Structured modes return JSON text here. |
| `{"error"}` | Terminal error |

## Summarize

| Method | Path | Body | Description |
|---|---|---|---|
| `POST` | `/api/summarize` | `{content, mode, model?, title?, options?}` | Plain text. |
| `POST` | `/api/summarize/url` | `{source: "youtube"\|"url", url, mode, prefer_captions?, refresh?, options?}` | YouTube or a web page. Extractions are cached; `refresh: true` re-fetches. |
| `POST` | `/api/summarize/file` | form: `file`, `source` (`audio`\|`pdf`), `mode`, `enhance_*` | Audio, video or PDF upload. |
| `POST` | `/api/summarize/image` | form: `file`, `mode` | Image, read by a vision model. |
| `POST` | `/api/recipe/jsonld` | `{recipe_markdown, source_url?, image?}` | Markdown → normalized schema.org JSON-LD. Parsed in code for Lumina's recipe layout, otherwise via the LLM; the `X-Converted-By` header says which. |
| `POST` | `/api/recipe/markdown` | `{recipe}` | schema.org JSON-LD → Markdown (code, instant). |

Modes are listed by `GET /api/prompts`; each prompt carries an `output_type` (`markdown`, `mindmap`, `json:list`, `json:recipe`, `json:mtg`). `options` carries mode-specific inputs, e.g. `{"decklist": "1 Sol Ring\n…"}` for `mtg_precon`.

```bash
# Ranked list from a YouTube video
curl -N -X POST "$LUMINA/api/summarize/url" -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"source": "youtube", "url": "https://youtu.be/…", "mode": "extract_list"}'

# Meeting minutes from a recording
curl -N -X POST "$LUMINA/api/summarize/file" -H "X-API-Key: $KEY" \
  -F "file=@meeting.mp3" -F "source=audio" -F "mode=meeting_minutes"
```

## Background jobs

YouTube and URL summaries from the UI, transcriptions, and podcast episodes run in a persistent queue. Jobs survive restarts and are limited by `MAX_CONCURRENT_JOBS`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/jobs` | Create a job: `{job_type, source_type, source_ref, source_title?, config}`. Types: `summarize`, `extract`, `transcribe`, `enhance`, `download`, `feed_episode`. |
| `POST` | `/api/jobs/batch` | `{urls: [...], job_type?, config?}` |
| `GET` | `/api/jobs` | List jobs. Results are previews (2,000 chars, `result_truncated`); filter with `status`, `type`, `batch_id`, `limit`. |
| `GET` | `/api/jobs/{id}` | Full job, including `result_meta` (reasoning, warnings, source text). While running, `result` holds the partial output. |
| `GET` | `/api/jobs/active` | `{running, queued}` counts. |
| `DELETE` | `/api/jobs/{id}` | Cancel; a running summary stops at its next progress update. |
| `POST` | `/api/jobs/{id}/retry` | Re-queue a failed or cancelled job. |
| `DELETE` | `/api/jobs/batch/{batch_id}` | Cancel a batch. |

```bash
curl -X POST "$LUMINA/api/jobs" -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"job_type": "summarize", "source_type": "youtube", "source_ref": "https://youtu.be/…",
       "config": {"mode": "mtg_precon", "options": {"decklist": ""}}}'
```

## Transcription

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/transcribe` | Upload audio or video (form `file`, optional `enhance_*`). Returns `{job_id}`. |
| `GET` | `/api/status/{job_id}` | `{status, result, segments, language, error}` |
| `GET` | `/api/export/{job_id}` | Transcript as `.txt` |
| `GET` | `/api/export/{job_id}/srt` · `/vtt` | Subtitles |
| `GET` | `/api/audio/{job_id}` | The original audio |
| `POST` | `/api/clip/{job_id}` | `{start, end, format}`. Cuts a clip; download it from `/api/clip/{job_id}/{clip_id}/download`. |
| `POST` | `/api/diarize/{job_id}` | Speaker labels (needs pyannote.audio and `HF_TOKEN`). |
| `POST` | `/api/retranscribe/{job_id}` | Transcribe a cached file again with new enhancement options. |
| `GET` | `/api/files` | Cached audio files. |

## Chat and translation

| Method | Path | Body |
|---|---|---|
| `POST` | `/api/chat` | `{content, messages: [{role, content}], model?}` |
| `POST` | `/api/translate` | `{text, target_language, source_language?}` |

## Audio tools

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/enhance` | Upload audio for enhancement; `/api/enhance/{id}/download` and `/original` return the files. |
| `POST` | `/api/pipeline` | Start a step-by-step enhancement session; apply steps with `/api/pipeline/{id}/step`, transcribe with `/api/pipeline/{id}/transcribe`. |
| `GET` | `/api/youtube/info?url=` | Video metadata. |
| `POST` | `/api/youtube/download` | Download video or audio; poll `/api/youtube/{id}`, fetch `/api/youtube/{id}/file`. |
| `POST` | `/api/tts/synthesize` | `{text, voice?}` → `audio/wav` |
| `GET` | `/api/tts/voices` · `/api/tts/status` | Voices and model status; `POST /api/tts/download` fetches weights (SSE). |

## Library

| Method | Path | Description |
|---|---|---|
| `GET` / `POST` / `PUT` / `DELETE` | `/api/prompts[/{id}]` | Prompt templates; `POST /api/prompts/reset` restores the built-ins. |
| `GET` | `/api/history` · `/api/history/search?q=` | Saved results; full-text search. |
| `GET` / `POST` / `DELETE` | `/api/feeds[/{id}]` | Podcast/RSS feeds; `POST /api/feeds/{id}/check` polls now. |
| `GET` / `DELETE` | `/api/cache[/{hash}]` | Extraction cache stats; delete an entry to force a refresh. |

## Integrations

| Method | Path | Body | Description |
|---|---|---|---|
| `POST` | `/api/integrations/mealie/test` | `{url?, token?}` | Check the Mealie URL and token (unsaved values allowed). Returns `{ok, message}`. |
| `POST` | `/api/integrations/mealie/recipes` | `{recipe \| markdown, source_url?, image?}` | Create a recipe in Mealie from schema.org JSON-LD (object or text) or from Markdown (converted first). Returns `{slug, url}`. |

## System

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/ready` | `{status: loading\|ready\|error, message}`. No auth when auth is disabled; used by the healthcheck. |
| `GET` | `/api/info` · `/api/capabilities` | Engine, model, GPU and engine availability. |
| `GET` / `PUT` | `/api/settings` | Settings. Secrets come back masked, and a masked value sent back leaves them unchanged. |
| `GET` | `/api/ollama/models` · `/api/ollama/model/{name}` | Installed models; per-model context, capabilities and the context Lumina will use. |
| `POST` | `/api/reload-engine` | Reload the transcription engine after changing it. |
