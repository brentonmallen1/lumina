import type { ActiveJobCounts, AudioModelMap, Capabilities, ChatMessage, EnhancementOptions, Feed, FeedEntry, FileMeta, HistoryEntry, Job, OllamaModel, OllamaModelInfo, PipelineSession, PersistentJob, Prompt, Settings, SettingsUpdateResponse, TTSStatus, TTSVoiceMap, YouTubeDownloadJob, YouTubeVideoInfo } from '../types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

// ── Engine ─────────────────────────────────────────────────────────────────

export function getCapabilities(): Promise<Capabilities> {
  return request<Capabilities>('/api/capabilities');
}

// ── Transcription ──────────────────────────────────────────────────────────

export function uploadFile(file: File, enhancement?: Partial<EnhancementOptions>): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('file', file);
  if (enhancement) {
    form.append('enhance_normalize', String(enhancement.normalize ?? false));
    form.append('enhance_denoise',   String(enhancement.denoise   ?? false));
    form.append('enhance_isolate',   String(enhancement.isolate   ?? false));
    form.append('enhance_upsample',  String(enhancement.upsample  ?? false));
  }
  return request('/api/transcribe', { method: 'POST', body: form });
}

export function getStatus(jobId: string): Promise<Job> {
  return request<Job>(`/api/status/${jobId}`);
}

export function getAudioUrl(jobId: string): string {
  return `/api/audio/${jobId}`;
}

export function getExportUrl(jobId: string): string {
  return `/api/export/${jobId}`;
}

export function getSrtExportUrl(jobId: string): string {
  return `/api/export/${jobId}/srt`;
}

export function getVttExportUrl(jobId: string): string {
  return `/api/export/${jobId}/vtt`;
}

export function getFiles(): Promise<FileMeta[]> {
  return request<FileMeta[]>('/api/files');
}

export function retranscribe(jobId: string, enhancement?: Partial<EnhancementOptions>): Promise<{ job_id: string }> {
  return request(`/api/retranscribe/${jobId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enhance_normalize: enhancement?.normalize ?? false,
      enhance_denoise:   enhancement?.denoise   ?? false,
      enhance_isolate:   enhancement?.isolate   ?? false,
      enhance_upsample:  enhancement?.upsample  ?? false,
    }),
  });
}

// ── Audio Enhancement ──────────────────────────────────────────────────────

export function enhanceFile(file: File, enhancement: Partial<EnhancementOptions>): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('file', file);
  form.append('enhance_normalize', String(enhancement.normalize ?? false));
  form.append('enhance_denoise',   String(enhancement.denoise   ?? false));
  form.append('enhance_isolate',   String(enhancement.isolate   ?? false));
  form.append('enhance_upsample',  String(enhancement.upsample  ?? false));
  return request('/api/enhance', { method: 'POST', body: form });
}

export function getEnhancedAudioUrl(jobId: string): string {
  return `/api/enhance/${jobId}/download`;
}

export function getOriginalAudioUrl(jobId: string): string {
  return `/api/enhance/${jobId}/original`;
}

export function reenhance(jobId: string, enhancement: Partial<EnhancementOptions>): Promise<{ job_id: string }> {
  return request(`/api/reenhance/${jobId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enhance_normalize: enhancement.normalize ?? false,
      enhance_denoise:   enhancement.denoise   ?? false,
      enhance_isolate:   enhancement.isolate   ?? false,
      enhance_upsample:  enhancement.upsample  ?? false,
    }),
  });
}

// ── Recipe JSON-LD Export ─────────────────────────────────────────────────

export interface RecipeJsonLD {
  '@context': string;
  '@type': string;
  name: string;
  description?: string;
  prepTime?: string;
  cookTime?: string;
  totalTime?: string;
  recipeYield?: string;
  recipeIngredient: string[];
  recipeInstructions: { '@type': string; text: string }[];
}

export function convertRecipeToJsonLD(recipeMarkdown: string, sourceUrl?: string): Promise<RecipeJsonLD> {
  return request<RecipeJsonLD>('/api/recipe/jsonld', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ recipe_markdown: recipeMarkdown, source_url: sourceUrl }),
  });
}

// ── Mealie ─────────────────────────────────────────────────────────────────

/** Check a Mealie URL + token (unsaved values from the form are allowed). */
export function testMealie(url?: string, token?: string): Promise<{ ok: boolean; message: string }> {
  return request('/api/integrations/mealie/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, token }),
  });
}

