/**
 * How each mode's output is rendered and which actions apply to it.
 *
 * The backend reports an `output_type` per mode (GET /api/prompts and the
 * final SSE `result` event): `markdown`, `mindmap`, or `json:<renderer>`.
 * Pages look the behaviour up here instead of hardcoding mode names.
 */

export type DownloadFormat = 'txt' | 'md' | 'json' | 'svg';

export interface OutputBehavior {
  /** Show the Markdown/Raw (or Diagram/Raw) toggle. */
  rawToggle: boolean;
  /** Label for the "rendered" state of the toggle. */
  renderedLabel: string;
  /** Offer Read Aloud. */
  tts: boolean;
  /** Offer translation. */
  translatable: boolean;
  /** Stream text live (false = show the thinking indicator until done). */
  streamText: boolean;
  downloads: DownloadFormat[];
}

const MARKDOWN: OutputBehavior = {
  rawToggle: true, renderedLabel: 'Markdown', tts: true, translatable: true,
  streamText: true, downloads: ['txt', 'md'],
};

const BEHAVIORS: Record<string, OutputBehavior> = {
  markdown: MARKDOWN,
  mindmap: {
    rawToggle: true, renderedLabel: 'Diagram', tts: false, translatable: false,
    streamText: true, downloads: ['svg', 'md'],
  },
  json: {
    rawToggle: true, renderedLabel: 'Formatted', tts: false, translatable: false,
    streamText: false, downloads: ['json'],
  },
};

export function outputBehavior(outputType: string | undefined): OutputBehavior {
  if (!outputType) return MARKDOWN;
  if (outputType.startsWith('json')) return BEHAVIORS.json;
  return BEHAVIORS[outputType] ?? MARKDOWN;
}

/** `json:mtg` → `mtg`; anything else → null. */
export function jsonRenderer(outputType: string | undefined): string | null {
  return outputType?.startsWith('json:') ? outputType.slice(5) : null;
}

/** Output types for built-in modes — used before /api/prompts loads and for old history entries. */
export const BUILTIN_OUTPUT_TYPES: Record<string, string> = {
  mind_map: 'mindmap',
  recipe_jsonld: 'json:recipe',
  extract_list: 'json:list',
  mtg_precon: 'json:mtg',
};

export function parseJson<T = unknown>(text: string): T | null {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const candidate = fenced ? fenced[1] : text;
  try {
    return JSON.parse(candidate) as T;
  } catch {
    const start = candidate.search(/[[{]/);
    const end = Math.max(candidate.lastIndexOf('}'), candidate.lastIndexOf(']'));
    if (start === -1 || end <= start) return null;
    try { return JSON.parse(candidate.slice(start, end + 1)) as T; } catch { return null; }
  }
}
