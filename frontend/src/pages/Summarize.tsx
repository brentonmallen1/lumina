import { useState, useRef, useCallback, useEffect } from 'react';
import {
  ArrowLeft, Sparkles, Copy, Download, RotateCcw, Square,
  Mic, Youtube, Globe, FileText, File as FileIcon, Image as ImageIcon,
  AlertTriangle, X, Code, Volume2, Loader, FileJson, ChefHat, ExternalLink,
} from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import * as api from '../api/client';
import type { StreamHandlers } from '../api/client';
import { useJobs } from '../context/JobContext';
import type { AudioModelMap, EnhancementOptions, PersistentJob } from '../types';
import EnhancementPanel, { DEFAULT_ENHANCEMENT } from '../components/EnhancementPanel';
import DropZone from '../components/summarize/DropZone';
import ChatPanel from '../components/summarize/ChatPanel';
import TranslatePanel from '../components/summarize/TranslatePanel';
import ResultView from '../components/results/ResultView';
import '../components/results/renderers';
import {
  BUILTIN_OUTPUT_TYPES, outputBehavior, parseJson, type DownloadFormat,
} from '../components/results/registry';
import { useSourceCache } from '../context/SourceCache';
import { useBatchedText } from '../hooks/useBatchedText';
import './Summarize.css';

// ── Types & constants ──────────────────────────────────────────────────────

type SourceTab = 'text' | 'audio' | 'youtube' | 'url' | 'pdf' | 'image';
type ViewState = 'idle' | 'extracting' | 'transcribing' | 'thinking' | 'streaming' | 'done' | 'error';

interface ModeOption { id: string; label: string; hint: string; outputType: string }
interface CachedResult { result: string; reasoning: string; outputType: string }

const SOURCE_TABS: { id: SourceTab; label: string; icon: React.ElementType }[] = [
  { id: 'text',    label: 'Text',    icon: FileText   },
  { id: 'audio',   label: 'Audio',   icon: Mic        },
  { id: 'youtube', label: 'YouTube', icon: Youtube    },
  { id: 'url',     label: 'URL',     icon: Globe      },
  { id: 'pdf',     label: 'PDF',     icon: FileIcon   },
  { id: 'image',   label: 'Image',   icon: ImageIcon  },
];

const TRANSCRIPT_MODE: ModeOption = {
  id: 'transcript', label: 'Transcript / Raw Text', hint: 'Raw transcription — no AI processing', outputType: 'markdown',
};

// Ordered most common → most specific. Labels are replaced by /api/prompts once loaded.
const DEFAULT_MODES: ModeOption[] = [
  { id: 'summary',         label: 'Summary',         hint: 'Prose overview — includes list items when detected' },
  { id: 'tldr',            label: 'TL;DR',           hint: 'Ultra-brief bullet summary (250 words max)' },
  { id: 'key_points',      label: 'Key Points',      hint: 'Numbered list of main ideas' },
  { id: 'action_items',    label: 'Action Items',    hint: 'Concrete tasks and next steps' },
  { id: 'q_and_a',         label: 'Q&A',             hint: 'Questions and answers' },
  { id: 'mind_map',        label: 'Mind Map',        hint: 'Hierarchical outline' },
  { id: 'meeting_minutes', label: 'Meeting Minutes', hint: 'Structured notes from a meeting' },
  { id: 'extract_list',    label: 'Extract List',    hint: 'Pull out ranked or top-X lists, with timestamps' },
  { id: 'recipe',          label: 'Recipe',          hint: 'Extract recipe with ingredients and steps' },
  { id: 'mtg_precon',      label: 'MTG Precon Upgrade', hint: 'Cards to add and cut from a Commander precon upgrade video' },
].map(m => ({ ...m, outputType: BUILTIN_OUTPUT_TYPES[m.id] ?? 'markdown' }));

const AUDIO_ACCEPT = '.mp3,.wav,.m4a,.flac,.ogg,.webm,.opus,.aac,.wma,.mp4,.mkv,.avi,.mov,.wmv,.flv,.m4v';
const PENDING_JOB_KEY = 'lumina-summarize-pending-job';
const JOB_POLL_MS = 1000;

const meta = (job: PersistentJob) => (job.result_meta ?? {}) as Record<string, unknown>;