/**
 * Create a recipe in Mealie from schema.org JSON-LD, or from a Markdown
 * recipe (converted on the server first). Returns the new recipe's link.
 */
export function sendRecipeToMealie(
  input: { recipe: unknown } | { markdown: string }, sourceUrl?: string,
): Promise<{ slug: string; url: string }> {
  return request('/api/integrations/mealie/recipes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...input, source_url: sourceUrl }),
  });
}

/** schema.org Recipe JSON-LD → Markdown (done in code on the server). */
export function recipeToMarkdown(recipe: unknown): Promise<{ markdown: string }> {
  return request('/api/recipe/markdown', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ recipe }),
  });
}

// ── Settings ───────────────────────────────────────────────────────────────

export function getSettings(): Promise<Settings> {
  return request<Settings>('/api/settings');
}

export function updateSettings(updates: Partial<Settings>): Promise<SettingsUpdateResponse> {
  return request<SettingsUpdateResponse>('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
}

export function reloadEngine(): Promise<{ status: string }> {
  return request('/api/reload-engine', { method: 'POST' });
}

// ── Ollama ─────────────────────────────────────────────────────────────────

export function testOllamaConnection(): Promise<{ ok: boolean; message: string }> {
  return request('/api/ollama/test');
}

export function getOllamaModels(): Promise<{ models: OllamaModel[] }> {
  return request('/api/ollama/models');
}

export function getOllamaModelInfo(name: string): Promise<OllamaModelInfo> {
  return request(`/api/ollama/model/${encodeURIComponent(name)}`);
}

// ── Prompts ────────────────────────────────────────────────────────────────

export function getPrompts(): Promise<Prompt[]> {
  return request<Prompt[]>('/api/prompts');
}

export function createPrompt(data: {
  name: string;
  mode: string;
  system_prompt: string;
  template: string;
}): Promise<Prompt> {
  return request<Prompt>('/api/prompts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updatePrompt(id: string, data: {
  name: string;
  system_prompt: string;
  template: string;
}): Promise<Prompt> {
  return request<Prompt>(`/api/prompts/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deletePrompt(id: string): Promise<void> {
  return request(`/api/prompts/${id}`, { method: 'DELETE' });
}

export function resetPrompts(): Promise<{ ok: boolean }> {
  return request('/api/prompts/reset', { method: 'POST' });
}

// ── History ────────────────────────────────────────────────────────────────

// ── RSS/Podcast feeds ──────────────────────────────────────────────────────

export function getFeedsStatus(): Promise<{ available: boolean; reason: string }> {
  return request('/api/feeds/status');
}

export function getFeeds(): Promise<Feed[]> {
  return request<Feed[]>('/api/feeds');
}

export function createFeed(data: {
  url: string;
  check_interval?: number;
  auto_summarize?: boolean;
  summarize_mode?: string;
}): Promise<Feed> {
  return request<Feed>('/api/feeds', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteFeed(feedId: string): Promise<void> {
  return request(`/api/feeds/${feedId}`, { method: 'DELETE' });
}

export function getFeedEntries(feedId: string): Promise<FeedEntry[]> {
  return request<FeedEntry[]>(`/api/feeds/${feedId}/entries`);
}

export function checkFeedNow(feedId: string): Promise<{ status: string }> {
  return request(`/api/feeds/${feedId}/check`, { method: 'POST' });
}

// ── Speaker diarization ────────────────────────────────────────────────────

export function diarizeJob(jobId: string): Promise<{ segments: import('../types').Segment[]; diarization: { speaker: string; start: number; end: number }[] }> {
  return request(`/api/diarize/${jobId}`, { method: 'POST' });
}

// ── Clip extraction ────────────────────────────────────────────────────────

export function extractClip(
  jobId: string,
  start: number,
  end: number,
  format: 'mp3' | 'wav' | 'm4a' | 'flac' = 'mp3',
): Promise<{ clip_id: string; filename: string; job_id: string }> {
  return request(`/api/clip/${jobId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ start, end, format }),
  });
}

export function getClipDownloadUrl(jobId: string, clipId: string): string {
  return `/api/clip/${jobId}/${clipId}/download`;
}

// ── Translation ────────────────────────────────────────────────────────────

