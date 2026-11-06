# Engines and models

Transcription engines, model sizes, text-to-speech voices, and disk usage. ← [Back to README](../README.md)

## Transcription engines

Pick the engine in **Settings → Transcription** (or `TRANSCRIPTION_ENGINE`).

| Engine | Hardware | Notes |
|---|---|---|
| `faster-whisper` | CPU or GPU | **Default.** About 4× faster than openai-whisper (CTranslate2). Word-level timestamps. |
| `whisper` | CPU or GPU | Original OpenAI Whisper. Slower, widely compatible. |
| `canary` | GPU | NVIDIA NeMo Canary. Needs the canary build (`docker-compose.canary.yml`). |
| `qwen-audio` | GPU | Qwen2.5-Audio via HuggingFace. Highest VRAM requirement. |

The app loads one engine instance and shares it between the UI and background jobs.

### Whisper model sizes

Applies to `whisper` and `faster-whisper`.

| Size | VRAM | Notes |
|---|---|---|
| `tiny` | ~1 GB | Fastest, least accurate |
| `base` | ~1 GB | |
| `small` | ~2 GB | Good CPU choice |
| `medium` | ~5 GB | |
| `large-v3` | ~10 GB | Most accurate |
| `large-v3-turbo` | ~1.5 GB | **Default.** Close to large-v3 quality at a fraction of the cost. |

### Canary models

| Model | VRAM | Notes |
|---|---|---|
| `nvidia/canary-qwen-2.5b` | ~6 GB | English only. |
| `nvidia/canary-1b` | ~4 GB | English, Spanish, French, German. |

### Qwen Audio models

| Model | VRAM | Notes |
|---|---|---|
| `Qwen/Qwen2.5-Audio-3B-Instruct` | ~8 GB | Default. |
| `Qwen/Qwen2.5-Audio-7B-Instruct` | ~16 GB | Higher quality if VRAM allows. |

## LLM (Ollama)

Any Ollama model works. Lumina reads each model's capabilities from Ollama:

- **Thinking** models (gemma4, qwen3, gpt-oss, deepseek-r1, …) get Ollama's native `think` option. Models with named levels, like gpt-oss, use their default level, or their lowest when thinking is off.
- **Vision** models (gemma4, qwen2.5-vl, llava, …) are used for images and for reading PDFs page by page.
- **Context length** comes from the model, or from the Modelfile's `num_ctx` for variants such as `gemma4:31b-128k`. See [Configuration](configuration.md#ollama-llm).

## Text to speech

Lumina uses [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), an 82M-parameter offline TTS model, with 28 English voices:

| Group | Count | Examples |
|---|---|---|
| American female (`af_`) | 11 | Bella, Nova, Sarah, Sky, Alloy, Heart |
| American male (`am_`) | 9 | Michael, Fenrir, Adam |
| British female (`bf_`) | 4 | Emma, Isabella, Alice, Lily |
| British male (`bm_`) | 4 | George, Fable, Daniel, Lewis |

Download the weights (~330 MB) from **Settings → Text to Speech**, where you can preview voices. **Read Aloud** then appears on Summarize results and translations, and the **Text to Speech** tool synthesizes free-form text to `.wav`.

## Disk space

| Component | Size |
|---|---|
| Docker image (CUDA + Python + Chromium) | ~8 GB |
| faster-whisper `large-v3-turbo` | ~1.6 GB |
| faster-whisper `large-v3` | ~3 GB |
| `nvidia/canary-qwen-2.5b` | ~6 GB |
| `nvidia/canary-1b` | ~4 GB |
| `Qwen2.5-Audio-3B` | ~8 GB |
| `Qwen2.5-Audio-7B` | ~15 GB |
| Kokoro TTS (model + 28 voices) | ~660 MB |

Weights live in the models volume and survive rebuilds.
