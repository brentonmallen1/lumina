# Troubleshooting

Common problems and what to check first. ← [Back to README](../README.md)

## Summaries miss the end of a long video

Check the header badge next to the model name: it shows the context window in use. If it's small (8K–32K), raise it for that model in **Settings → Ollama**, or remove the global context cap. When content doesn't fit, Lumina processes it in parts and says so ("Reading part 2 of 4…"). A yellow warning means the input filled the window or the reply hit the output budget.

## Ollama runs out of memory, or a model loads slowly

The context window is the main VRAM cost after the weights. Set a smaller per-model context in Settings → Ollama, or a global cap. Lumina keeps one fixed window per model, so the model isn't reloaded between requests. If `ollama ps` shows a reload on every request, check that nothing else is calling the same model with a different `num_ctx`.

## Results include no reasoning / thinking does nothing

Thinking only applies to models whose Ollama metadata lists the `thinking` capability (Settings → Ollama shows capabilities). Update Ollama if a thinking model doesn't report it. Structured modes (lists, recipes, MTG) may skip visible reasoning when Ollama enforces the JSON schema.

## "Connection refused" to Ollama from Docker

`localhost` inside the container is the container itself. Use the host's LAN IP or `http://host.docker.internal:11434`. See [Deployment](deployment.md#reaching-ollama).

## YouTube: "Sign in to confirm", missing formats, or no captions

- Rebuild the image so yt-dlp and its Deno-based challenge solver are current: `just rebuild`.
- Paste browser cookies in **Settings → YouTube** for age-restricted videos or rate limiting.
- Untick *Use captions* to force audio transcription.

## A cached transcript is stale

Mode switches reuse the cached extraction. To re-fetch, call `/api/summarize/url` with `"refresh": true`, or delete the entry via `/api/cache/{hash}`. Entries also expire after 30 days unused.

## MTG mode: wrong or flagged cards

- Paste the upgraded decklist (with a `Cuts` section) for exact lists. This matters for Moxfield links, which can't be read automatically.
- "not in the precon list" means the host's cut didn't match the original precon. Usually it's a caption error the matcher couldn't resolve.
- "original precon list not found" usually means a brand-new precon that MTGJSON hasn't published yet. Cuts then aren't cross-checked.

## Settings reset after updating on Unraid

Older images didn't point the app at `/data`, so the database lived inside the container. Current images do. Make sure the **App Data** path is mapped to `/data`.

## Tests

```bash
just test          # backend (pytest, inside the project venv)
just check-ui      # frontend type-check
```
