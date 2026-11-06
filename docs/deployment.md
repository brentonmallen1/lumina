# Deployment

Running Lumina with Docker Compose or on Unraid, plus GPU setup, volumes, updates and backups. ← [Back to README](../README.md)

## Docker Compose

The image is built from source. It has two stages that matter:

1. **Playwright base** — Chromium (for web pages) plus a static ffmpeg. It rarely changes, so it's built once and reused.
2. **App image** — CUDA runtime, Python 3.12 environment, the built React UI, and Deno (which yt-dlp needs for YouTube).

```bash
cp .env.example .env          # set OLLAMA_URL and OLLAMA_MODEL at least
just build-playwright-base    # once; rebuild only when Playwright or ffmpeg change
just up                       # build the app image and start it in the background
just logs                     # follow the logs
```

Without `just`:

```bash
docker buildx build --platform linux/amd64 -f backend/Dockerfile.playwright-base \
  --build-arg PLAYWRIGHT_VERSION=<version from backend/uv.lock> -t lumina:playwright-base --load .
docker compose up -d --build
```

If `DOCKER_REGISTRY` is set in `.env`, `just build-playwright-base` pushes the base to `<registry>:playwright-base`, and the app build pulls it from there. `just release` builds and pushes `<registry>:latest` and a dated tag.

Open `http://<host>:8880`. On first start the container downloads the configured transcription model into the models volume; later starts reuse it. The page shows a loading screen until the engine is ready. `/api/ready` reports progress, and the compose healthcheck uses it.

### Reaching Ollama

`OLLAMA_URL` must be reachable **from inside the container**. `localhost` there means the container itself. Use your host's LAN IP, `http://host.docker.internal:11434` (Docker Desktop, or add `extra_hosts: ["host.docker.internal:host-gateway"]` on Linux), or an Ollama container on the same network.

## GPU

1. Install the NVIDIA Container Toolkit on the host:

   ```bash
   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
     | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
   curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
     | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
     | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
   sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
   sudo nvidia-ctk runtime configure --runtime=docker
   sudo systemctl restart docker
   ```

2. Set `ENABLE_GPU=true` in `.env`. The `just` recipes and `start.sh` then add `docker-compose.gpu.yml`.
3. For faster-whisper on GPU, `COMPUTE_TYPE=float16` or `int8_float16` is a good choice.

For the Canary engine, build with the NeMo extra: `just release-canary`, or add `-f docker-compose.canary.yml`.

## Unraid

A template lives at [`unraid/lumina.xml`](../unraid/lumina.xml). Copy it to `/boot/config/plugins/dockerMan/templates-user/` on your server, then pick it under **Docker → Add Container → Template**.

- Set **Repository** to the image you pushed with `just release` (e.g. `registry.example.com/lumina:latest`).
- Map the three paths: models, audio cache, app data. The image already points the app at `/models`, `/cache/audio` and `/data`, so the database and models survive updates.
- Set **Ollama URL** to your Ollama server's LAN address and pick a model.
- The template passes `--gpus all`. Remove it from *Extra Parameters* on a CPU-only server.
- Advanced fields cover the LLM output budget, context cap, job concurrency and upload limits.

## Volumes

| Container path | Holds | Back up? |
|---|---|---|
| `/data` | SQLite database (settings, prompts, history, jobs, cache), MTG card cache | **Yes** |
| `/models` | Whisper/HuggingFace/TTS weights | No; re-downloadable |
| `/cache/audio` | Uploaded audio, cleaned up after `AUDIO_CACHE_TTL_HOURS` | No |

To back up, stop the container (or run `sqlite3 /data/app.db ".backup app.db.bak"`) and copy the `/data` folder.

## Updating

```bash
git pull
just restart                  # rebuilds and restarts
```

Database migrations run automatically on start. Settings retired by an update are removed; for example, the old fixed 32K context setting gave way to per-model context.

## Reverse proxy

Lumina is a single HTTP service on port 8000 inside the container. Streaming responses use Server-Sent Events. If your proxy buffers responses, turn buffering off for `/api/` (the app already sends `X-Accel-Buffering: no` for nginx). Enable Basic Auth or an API key before exposing it beyond your LAN.