export function translateStream(
  text: string,
  targetLanguage: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return streamSSE('/api/translate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, target_language: targetLanguage }),
  }, handlers, signal);
}

// ── History ────────────────────────────────────────────────────────────────

export function getHistory(): Promise<HistoryEntry[]> {
  return request<HistoryEntry[]>('/api/history');
}

export function searchHistory(q: string): Promise<(HistoryEntry & { snippet?: string })[]> {
  return request(`/api/history/search?q=${encodeURIComponent(q)}`);
}

export function saveHistory(data: {
  mode: string;
  source: string;
  source_detail?: string;
  result: string;
  reasoning?: string;
}): Promise<HistoryEntry> {
  return request<HistoryEntry>('/api/history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteHistoryEntry(id: string): Promise<void> {
  return request(`/api/history/${id}`, { method: 'DELETE' });
}

export function clearHistory(): Promise<void> {
  return request('/api/history', { method: 'DELETE' });
}

// ── YouTube Download ───────────────────────────────────────────────────────

export function getYouTubeInfo(url: string): Promise<YouTubeVideoInfo> {
  return request<YouTubeVideoInfo>(`/api/youtube/info?url=${encodeURIComponent(url)}`);
}

export function startYouTubeDownload(opts: {
  url:           string;
  mode:          'video' | 'audio';
  video_quality?: string;
  video_format?:  string;
  audio_format?:  string;
  audio_quality?: string;
}): Promise<{ job_id: string }> {
  return request('/api/youtube/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts),
  });
}

export function getYouTubeJobStatus(jobId: string): Promise<YouTubeDownloadJob> {
  return request<YouTubeDownloadJob>(`/api/youtube/${jobId}`);
}

export function getYouTubeFileUrl(jobId: string): string {
  return `/api/youtube/${jobId}/file`;
}

// ── Interactive Audio Pipeline ─────────────────────────────────────────────

export function createPipeline(file: File): Promise<{ session_id: string; filename: string | null }> {
  const form = new FormData();
  form.append('file', file);
  return request('/api/pipeline', { method: 'POST', body: form });
}

export function getPipelineSession(sessionId: string): Promise<PipelineSession> {
  return request<PipelineSession>(`/api/pipeline/${sessionId}`);
}

export function applyPipelineStep(sessionId: string, step: string): Promise<{ status: string; step: string }> {
  return request(`/api/pipeline/${sessionId}/step`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ step }),
  });
}

export function undoPipelineStep(sessionId: string): Promise<{ status: string; steps_remaining: number }> {
  return request(`/api/pipeline/${sessionId}/step`, { method: 'DELETE' });
}

export function transcribePipeline(sessionId: string): Promise<{ job_id: string }> {
  return request(`/api/pipeline/${sessionId}/transcribe`, { method: 'POST' });
}

export function getPipelineAudioUrl(sessionId: string, step: string = 'current'): string {
  return `/api/pipeline/${sessionId}/audio?step=${encodeURIComponent(step)}`;
}

export function getPipelineDownloadUrl(sessionId: string): string {
  return `/api/pipeline/${sessionId}/download`;
}

export function deletePipeline(sessionId: string): Promise<{ status: string }> {
  return request(`/api/pipeline/${sessionId}`, { method: 'DELETE' });
}

// ── Audio models ───────────────────────────────────────────────────────────

export function getAudioModels(): Promise<AudioModelMap> {
  return request<AudioModelMap>('/api/audio/models');
}

/**
 * Download one or more audio enhancement models.
 * Streams SSE events:
 *   {"model": "deepfilternet", "status": "downloading"|"done"|"error", "message": "..."}
 *   [DONE]
 */
export async function downloadAudioModels(
  models: string[],
  onProgress: (model: string, status: string, message: string) => void,
  onDone: () => void,
  onError: (message: string) => void,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch('/api/audio/models/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ models }),
    });
  } catch {
    onError('Network error — is the API server running?');
    return;
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    onError(body.detail ?? res.statusText);
    return;
  }

  const reader  = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') { onDone(); return; }
        try {
          const ev = JSON.parse(payload);
          if (ev.error)  { onError(ev.error); return; }
          if (ev.model)  { onProgress(ev.model, ev.status ?? '', ev.message ?? ''); }
        } catch { /* skip */ }
      }
    }
  } finally {
    reader.releaseLock();
  }
  onDone();
}