function downloadBlob(content: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
    } else {
      // Fallback for plain-HTTP LAN access, where the Clipboard API is unavailable.
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    return true;
  } catch {
    return false;
  }
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function Summarize() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { submitJob, cancelJob } = useJobs();
  const sourceCache = useSourceCache();

  const validTabs = SOURCE_TABS.map(t => t.id) as string[];
  const initialTab = searchParams.get('tab');
  const [sourceTab, setSourceTab] = useState<SourceTab>(
    (initialTab && validTabs.includes(initialTab) ? initialTab : 'text') as SourceTab,
  );
  const [mode, setMode]   = useState('summary');
  const [modes, setModes] = useState<ModeOption[]>([...DEFAULT_MODES, TRANSCRIPT_MODE]);
  const [view, setView]   = useState<ViewState>('idle');
  const [result, resultBuf]       = useBatchedText();
  const [reasoning, reasoningBuf] = useBatchedText();
  const [resultMode, setResultMode] = useState('');           // mode whose result is on screen
  const [outputType, setOutputType] = useState('markdown');
  const [errorMsg, setErrorMsg]     = useState('');
  const [warnings, setWarnings]     = useState<string[]>([]);
  const [statusDetail, setStatusDetail] = useState('');
  const [isCopied, setIsCopied]     = useState(false);
  const [rendered, setRendered]     = useState(true);
  const [modeCache, setModeCache]   = useState<Record<string, CachedResult>>({});

  const abortRef = useRef<AbortController | null>(null);
  const [pendingJobId, setPendingJobIdState] = useState<string | null>(() => {
    try { return sessionStorage.getItem(PENDING_JOB_KEY); } catch { return null; }
  });
  const setPendingJobId = (id: string | null) => {
    setPendingJobIdState(id);
    try {
      if (id) sessionStorage.setItem(PENDING_JOB_KEY, id);
      else sessionStorage.removeItem(PENDING_JOB_KEY);
    } catch { /* storage unavailable */ }
  };

  // Source inputs
  const [content, setContent]               = useState('');
  const [audioFile, setAudioFile]           = useState<File | null>(null);
  const [pdfFile, setPdfFile]               = useState<File | null>(null);
  const [imageFile, setImageFile]           = useState<File | null>(null);
  const [youtubeUrl, setYoutubeUrl]         = useState('');
  const [urlInput, setUrlInput]             = useState('');
  const [preferCaptions, setPreferCaptions] = useState(true);
  const [enhancement, setEnhancement]       = useState<EnhancementOptions>(DEFAULT_ENHANCEMENT);
  const [audioModels, setAudioModels]       = useState<AudioModelMap | undefined>(undefined);
  const [maxUploadSizeMb, setMaxUploadSizeMb] = useState(500);

  // Chat source
  const [sourceContent, setSourceContent] = useState('');
  const [sourceUrl, setSourceUrl]         = useState<string | undefined>(undefined);

  // TTS
  const [ttsEnabled, setTtsEnabled]   = useState(true);
  const [ttsVoice, setTtsVoice]       = useState<string | undefined>(undefined);
  const [ttsAudioUrl, setTtsAudioUrl] = useState<string | null>(null);
  const [ttsLoading, setTtsLoading]   = useState(false);
  const [ttsError, setTtsError]       = useState('');
  const ttsBlobUrlRef = useRef<string | null>(null);

  // MTG precon upgrade: optional pasted decklist (Moxfield/Archidekt export)
  const [mtgDecklist, setMtgDecklist] = useState('');

  // Recipe
  const [recipeFormat, setRecipeFormat]   = useState<'markdown' | 'jsonld'>('jsonld');
  const [jsonLdLoading, setJsonLdLoading] = useState(false);
  const [jsonLdError, setJsonLdError]     = useState('');
  const [jsonLdCopied, setJsonLdCopied]   = useState(false);

  // Mealie (Settings → Integrations)
  const [mealieReady, setMealieReady]     = useState(false);
  const [mealieSending, setMealieSending] = useState(false);
  const [mealieLink, setMealieLink]       = useState('');
  const [mealieError, setMealieError]     = useState('');

  const behavior = outputBehavior(outputType);
  const isRunning = ['extracting', 'transcribing', 'thinking', 'streaming'].includes(view);
  const modeLabel = (id: string): string => {
    if (id === 'recipe_jsonld') return `${modeLabel('recipe')} (JSON-LD)`;
    return modes.find(m => m.id === id)?.label ?? id;
  };

  useEffect(() => () => {
    abortRef.current?.abort();
    if (ttsBlobUrlRef.current) URL.revokeObjectURL(ttsBlobUrlRef.current);
  }, []);

  // ── Load settings & modes ──────────────────────────────────────────────
  useEffect(() => {
    api.getAudioModels().then(setAudioModels).catch(() => {});
    api.getSettings().then(s => {
      setTtsEnabled(s.tts_enabled !== 'false');
      setTtsVoice(s.tts_voice || undefined);
      setMealieReady(Boolean(s.mealie_url && s.mealie_api_token));
      const maxSize = parseInt(s.max_upload_size_mb, 10);
      if (!isNaN(maxSize) && maxSize > 0) setMaxUploadSizeMb(maxSize);
    }).catch(() => {});
    api.getPrompts().then(prompts => {
      const hints = Object.fromEntries(DEFAULT_MODES.map(m => [m.id, m.hint]));
      const order = new Map(DEFAULT_MODES.map((m, i) => [m.id, i]));
      // Custom prompts shadow built-ins with the same mode slug.
      const byMode = new Map<string, ModeOption>();
      for (const p of [...prompts].sort((a, b) => Number(b.is_default) - Number(a.is_default))) {
        byMode.set(p.mode, {
          id: p.mode, label: p.name, hint: hints[p.mode] ?? '',
          outputType: p.output_type ?? BUILTIN_OUTPUT_TYPES[p.mode] ?? 'markdown',
        });
      }
      if (byMode.size > 0) {
        const list = [...byMode.values()].sort((a, b) => (order.get(a.id) ?? 999) - (order.get(b.id) ?? 999));
        setModes([...list, TRANSCRIPT_MODE]);
      }
    }).catch(() => {});
  }, []);

  // ── Result lifecycle ───────────────────────────────────────────────────

  const clearRun = () => {
    resultBuf.set('');
    reasoningBuf.set('');
    setErrorMsg('');
    setWarnings([]);
    setStatusDetail('');
    setJsonLdError('');
    setMealieLink('');
    setMealieError('');
  };

  const addWarning = (msg: string) => setWarnings(prev => (prev.includes(msg) ? prev : [...prev, msg]));

  /** Show a finished result and remember it for this mode. */
  const showResult = useCallback((forMode: string, text: string, why: string, type: string) => {
    resultBuf.set(text);
    reasoningBuf.set(why);
    setResultMode(forMode);
    setOutputType(type);
    setRendered(true);
    setView('done');
    setModeCache(prev => ({ ...prev, [forMode]: { result: text, reasoning: why, outputType: type } }));
  }, [resultBuf, reasoningBuf]);

  const loadSourceFromJob = useCallback((job: PersistentJob) => {
    const extracted = meta(job).extracted_text as string | undefined;
    if (extracted) {
      setSourceContent(extracted);
      setModeCache(prev => ({ ...prev, transcript: { result: extracted, reasoning: '', outputType: 'markdown' } }));
    }
    if (job.source_type === 'youtube') setSourceUrl(job.source_ref ?? undefined);
  }, []);

  const showJobResult = useCallback((job: PersistentJob) => {
    const m = meta(job);
    const jobMode = (job.config as Record<string, unknown>)?.mode as string || 'summary';
    const type = (m.output_type as string) || BUILTIN_OUTPUT_TYPES[jobMode] || 'markdown';
    setMode(jobMode);
    showResult(jobMode, job.result ?? '', (m.reasoning as string) || '', type);
    const jobWarnings = (m.warnings as string[] | undefined) ?? [];
    setWarnings(jobWarnings);
    loadSourceFromJob(job);
  }, [showResult, loadSourceFromJob]);

  // Open a finished job from the Jobs page (?jobId=…)
  useEffect(() => {
    const jobId = searchParams.get('jobId');
    if (!jobId) return;
    api.getJob(jobId).then(job => {
      if (!job || job.status !== 'done' || !job.result) return;
      if (job.source_type === 'youtube') { setSourceTab('youtube'); setYoutubeUrl(job.source_ref || ''); }
      else if (job.source_type === 'url') { setSourceTab('url'); setUrlInput(job.source_ref || ''); }

      if (job.type === 'extract') {
        setSourceContent(job.result);
        setModeCache({ transcript: { result: job.result, reasoning: '', outputType: 'markdown' } });
        setMode('summary');
        setView('idle');
      } else {
        showJobResult(job);
      }
      setSearchParams({}, { replace: true });
    }).catch(() => {});
  }, [searchParams, setSearchParams, showJobResult]);

  // Follow a queued job (YouTube / URL): stream its partial result, then show it.
  useEffect(() => {
    if (!pendingJobId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      let job: PersistentJob;
      try {
        job = await api.getJob(pendingJobId);
      } catch {
        if (!stopped) timer = setTimeout(tick, JOB_POLL_MS * 3);
        return;
      }
      if (stopped) return;

      if (job.status === 'done') {
        showJobResult(job);
        setPendingJobId(null);
        return;
      }
      if (job.status === 'error' || job.status === 'cancelled') {
        setErrorMsg(job.status === 'cancelled' ? 'Job was cancelled' : (job.error || 'Job failed'));
        setView('error');
        setPendingJobId(null);
        return;
      }
      if (job.status_detail) setStatusDetail(job.status_detail);
      const jobMode = (job.config as Record<string, unknown>)?.mode as string;
      const streams = outputBehavior(BUILTIN_OUTPUT_TYPES[jobMode]).streamText;
      if (job.status === 'running' && job.result && streams) {
        resultBuf.set(job.result);
        setView('streaming');
      } else {
        setView(v => (v === 'idle' || v === 'done' ? 'extracting' : v));
      }
      timer = setTimeout(tick, JOB_POLL_MS);
    };

    if (view === 'idle') setView('extracting');
    tick();
    return () => { stopped = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingJobId]);

  // ── Actions ────────────────────────────────────────────────────────────

  const reset = () => {
    abortRef.current?.abort();
    clearRun();
    setView('idle');
    setResultMode('');
    setModeCache({});
    setSourceContent('');
    setSourceUrl(undefined);
    setImageFile(null);
    setPendingJobId(null);
    if (ttsBlobUrlRef.current) { URL.revokeObjectURL(ttsBlobUrlRef.current); ttsBlobUrlRef.current = null; }
    setTtsAudioUrl(null);
  };

  const stop = () => {
    abortRef.current?.abort();
    if (pendingJobId) {
      cancelJob(pendingJobId).catch(() => {});
      setPendingJobId(null);
    }
    const partial = resultBuf.current();
    if (partial) {
      setView('done');
      addWarning('Stopped — the result is incomplete.');
    } else {
      setView('idle');
    }
  };

  const canSubmit = (() => {
    if (isRunning) return false;
    switch (sourceTab) {
      case 'text':    return content.trim().length > 0;
      case 'audio':   return audioFile !== null;
      case 'youtube': return youtubeUrl.trim().length > 0;
      case 'url':     return urlInput.trim().length > 0;
      case 'pdf':     return pdfFile !== null;
      case 'image':   return imageFile !== null;
    }
  })();

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const effectiveMode = (mode === 'recipe' && recipeFormat === 'jsonld') ? 'recipe_jsonld' : mode;
    const expectedType = modes.find(m => m.id === effectiveMode)?.outputType
      ?? BUILTIN_OUTPUT_TYPES[effectiveMode] ?? 'markdown';

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    clearRun();
    setView('thinking');
    setResultMode(effectiveMode);
    setOutputType(expectedType);
    const src = sourceTab;
    let finalType = expectedType;
    const modeOptions = effectiveMode === 'mtg_precon' && mtgDecklist.trim()
      ? { decklist: mtgDecklist }
      : undefined;

    const handlers: StreamHandlers = {
      onPhase: (phase, detail) => {
        setView(phase === 'thinking' ? 'thinking' : (phase as ViewState));
        setStatusDetail(detail);
      },
      onReasoning: chunk => {
        reasoningBuf.append(chunk);
        setView(v => (v === 'streaming' ? v : 'thinking'));
        setStatusDetail('');
      },
      onChunk: chunk => {
        resultBuf.append(chunk);
        setView('streaming');
      },
      onReset: () => resultBuf.set(''),
      onResult: (text, m) => {
        resultBuf.set(text);
        if (m.output_type) { finalType = m.output_type; setOutputType(m.output_type); }
      },
      onWarning: addWarning,
      onError: msg => { setErrorMsg(msg); setView('error'); },
      onDone: () => {
        if (controller.signal.aborted) return;
        const text = resultBuf.current();
        const why = reasoningBuf.current();
        setView(v => (v === 'error' ? v : 'done'));
        if (!text) return;
        showResult(effectiveMode, text, why, finalType);
        const sourceDetail =
          src === 'audio' ? (audioFile?.name ?? '') :
          src === 'pdf'   ? (pdfFile?.name ?? '') :
          src === 'image' ? (imageFile?.name ?? '') : '';
        api.saveHistory({
          mode: effectiveMode, source: src, source_detail: sourceDetail, result: text, reasoning: why,
        }).catch(() => {});
      },
    };

    const onExtracted = (key: string | null, label: string) => (extracted: string) => {
      if (key) sourceCache.set(key, { content: extracted, label, sourceType: src });
      setSourceContent(extracted);
      setModeCache(prev => ({ ...prev, transcript: { result: extracted, reasoning: '', outputType: 'markdown' } }));
    };

    // Re-runs on the same file reuse the extracted text instead of re-transcribing.
    const fileKey = (prefix: string, f: File, extra = '') => `${prefix}:${f.name}:${f.size}:${f.lastModified}${extra}`;
    const fromCacheOr = async (key: string, fresh: () => Promise<void>) => {
      const cached = sourceCache.get(key);
      if (!cached) return fresh();
      setStatusDetail('Using cached extraction…');
      onExtracted(null, cached.label)(cached.content);
      await api.summarize(cached.content, effectiveMode, handlers, { options: modeOptions, signal: controller.signal });
    };

    switch (sourceTab) {
      case 'text': {
        const trimmed = content.trim();
        onExtracted(null, 'text')(trimmed);
        await api.summarize(trimmed, effectiveMode, handlers, { options: modeOptions, signal: controller.signal });
        break;
      }
      case 'audio': {
        const key = fileKey('audio', audioFile!, `:${JSON.stringify(enhancement)}`);
        await fromCacheOr(key, () => api.summarizeFile(audioFile!, 'audio', effectiveMode,
          { ...handlers, onExtracted: onExtracted(key, audioFile!.name) },
          { enhancement, signal: controller.signal }));
        break;
      }
      case 'pdf': {
        const key = fileKey('pdf', pdfFile!);
        await fromCacheOr(key, () => api.summarizeFile(pdfFile!, 'pdf', effectiveMode,
          { ...handlers, onExtracted: onExtracted(key, pdfFile!.name) },
          { signal: controller.signal }));
        break;
      }
      case 'image':
        await api.summarizeImage(imageFile!, effectiveMode, handlers, { signal: controller.signal });
        break;
      case 'youtube':
      case 'url': {
        const url = (sourceTab === 'youtube' ? youtubeUrl : urlInput).trim();
        try {
          const job = await submitJob({
            job_type: 'summarize',
            source_type: sourceTab,
            source_ref: url,
            source_title: url,
            config: {
              mode: effectiveMode,
              ...(sourceTab === 'youtube' ? { prefer_captions: preferCaptions } : {}),
              ...(modeOptions ? { options: modeOptions } : {}),
            },
          });
          setView('extracting');
          setStatusDetail('Queued for processing…');
          setPendingJobId(job.id);
        } catch (err) {
          handlers.onError(err instanceof Error ? err.message : 'Failed to create job');
        }
        break;
      }
    }
  };

  const handleModeClick = (newMode: string) => {
    if (isRunning) return;
    setMode(newMode);
    setMealieLink('');
    setMealieError('');
    const cached = modeCache[newMode]
      ?? (newMode === 'recipe' ? modeCache.recipe_jsonld : undefined);
    if (cached) {
      const cachedMode = modeCache[newMode] ? newMode : 'recipe_jsonld';
      resultBuf.set(cached.result);
      reasoningBuf.set(cached.reasoning);
      setResultMode(cachedMode);
      setOutputType(cached.outputType);
      setWarnings([]);
      setView('done');
    } else if (view === 'done' || view === 'streaming') {
      setView('idle');
      resultBuf.set('');
      reasoningBuf.set('');
    }
  };

  const handleSourceTabClick = (tab: SourceTab) => {
    if (isRunning || tab === sourceTab) return;
    setSourceTab(tab);
    // Different source = different content: drop cached results and chat.
    setModeCache({});
    setView('idle');
    clearRun();
    setSourceContent('');
    setSourceUrl(undefined);
  };

  // ── Result actions ─────────────────────────────────────────────────────

  const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'result';

  const download = (format: DownloadFormat) => {
    const label = modeLabel(resultMode || mode);
    if (format === 'svg') {
      const svg = document.querySelector('.summarize-result .mindmap-svg');
      if (svg) downloadBlob(svg.outerHTML, `${slug(label)}.svg`, 'image/svg+xml');
      return;
    }
    if (format === 'json') {
      const data = parseJson<{ name?: string; title?: string }>(result);
      const name = data?.name ?? data?.title ?? label;
      downloadBlob(data ? JSON.stringify(data, null, 2) : result, `${slug(String(name))}.json`,
        resultMode === 'recipe_jsonld' ? 'application/ld+json' : 'application/json');
      return;
    }
    let body = result;
    if (format === 'md') {
      body = `# ${label}\n\n${result}`;
      if (reasoning) body += `\n\n<details>\n<summary>Reasoning</summary>\n\n${reasoning}\n</details>`;
    }
    downloadBlob(body, `${slug(label)}.${format}`, format === 'md' ? 'text/markdown' : 'text/plain');
  };

  const copyResult = async () => {
    if (await copyText(result)) {
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    }
  };

  /** The URL the current result came from (YouTube or webpage), if any. */
  const resultSourceUrl = sourceUrl
    ?? (sourceTab === 'youtube' ? youtubeUrl.trim() || undefined
      : sourceTab === 'url' ? urlInput.trim() || undefined : undefined);

  /** JSON-LD for the recipe on screen: the result itself, or the exported JSON-LD of a Markdown recipe. */
  const recipeJsonLd = resultMode === 'recipe_jsonld' ? result
    : resultMode === 'recipe' ? modeCache.recipe_jsonld?.result ?? '' : '';

  const sendToMealie = async () => {
    if (!recipeJsonLd) return;
    setMealieSending(true);
    setMealieError('');
    setMealieLink('');
    try {
      const { url } = await api.sendRecipeToMealie(parseJson(recipeJsonLd) ?? recipeJsonLd, resultSourceUrl);
      setMealieLink(url);
    } catch (err) {
      setMealieError(err instanceof Error ? err.message : 'Sending to Mealie failed');
    } finally {
      setMealieSending(false);
    }
  };

  const generateJsonLD = async () => {
    if (!result || resultMode !== 'recipe') return;
    setJsonLdLoading(true);
    setJsonLdError('');
    try {
      const data = await api.convertRecipeToJsonLD(result, resultSourceUrl);
      setModeCache(prev => ({
        ...prev,
        recipe_jsonld: { result: JSON.stringify(data, null, 2), reasoning: '', outputType: 'json:recipe' },
      }));
    } catch (err) {
      setJsonLdError(err instanceof Error ? err.message : 'Failed to generate JSON-LD');
    } finally {
      setJsonLdLoading(false);
    }
  };

  const copyJsonLD = async () => {
    const json = modeCache.recipe_jsonld?.result;
    if (json && await copyText(json)) {
      setJsonLdCopied(true);
      setTimeout(() => setJsonLdCopied(false), 2000);
    }
  };

  const handleReadAloud = async (text: string) => {
    if (ttsBlobUrlRef.current) { URL.revokeObjectURL(ttsBlobUrlRef.current); ttsBlobUrlRef.current = null; }
    setTtsAudioUrl(null);
    setTtsLoading(true);
    setTtsError('');
    try {
      const blob = await api.synthesizeSpeech(text, ttsVoice);
      const url = URL.createObjectURL(blob);
      ttsBlobUrlRef.current = url;
      setTtsAudioUrl(url);
    } catch (err) {
      setTtsError(err instanceof Error ? err.message : 'TTS generation failed — check voice model is downloaded');
    } finally {
      setTtsLoading(false);
    }
  };

  const phaseLabel = statusDetail
    || (view === 'thinking' ? (reasoning ? 'Reasoning…' : 'Thinking…') : '')
    || (view === 'extracting' ? 'Extracting…' : view === 'transcribing' ? 'Transcribing…' : '');

  const showIndicator = view === 'extracting' || view === 'transcribing' || view === 'thinking'
    || (view === 'streaming' && !behavior.streamText);
  const showOutput = (view === 'done' || (view === 'streaming' && behavior.streamText)) && result;
  const sourceDisabled = isRunning;

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="summarize-page">
      <div className="summarize-inner">

        <Link to="/" className="summarize-back">
          <ArrowLeft size={15} aria-hidden="true" />
          All tools
        </Link>

        <div className="summarize-header">
          <div className="summarize-header-icon">
            <Sparkles size={20} aria-hidden="true" />
          </div>
          <div>
            <h1 className="summarize-title">Summarize</h1>
            <p className="summarize-subtitle">Extract insights from any content using AI</p>
          </div>
        </div>

        {/* Source tabs */}
        <div className="summarize-tabs" role="tablist" aria-label="Source type">
          {SOURCE_TABS.map(tab => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={sourceTab === tab.id}
              className={`summarize-tab${sourceTab === tab.id ? ' active' : ''}`}
              onClick={() => handleSourceTabClick(tab.id)}
              disabled={sourceDisabled}
            >
              <tab.icon size={14} aria-hidden="true" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Source input */}
        {sourceTab === 'text' && (
          <textarea
            className="summarize-textarea"
            value={content}
            onChange={e => setContent(e.target.value)}
            placeholder="Paste your text, article, transcript, or notes here…"
            rows={10}
            disabled={sourceDisabled}
            aria-label="Content to summarize"
          />
        )}

        {sourceTab === 'audio' && (
          <>
            <DropZone
              accept={AUDIO_ACCEPT}
              file={audioFile}
              onFile={setAudioFile}
              label="Drop audio or video file here, or click to browse"
              hint="MP3, WAV, M4A, FLAC, OGG, MP4, MKV, MOV, …"
              icon={Mic}
              disabled={sourceDisabled}
              maxSizeMb={maxUploadSizeMb}
              onSizeError={(msg) => { setView('error'); setErrorMsg(msg); }}
            />
            <EnhancementPanel value={enhancement} onChange={setEnhancement} models={audioModels} disabled={sourceDisabled} />
          </>
        )}

        {sourceTab === 'pdf' && (
          <DropZone
            accept=".pdf"
            file={pdfFile}
            onFile={setPdfFile}
            label="Drop a PDF here, or click to browse"
            hint="PDF files only"
            icon={FileIcon}
            disabled={sourceDisabled}
            maxSizeMb={maxUploadSizeMb}
            onSizeError={(msg) => { setView('error'); setErrorMsg(msg); }}
          />
        )}

        {sourceTab === 'image' && (
          <DropZone
            accept=".jpg,.jpeg,.png,.webp,.gif"
            file={imageFile}
            onFile={setImageFile}
            label="Drop an image here, or click to browse"
            hint="JPG, PNG, WebP, GIF — requires a vision-capable model"
            icon={ImageIcon}
            disabled={sourceDisabled}
            maxSizeMb={maxUploadSizeMb}
            onSizeError={(msg) => { setView('error'); setErrorMsg(msg); }}
          />
        )}

        {sourceTab === 'youtube' && (
          <div className="summarize-url-block">
            <input
              type="url"
              className="summarize-url-input"
              value={youtubeUrl}
              onChange={e => setYoutubeUrl(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
              placeholder="https://www.youtube.com/watch?v=…"
              disabled={sourceDisabled}
              aria-label="YouTube URL"
            />
            <label className="summarize-caption-toggle">
              <input
                type="checkbox"
                checked={preferCaptions}
                onChange={e => setPreferCaptions(e.target.checked)}
                disabled={sourceDisabled}
              />
              Use captions when available (faster)
            </label>
          </div>
        )}

        {sourceTab === 'url' && (
          <input
            type="url"
            className="summarize-url-input"
            value={urlInput}
            onChange={e => setUrlInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSubmit()}
            placeholder="https://…"
            disabled={sourceDisabled}
            aria-label="Webpage URL"
          />
        )}

        {/* Mode + submit */}
        <div className="summarize-controls">
          <div className="summarize-modes" role="group" aria-label="Mode">
            {modes.map(m => {
              const hasCached = Boolean(modeCache[m.id] || (m.id === 'recipe' && modeCache.recipe_jsonld));
              return (
                <button
                  key={m.id}
                  className={['summarize-mode-btn', mode === m.id ? 'active' : '', hasCached ? 'has-result' : '']
                    .filter(Boolean).join(' ')}
                  onClick={() => handleModeClick(m.id)}
                  disabled={isRunning}
                  aria-pressed={mode === m.id}
                  title={hasCached ? `${m.label} — click to view result` : m.hint}
                >
                  {m.label}
                  {hasCached && <span className="summarize-mode-dot" aria-hidden="true" />}
                </button>
              );
            })}
          </div>

          {mode === 'recipe' && (
            <div className="summarize-recipe-format">
              <span className="summarize-recipe-format-label">Output format:</span>
              <button
                className={`summarize-recipe-format-btn${recipeFormat === 'jsonld' ? ' active' : ''}`}
                onClick={() => setRecipeFormat('jsonld')}
                disabled={isRunning}
                aria-pressed={recipeFormat === 'jsonld'}
              >
                <FileJson size={13} aria-hidden="true" />
                JSON-LD
              </button>
              <button
                className={`summarize-recipe-format-btn${recipeFormat === 'markdown' ? ' active' : ''}`}
                onClick={() => setRecipeFormat('markdown')}
                disabled={isRunning}
                aria-pressed={recipeFormat === 'markdown'}
              >
                Markdown
              </button>
            </div>
          )}

          {mode === 'mtg_precon' && (
            <details className="summarize-mode-options" open={Boolean(mtgDecklist)}>
              <summary>Upgraded decklist (optional)</summary>
              <p className="summarize-mode-options-hint">
                Linked Archidekt decks are read automatically. For Moxfield or anything else, paste the
                exported list here for exact results — a <code>Cuts</code> or <code>Sideboard</code> section is
                treated as the cards removed.
              </p>
              <textarea
                className="summarize-textarea summarize-textarea--compact"
                value={mtgDecklist}
                onChange={e => setMtgDecklist(e.target.value)}
                placeholder={'1 Sol Ring\n1 Arcane Signet\n…\n\nCuts\n1 Mind Stone'}
                rows={6}
                disabled={isRunning}
                aria-label="Upgraded decklist"
              />
            </details>
          )}

          {isRunning ? (
            <button className="summarize-submit-btn summarize-submit-btn--stop" onClick={stop}>
              <Square size={13} aria-hidden="true" />
              Stop
            </button>
          ) : (
            <button className="summarize-submit-btn" onClick={handleSubmit} disabled={!canSubmit}>
              <Sparkles size={15} aria-hidden="true" />
              {modeCache[mode] ? 'Re-run' : mode === 'transcript' ? 'Transcribe' : 'Run'}
            </button>
          )}
        </div>

        {ttsEnabled && ttsAudioUrl && (
          <div className="summarize-tts-bar">
            <Volume2 size={14} className="summarize-tts-bar-icon" aria-hidden="true" />
            <audio className="summarize-tts-audio" src={ttsAudioUrl} controls autoPlay />
            <button
              className="summarize-tts-bar-close"
              onClick={() => {
                if (ttsBlobUrlRef.current) { URL.revokeObjectURL(ttsBlobUrlRef.current); ttsBlobUrlRef.current = null; }
                setTtsAudioUrl(null);
              }}
              aria-label="Close audio player"
            >
              <X size={13} />
            </button>
          </div>
        )}

        {/* Results */}
        {view !== 'idle' && (
          <div className="summarize-result">
            <div className="summarize-result-header">
              <h2 className="summarize-result-title">{modeLabel(resultMode || mode) || 'Result'}</h2>
              {view === 'done' && result && (
                <div className="summarize-result-actions">
                  {behavior.rawToggle && (
                    <button
                      className={`summarize-action-btn${!rendered ? ' active' : ''}`}
                      onClick={() => setRendered(r => !r)}
                      title={rendered ? 'Show raw output' : `Show ${behavior.renderedLabel.toLowerCase()}`}
                      aria-pressed={!rendered}
                    >
                      <Code size={14} aria-hidden="true" />
                      {rendered ? 'Raw' : behavior.renderedLabel}
                    </button>
                  )}
                  <button className={`summarize-action-btn${isCopied ? ' copied' : ''}`} onClick={copyResult}>
                    <Copy size={14} aria-hidden="true" />
                    {isCopied ? 'Copied!' : 'Copy'}
                  </button>
                  {ttsEnabled && behavior.tts && (
                    <button
                      className="summarize-action-btn"
                      onClick={() => handleReadAloud(result)}
                      disabled={ttsLoading}
                      title="Read aloud"
                    >
                      {ttsLoading
                        ? <><Loader size={13} className="summarize-tts-spin" aria-hidden="true" /> Generating…</>
                        : <><Volume2 size={13} aria-hidden="true" /> Read Aloud</>}
                    </button>
                  )}
                  {ttsError && <span className="summarize-tts-error" role="alert">{ttsError}</span>}
                  {behavior.downloads
                    .filter(f => f !== 'svg' || (outputType === 'mindmap' && rendered))
                    .map(f => (
                      <button key={f} className="summarize-action-btn" onClick={() => download(f)}>
                        <Download size={14} aria-hidden="true" />
                        .{f}
                      </button>
                    ))}
                  {resultMode === 'recipe' && (
                    modeCache.recipe_jsonld ? (
                      <>
                        <button
                          className={`summarize-action-btn${jsonLdCopied ? ' copied' : ''}`}
                          onClick={copyJsonLD}
                          title="Copy JSON-LD"
                        >
                          <FileJson size={14} aria-hidden="true" />
                          {jsonLdCopied ? 'Copied!' : 'Copy JSON-LD'}
                        </button>
                        <button
                          className="summarize-action-btn"
                          onClick={() => downloadBlob(modeCache.recipe_jsonld!.result, 'recipe.json', 'application/ld+json')}
                        >
                          <Download size={14} aria-hidden="true" />
                          .json
                        </button>
                      </>
                    ) : (
                      <button
                        className="summarize-action-btn"
                        onClick={generateJsonLD}
                        disabled={jsonLdLoading}
                        title="Generate JSON-LD for Mealie"
                      >
                        <FileJson size={14} aria-hidden="true" />
                        {jsonLdLoading ? 'Generating…' : 'Export JSON-LD'}
                      </button>
                    )
                  )}
                  {jsonLdError && <span className="summarize-jsonld-error" role="alert">{jsonLdError}</span>}
                  {mealieReady && recipeJsonLd && (
                    mealieLink ? (
                      <a className="summarize-action-btn" href={mealieLink} target="_blank" rel="noreferrer">
                        <ExternalLink size={14} aria-hidden="true" />
                        Open in Mealie
                      </a>
                    ) : (
                      <button
                        className="summarize-action-btn"
                        onClick={sendToMealie}
                        disabled={mealieSending}
                        title="Create this recipe in Mealie"
                      >
                        {mealieSending
                          ? <><Loader size={13} className="summarize-tts-spin" aria-hidden="true" /> Sending…</>
                          : <><ChefHat size={14} aria-hidden="true" /> Send to Mealie</>}
                      </button>
                    )
                  )}
                  {mealieError && <span className="summarize-jsonld-error" role="alert">{mealieError}</span>}
                  <button className="summarize-action-btn summarize-action-btn--ghost" onClick={reset}>
                    <RotateCcw size={14} aria-hidden="true" />
                    New
                  </button>
                </div>
              )}
            </div>

            {showIndicator && (
              <div className="summarize-thinking" aria-live="polite">
                <span className="summarize-thinking-dot" />
                <span className="summarize-thinking-dot" />
                <span className="summarize-thinking-dot" />
                <span className="summarize-thinking-label">{phaseLabel || 'Working…'}</span>
              </div>
            )}

            {view === 'error' && (
              <div className="summarize-error" role="alert">
                <AlertTriangle size={16} aria-hidden="true" />
                <span>{errorMsg}</span>
                <button className="summarize-action-btn" onClick={reset}>Try again</button>
              </div>
            )}

            {view !== 'error' && warnings.map(w => (
              <div key={w} className="summarize-warning" role="status">
                <AlertTriangle size={16} aria-hidden="true" />
                <span>{w}</span>
              </div>
            ))}

            {/* Live reasoning while the model thinks; collapsible afterwards */}
            {reasoning && (view === 'thinking' || view === 'streaming' || view === 'done') && (
              <details className="summarize-reasoning">
                <summary className="summarize-reasoning-summary">
                  {view === 'done' ? 'Reasoning' : 'Reasoning (live)'}
                  <span className="summarize-reasoning-lines">
                    {reasoning.split('\n').filter(Boolean).length} lines
                  </span>
                </summary>
                <pre className="summarize-reasoning-body">{reasoning}</pre>
              </details>
            )}

            {showOutput && (
              <ResultView
                text={result}
                outputType={outputType}
                rendered={rendered}
                streaming={view === 'streaming'}
                sourceUrl={sourceUrl}
              />
            )}

            {view === 'done' && result && behavior.translatable && (
              <TranslatePanel
                text={result}
                ttsEnabled={ttsEnabled}
                ttsLoading={ttsLoading}
                onReadAloud={handleReadAloud}
              />
            )}
          </div>
        )}

        {sourceContent && <ChatPanel sourceContent={sourceContent} />}

      </div>
    </div>
  );
}
