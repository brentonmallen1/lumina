# Modes

What each Summarize mode produces, and how Lumina handles YouTube, long content and the MTG precon mode. ← [Back to README](../README.md)

## Built-in modes

| Mode | Output | Notes |
|---|---|---|
| **Summary** | Prose with citations | Adds a *List Items* section when the source is a ranked list. |
| **TL;DR** | Short bullet list | 250 words or less. |
| **Key Points** | Numbered list | Each point cites the source. |
| **Action Items** | Task list | Grouped by owner when names are mentioned. |
| **Q&A** | Question and answer pairs | |
| **Mind Map** | Interactive diagram | Rendered with markmap; download as `.svg`. |
| **Meeting Minutes** | Structured notes | Attendees, decisions, action items, next steps. |
| **Extract List** | Structured list | Rank, title, one-line detail and timestamp for every item, plus honorable mentions. Warns when it finds fewer items than the title promises ("9 of 10"). |
| **Recipe** | Markdown or JSON-LD | See [Recipes](#recipes). |
| **MTG Precon Upgrade** | Add/Cut card lists | See [below](#mtg-precon-upgrade). |
| **Transcript / Raw Text** | The extracted text | No LLM. |

Each mode's prompt can be edited, or a new mode added, on the **Prompts** page. Runtime behavior is fixed per built-in mode: sampling temperature, thinking, and the JSON schema for structured modes. A custom prompt for a built-in mode keeps that mode's behavior; a brand-new mode returns Markdown.

Structured modes (Extract List, Recipe JSON-LD, MTG) use Ollama's structured outputs with a JSON schema at a low temperature. The result is validated; if a model returns invalid JSON while thinking, Lumina retries once with thinking off.

## YouTube

For every video Lumina makes one metadata request, then picks the best caption track:

1. captions uploaded by the creator beat auto-generated ones;
2. language order: your configured language, then the video's original language, then English;
3. YouTube's `json3` format is preferred for exact timing, with WebVTT as the fallback.

If a video has no captions, or you untick *Use captions*, the audio is downloaded and transcribed with your engine.

Transcripts are stored as ~30-second paragraphs with `[m:ss]` timestamps. The **title, channel, date, chapters and description** are added above the transcript for every mode. Chapters often name each item in a top-X video, and descriptions often carry recipe ingredients or decklists. Timestamps in results link back into the video.

Extracted transcripts are cached, so running a second mode on the same video doesn't download anything again.

## Long content

Lumina estimates how much of the context window a request needs. When the content doesn't fit alongside the output budget, it switches to long-form processing instead of letting Ollama silently drop text:

- **Prose modes**: the content is split on paragraph or timestamp boundaries, each part becomes dense notes, and the real mode prompt runs over the combined notes.
- **Structured modes**: each part is extracted with the same JSON schema and the results are merged, with duplicates removed by name.

Progress shows as "Reading part 2 of 4…". With a 128K-context model like gemma4, videos of a couple of hours fit in one pass. Lumina also warns when a reply hits the output limit or the input filled the whole window.

## Recipes

When a video's description links the creator's recipe page ("print recipe"), Lumina reads that page's schema.org data first. The result is the exact recipe, with real quantities, every step and the photo, and the video adds nothing it would have to guess. Sponsor, social and affiliate links are ignored. If the page refuses automated requests, Lumina says so and rebuilds the recipe from the video instead. You can also open the page with the **URL** source.

From the video alone, the model is told to keep quantities and preparation notes ("1 onion, diced"), include every step in order, and use every ingredient in a step. Steps that only happen on camera, never spoken, can still be missing; a linked recipe page avoids that.

**JSON-LD output** is always normalized to valid schema.org/Recipe before you see it. That means `HowToStep` steps, ISO 8601 times, the source URL, the video thumbnail as the image, and the channel as the author. It imports cleanly with Mealie's parser (verified with Mealie v3.30).

**Markdown ⇄ JSON-LD**: every recipe result, and every saved recipe in **History**, has a Markdown / JSON-LD switch. JSON-LD → Markdown happens instantly in code. Markdown → JSON-LD is also parsed in code for Lumina's own recipe layout; only Markdown in some other shape, such as from a custom prompt, goes to the LLM.

**Send to Mealie**: add your Mealie URL and API token in **Settings → Integrations**. Recipe results, in either format, get a **Send to Mealie** button that creates the recipe through Mealie's API and links you to it. The photo is included, using the video thumbnail for YouTube recipes. It's also on saved recipes in **History**, so a recipe that finished while you were elsewhere is one click away.

## Chat

After a result you can chat with the full source, including its title, description and chapters. The chat budget comes from the model's real context window. Long conversations are compressed by summarizing older turns, and answers cite `[m:ss]` timestamps when the source has them.

## MTG Precon Upgrade

For Commander precon upgrade guides ("10 in / 10 out", "$50 upgrade"). The result is two columns, **Add** and **Cut**. Each card shows its Scryfall link, art, type, USD price, the host's reason, and a timestamp link into the video. You also get swap pairs when the host pairs cards, the total cost of the adds, and **Copy adds / Copy cuts** buttons that produce `1 Card Name` lines you can paste into Moxfield or Archidekt.

Lumina combines several sources, the most authoritative first:

1. **An upgraded decklist.** Paste one into *Upgraded decklist (optional)* in any common export format; a `Cuts` or `Sideboard` section counts as the removed cards. Or use an Archidekt link in the video description: its *Adds* and *Cuts* categories, when present, are used as-is. Moxfield doesn't allow automated access, so for Moxfield lists, export and paste.
2. **The original precon list** from [MTGJSON](https://mtgjson.com), matched from the precon name or the video title. It's used to diff against an upgraded list and to sanity-check the results.
3. **The video itself.** The LLM reads the transcript, chapters ("Cut 01", "Add 03") and description. This supplies each card's reason, timestamp and swap pairing, and the lists themselves when there's no decklist.

Every card name is then checked:

- against the precon and deck lists first, which fixes caption errors like "King Prahv" → *Kang Prime*;
- then against [Scryfall](https://scryfall.com).

Cards that don't line up get a visible flag instead of being dropped silently. That covers a cut that isn't in the precon, an add that's already in it, a name Scryfall doesn't know, and an automatic correction.

This mode talks to Scryfall, MTGJSON and Archidekt. Card data is cached for 24 hours and precon lists indefinitely, in `/data`.