// ── Text-to-Speech ─────────────────────────────────────────────────────────

export function getTTSStatus(): Promise<TTSStatus> {
  return request<TTSStatus>('/api/tts/status');
}

export function getTTSVoices(): Promise<{ voices: TTSVoiceMap }> {
  return request<{ voices: TTSVoiceMap }>('/api/tts/voices');
}

/**
 * Download Kokoro TTS model weights.
 * Streams SSE events:
 *   {"status": "downloading"|"done"|"error", "message": "...", "error": "..."}
 *   [DONE]
 */
export async function downloadTTSModel(
  onProgress: (status: string, message: string) => void,
  onDone: () => void,
  onError: (message: string) => void,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch('/api/tts/download', { method: 'POST' });
  } catch {
    onError('Network error — is the API server running?');
    return;
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    onError(body.detail ?? res.statusText);
    return;
  }

  const reader  = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        if (payload === '[DONE]') { onDone(); return; }
        try {
          const ev = JSON.parse(payload);
          if (ev.error)   { onError(ev.error); return; }
          if (ev.status)  { onProgress(ev.status, ev.message ?? ''); }
        } catch { /* skip */ }
      }
    }
  } finally {
    reader.releaseLock();
  }
  onDone();
}

/**
 * Synthesize text to speech and return an audio Blob (WAV).
 * Pass voice=undefined to use the server's default voice setting.
 */
export async function synthesizeSpeech(text: string, voice?: string): Promise<Blob> {
  const res = await fetch('/api/tts/synthesize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? res.statusText);
  }
  return res.blob();
}

// ── Shared SSE streaming ───────────────────────────────────────────────────

/**
 * Handlers for the backend's SSE protocol (see backend/routers/llm.py):
 *   {"phase", "detail"}       progress (extracting | transcribing | thinking)
 *   {"reasoning"}             model reasoning chunk (native Ollama thinking)
 *   {"text"}                  answer chunk
 *   {"reset": true}           discard streamed text (structured-output retry)
 *   {"warning"} / {"notice"}  non-fatal messages
 *   {"extracted_content"}     full source text, for chat
 *   {"result", "meta"}        authoritative final result
 *   {"error"}                 terminal error
 *   [DONE]
 */
export interface StreamHandlers {
  onError: (message: string) => void;
  onDone: () => void;
  onPhase?: (phase: string, detail: string) => void;
  onChunk?: (text: string) => void;
  onReasoning?: (text: string) => void;
  onReset?: () => void;
  onResult?: (text: string, meta: StreamResultMeta) => void;
  onExtracted?: (content: string) => void;
  onWarning?: (message: string) => void;
  onNotice?: (message: string) => void;
}

export interface StreamResultMeta {
  mode?: string;
  model?: string;
  num_ctx?: number;
  output_type?: string;
  longform?: boolean;
  parts?: number;
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError';
}

/**
 * POST to an SSE endpoint and dispatch events. Never throws: network errors,
 * HTTP errors and dropped connections all go to onError. An aborted request
 * (user pressed Stop / navigated away) ends silently.
 */
async function streamSSE(
  url: string,
  init: RequestInit,
  h: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, { ...init, signal });
  } catch (err) {
    if (!isAbort(err)) h.onError('Network error — is the API server running?');
    return;
  }
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    h.onError(typeof body.detail === 'string' ? body.detail : res.statusText);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        if (payload === '[DONE]') { h.onDone(); return; }
        let ev: Record<string, unknown>;
        try { ev = JSON.parse(payload); } catch { continue; }
        if (typeof ev.error === 'string') { h.onError(ev.error); return; }
        if (typeof ev.phase === 'string') { h.onPhase?.(ev.phase, (ev.detail as string) ?? ''); continue; }
        if (typeof ev.extracted_content === 'string') { h.onExtracted?.(ev.extracted_content); continue; }
        if (typeof ev.warning === 'string') { h.onWarning?.(ev.warning); continue; }
        if (typeof ev.notice === 'string') { h.onNotice?.(ev.notice); continue; }
        if (ev.reset) { h.onReset?.(); continue; }
        if (typeof ev.reasoning === 'string') { h.onReasoning?.(ev.reasoning); continue; }
        if (typeof ev.result === 'string') { h.onResult?.(ev.result, (ev.meta as StreamResultMeta) ?? {}); continue; }
        if (typeof ev.text === 'string') { h.onChunk?.(ev.text); }
      }
    }
  } catch (err) {
    if (!isAbort(err)) h.onError('Connection lost while streaming — the result may be incomplete.');
    return;
  } finally {
    reader.releaseLock();
  }
  h.onDone();
}

