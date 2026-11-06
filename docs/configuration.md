# Configuration

Every setting Lumina reads, and where each one comes from. ← [Back to README](../README.md)

## How settings work

Lumina keeps its runtime settings in SQLite (`/data/app.db` in Docker). On the very first start, environment variables (from `.env` or your container template) **seed** that database. After that, the **Settings** page is the source of truth: changes apply immediately, with no restart (changing the transcription engine prompts you to reload it).

A few values are read on every start instead. They are marked **deploy** below.

Secrets (password, API key, HuggingFace token, YouTube cookies) are never sent back to the browser. The Settings page shows `••••••••` for a stored secret and leaves it unchanged unless you type a new one.

## Ollama (LLM)

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Your Ollama server. From Docker on the same host, use `http://host.docker.internal:11434` or the host's LAN IP. |
| `OLLAMA_MODEL` | *(blank)* | Model for summaries, extraction and chat, e.g. `gemma4`, `gemma4:31b`, `qwen3`. |
| `OLLAMA_TIMEOUT` | `120` | Seconds to wait for the next streamed token before giving up. |
| `OLLAMA_THINKING_ENABLED` | `true` | Use the model's native reasoning (Ollama's `think` option). It's ignored for models that don't support thinking. Reasoning appears in a collapsible panel. |
| `OLLAMA_OUTPUT_BUDGET` | `32768` | Tokens reserved for each reply, reasoning included. It's also the generation limit. |
| `OLLAMA_CONTEXT_OVERRIDES` | `{}` | JSON map of per-model context windows, e.g. `{"gemma4:31b": 131072}`. Easier to set in Settings → Ollama. |
| `OLLAMA_CONTEXT_CAP` | *(blank)* | Upper limit on the context window for every model. Use it to fit a smaller GPU. |
| `OLLAMA_VISION_OVERRIDE` | `false` | Treat the model as vision-capable even if Ollama doesn't report it. |

**Context window.** For each model Lumina asks Ollama for its details, then uses, in order:

1. your per-model override;
2. the `num_ctx` set in the model's Modelfile (for variants like `gemma4:31b-128k`);
3. the model's maximum context.

The optional global cap is applied last. In Settings → Ollama these are sliders with stops from 8K up to the model's maximum, with the default stop marked. The window stays fixed per model, so Ollama never reloads the model between requests. Content that doesn't fit is processed in parts automatically (see [Modes](modes.md#long-content)). Larger windows use more VRAM. If Ollama runs out of memory, slide that model's window down a stop or two.

## Transcription

| Variable | Default | Description |
|---|---|---|
| `TRANSCRIPTION_ENGINE` | `faster-whisper` | `faster-whisper`, `whisper`, `canary` (GPU), or `qwen-audio` (GPU). See [Engines](engines.md). |
| `WHISPER_MODEL_SIZE` | `large-v3-turbo` | `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`. |
| `COMPUTE_TYPE` | `int8` | faster-whisper quantization: `int8` (CPU), `int8_float16`, `float16` (GPU), `float32`. |
| `LANGUAGE` | `en` | ISO 639-1 code, or blank to auto-detect. It also sets the preferred YouTube caption language. |
| `CANARY_MODEL` | `nvidia/canary-qwen-2.5b` | Model for the Canary engine. |
| `QWEN_MODEL` | `Qwen/Qwen2.5-Audio-3B-Instruct` | Model for the Qwen Audio engine. |

## Jobs, uploads and storage

| Variable | Default | Description |
|---|---|---|
| `MAX_CONCURRENT_JOBS` | `2` | Background jobs (transcriptions, YouTube/URL summaries, podcast episodes) that run at once. |
| `MAX_UPLOAD_SIZE_MB` | `500` | Largest upload, or podcast episode download, accepted. |
| `AUDIO_CACHE_TTL_HOURS` | `72` | Uploaded audio older than this is deleted hourly, except files that queued jobs still need. `0` keeps everything. |

Finished jobs and cached extractions (YouTube transcripts, web pages) are kept for 30 days.

## Access

| Variable | Default | Description |
|---|---|---|
| `AUTH_ENABLED` | `false` | Require HTTP Basic Auth for the UI and API. |
| `AUTH_USERNAME` | `admin` | Basic Auth username. |
| `AUTH_PASSWORD` | *(blank)* | Basic Auth password. It's required when auth is enabled. |
| `API_KEY` | *(blank)* | Token for scripts. Send it as `Authorization: Bearer <key>` or `X-API-Key: <key>`; it works with or without Basic Auth. |
| `CORS_ORIGINS` | *(blank)* | **deploy.** Comma-separated origins allowed to call the API from another site. Blank means same origin only. |

Auth is off by default, which suits a trusted LAN. Turn it on before exposing Lumina anywhere else.

## Audio enhancement and text to speech

| Variable | Default | Description |
|---|---|---|
| `ENHANCE_NORMALIZE` | `false` | Pre-select loudness normalization for new jobs. |
| `ENHANCE_DENOISE` | `false` | Pre-select noise reduction. |
| `ENHANCE_ISOLATE` | `false` | Pre-select vocal isolation. |
| `ENHANCE_UPSAMPLE` | `false` | Pre-select super-resolution. |
| `TTS_ENABLED` | `true` | Show Read Aloud buttons and the TTS tool. |
| `TTS_VOICE` | `af_bella` | Default Kokoro voice. |

## Integrations

| Variable | Default | Description |
|---|---|---|
| `HF_TOKEN` | *(blank)* | HuggingFace token for speaker diarization (pyannote.audio). |
| `YOUTUBE_COOKIES` | *(blank)* | Netscape-format cookies for YouTube, for age-restricted videos or rate limits. Easier to paste in Settings → YouTube. |
| `APP_NAME` | `Lumina` | Name shown in the Basic Auth prompt. |

## Deployment

All **deploy**, read by Docker Compose or the container on every start.

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `8880` | Host port for the UI and API. |
| `API_PORT` | — | Optional second host port for the API. Uncomment the matching line in `docker-compose.yml`. |
| `ENABLE_GPU` | `false` | Adds `docker-compose.gpu.yml` when you use `just` recipes or `start.sh`. |
| `NVIDIA_VISIBLE_DEVICES` | `all` | GPUs to expose, e.g. `0` or `0,1`. |
| `MODELS_VOLUME` | `./volumes/models` | Host path for model weights (mounted at `/models`). |
| `AUDIO_CACHE_VOLUME` | `./volumes/audio_cache` | Host path for uploaded audio (mounted at `/cache/audio`). |
| `DATA_VOLUME` | `./volumes/data` | Host path for the database (mounted at `/data`). |
| `DOCKER_REGISTRY` | *(blank)* | Registry used by `just release` and for the Playwright base image. Blank means build locally. |
| `DOCKER_TAG` | `latest` | Tag used by `just release`. |
| `TZ` | `UTC` | Container timezone. |

Inside the image, `DATA_DIR=/data`, `AUDIO_CACHE_DIR=/cache/audio`, `HF_HOME=/models/hf`, `WHISPER_DOWNLOAD_ROOT=/models/whisper` and `TORCH_HOME=/models/torch` are preset to match those mounts. You only need to change them for unusual layouts.