// ── Summarize ──────────────────────────────────────────────────────────────

/** Stream a summarization of plain text. */
export function summarize(
  content: string,
  mode: string,
  handlers: StreamHandlers,
  opts: { model?: string | null; title?: string; options?: Record<string, unknown>; signal?: AbortSignal } = {},
): Promise<void> {
  return streamSSE('/api/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, mode, model: opts.model ?? null, title: opts.title, options: opts.options }),
  }, handlers, opts.signal);
}

/** Upload a file (audio/video/PDF) and stream extraction + summarization. */
export function summarizeFile(
  file: File,
  source: 'audio' | 'pdf',
  mode: string,
  handlers: StreamHandlers,
  opts: { enhancement?: Partial<EnhancementOptions>; signal?: AbortSignal } = {},
): Promise<void> {
  const form = new FormData();
  form.append('file', file);
  form.append('source', source);
  form.append('mode', mode);
  const e = opts.enhancement;
  if (e && source === 'audio') {
    form.append('enhance_normalize', String(e.normalize ?? false));
    form.append('enhance_denoise',   String(e.denoise   ?? false));
    form.append('enhance_isolate',   String(e.isolate   ?? false));
    form.append('enhance_upsample',  String(e.upsample  ?? false));
  }
  return streamSSE('/api/summarize/file', { method: 'POST', body: form }, handlers, opts.signal);
}

/** Upload an image and stream a vision-LLM result. */
export function summarizeImage(
  file: File,
  mode: string,
  handlers: StreamHandlers,
  opts: { signal?: AbortSignal } = {},
): Promise<void> {
  const form = new FormData();
  form.append('file', file);
  form.append('mode', mode);
  return streamSSE('/api/summarize/image', { method: 'POST', body: form }, handlers, opts.signal);
}

// ── Chat ───────────────────────────────────────────────────────────────────

/** Multi-turn streaming chat about a source document. */
export function chat(
  content: string,
  messages: ChatMessage[],
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return streamSSE('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, messages }),
  }, handlers, signal);
}

// ── Persistent Jobs API ────────────────────────────────────────────────────


export interface ListJobsParams {
  status?: string;
  type?: string;
  batch_id?: string;
  limit?: number;
}

export function listJobs(params?: ListJobsParams): Promise<{ jobs: PersistentJob[] }> {
  const query = new URLSearchParams();
  if (params?.status) query.set('status', params.status);
  if (params?.type) query.set('type', params.type);
  if (params?.batch_id) query.set('batch_id', params.batch_id);
  if (params?.limit) query.set('limit', String(params.limit));
  const qs = query.toString();
  return request<{ jobs: PersistentJob[] }>(`/api/jobs${qs ? `?${qs}` : ''}`);
}

export function getJob(jobId: string): Promise<PersistentJob> {
  return request<PersistentJob>(`/api/jobs/${jobId}`);
}

export function cancelJob(jobId: string): Promise<PersistentJob> {
  return request<PersistentJob>(`/api/jobs/${jobId}`, { method: 'DELETE' });
}

export function retryJob(jobId: string): Promise<PersistentJob> {
  return request<PersistentJob>(`/api/jobs/${jobId}/retry`, { method: 'POST' });
}

export function getActiveJobCounts(): Promise<ActiveJobCounts> {
  return request<ActiveJobCounts>('/api/jobs/active');
}

export interface CreateJobRequest {
  job_type: string;
  source_type: string;
  source_ref: string;
  source_title?: string;
  config?: Record<string, unknown>;
}

export function createJob(req: CreateJobRequest): Promise<PersistentJob> {
  return request<PersistentJob>('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export interface BatchJobRequest {
  urls: string[];
  job_type?: string;
  config?: Record<string, unknown>;
}

export function createBatchJobs(req: BatchJobRequest): Promise<{
  batch_id: string;
  job_count: number;
  jobs: PersistentJob[];
}> {
  return request<{
    batch_id: string;
    job_count: number;
    jobs: PersistentJob[];
  }>('/api/jobs/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

// ── Extraction Cache API ───────────────────────────────────────────────────

