import { useState, useRef, useEffect, useCallback } from 'react';
import { ArrowLeft, Upload, Copy, Download, Edit3, RotateCcw, Mic, ChevronDown, Scissors } from 'lucide-react';
import { Link } from 'react-router-dom';
import * as api from '../api/client';
import type { AudioModelMap, EnhancementOptions, FileMeta, Segment } from '../types';

// Stable color palette for speaker labels
const SPEAKER_COLORS = ['#0891b2','#7c3aed','#059669','#dc2626','#d97706','#db2777'];
function speakerColor(speaker: string | null | undefined): string {
  if (!speaker) return 'transparent';
  const idx = parseInt(speaker.replace(/\D/g, '') || '0', 10) % SPEAKER_COLORS.length;
  return SPEAKER_COLORS[idx];
}
import EnhancementPanel, { DEFAULT_ENHANCEMENT } from '../components/EnhancementPanel';
import './Transcribe.css';

const ACCEPTED_EXTENSIONS = [
  '.mp3', '.wav', '.m4a', '.flac', '.ogg', '.webm', '.opus', '.aac', '.wma',
  '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m4v',
];
const ACCEPTED_MIME = ACCEPTED_EXTENSIONS.join(',');
const POLL_INTERVAL_MS = 1200;

type View = 'upload' | 'progress' | 'result' | 'error';
type ActiveTab = 'transcribe' | 'files';

export default function Transcribe() {
  const [view, setView]           = useState<View>('upload');
  const [activeTab, setActiveTab] = useState<ActiveTab>('transcribe');
  const [filename, setFilename]   = useState('');
  const [progressLabel, setProgressLabel] = useState('');
  const [transcript, setTranscript]       = useState('');
  const [segments, setSegments]           = useState<Segment[]>([]);
  const [currentTime, setCurrentTime]     = useState(0);
  const [playbackRate, setPlaybackRate]   = useState(1);
  const [errorMsg, setErrorMsg]           = useState('');
  const [wordCount, setWordCount]         = useState(0);
  const [isEditing, setIsEditing]         = useState(false);
  const [isCopied, setIsCopied]           = useState(false);
  const [isDragging, setIsDragging]       = useState(false);
  const [exportOpen, setExportOpen]       = useState(false);
  const [clipStart,  setClipStart]        = useState<number | null>(null);
  const [clipEnd,    setClipEnd]          = useState<number | null>(null);
  const [clipState,  setClipState]        = useState<'idle' | 'extracting' | 'ready' | 'error'>('idle');
  const [clipId,     setClipId]           = useState<string | null>(null);
  const [diarizeState, setDiarizeState]   = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [diarizeError, setDiarizeError]   = useState('');
  const [files, setFiles]                 = useState<FileMeta[]>([]);
  const [filesLoading, setFilesLoading]   = useState(false);
  const [enhancement, setEnhancement]     = useState<EnhancementOptions>(DEFAULT_ENHANCEMENT);
  const [audioModels, setAudioModels]     = useState<AudioModelMap | undefined>(undefined);

  const jobIdRef    = useRef<string | null>(null);
  const pollRef     = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef  = useRef<HTMLInputElement>(null);
  const audioRef    = useRef<HTMLAudioElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const exportRef   = useRef<HTMLDivElement>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // Load audio model status and settings defaults on mount
  useEffect(() => {
    api.getAudioModels().then(setAudioModels).catch(() => {});
    api.getSettings().then(s => {
      setEnhancement({
        normalize: s.enhance_normalize === 'true',
        denoise:   s.enhance_denoise   === 'true',
        isolate:   s.enhance_isolate   === 'true',
        upsample:  s.enhance_upsample  === 'true',
      });
    }).catch(() => {});
  }, []);

  // Track audio playback position and speed
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onRateChange = () => setPlaybackRate(audio.playbackRate);
    audio.addEventListener('timeupdate', onTimeUpdate);
    audio.addEventListener('ratechange', onRateChange);
    return () => {
      audio.removeEventListener('timeupdate', onTimeUpdate);
      audio.removeEventListener('ratechange', onRateChange);
    };
  }, [view]); // re-bind when result view mounts

  // Keyboard shortcuts for audio player
  useEffect(() => {
    if (view !== 'result') return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      const audio = audioRef.current;
      if (!audio) return;
      switch (e.key) {
        case ' ':
        case 'k':
        case 'K':
          e.preventDefault();
          audio.paused ? audio.play() : audio.pause();
          break;
        case 'j':
        case 'J':
          audio.currentTime = Math.max(0, audio.currentTime - 10);
          break;
        case 'l':
        case 'L':
          audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 10);
          break;
        case ',':
          audio.currentTime = Math.max(0, audio.currentTime - 1);
          break;
        case '.':
          audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 1);
          break;
        case '[':
          audio.playbackRate = Math.max(0.25, audio.playbackRate - 0.25);
          break;
        case ']':
          audio.playbackRate = Math.min(2, audio.playbackRate + 0.25);
          break;
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [view]);

  // Close export dropdown on outside click
  useEffect(() => {
    if (!exportOpen) return;
    const handler = (e: MouseEvent) => {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setExportOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [exportOpen]);

  // ── File handling ──────────────────────────────────────────────────────
  const handleFile = useCallback((file: File) => {
    const ext = '.' + file.name.split('.').pop()!.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      setErrorMsg(`Unsupported file type: ${ext}. Accepted: ${ACCEPTED_EXTENSIONS.join(', ')}`);
      setView('error');
      return;
    }
    uploadFile(file);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const uploadFile = async (file: File) => {
    setFilename(file.name);
    setProgressLabel('Uploading…');
    setView('progress');

    try {
      const { job_id } = await api.uploadFile(file, enhancement);
      jobIdRef.current = job_id;
      setProgressLabel('Transcribing…');
      startPolling(job_id);
    } catch (err) {
      showError((err as Error).message);
    }
  };

  const startPolling = (jobId: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const job = await api.getStatus(jobId);
        if (job.status === 'done') {
          stopPolling();
          showResult(job.result ?? '', job.segments ?? []);
        } else if (job.status === 'error') {
          stopPolling();
          showError(job.error ?? 'Transcription failed.');
        } else if (job.status === 'enhancing') {
          setProgressLabel(job.status_detail || 'Enhancing audio…');
        } else if (job.status === 'processing') {
          setProgressLabel('Transcribing… (this may take a moment)');
        }
      } catch {
        // network hiccup — keep polling
      }
    }, POLL_INTERVAL_MS);
  };

  const showResult = (text: string, segs: Segment[]) => {
    setTranscript(text);
    setSegments(segs);
    const words = text.trim().split(/\s+/).filter(Boolean).length;
    setWordCount(words);
    setView('result');
  };

  // Set audio src after the result view renders (audioRef is null until then)
  useEffect(() => {
    if (view === 'result' && audioRef.current && jobIdRef.current) {
      audioRef.current.src = api.getAudioUrl(jobIdRef.current);
    }
  }, [view]);

  const showError = (msg: string) => {
    stopPolling();
    setErrorMsg(msg);
    setView('error');
  };

  const reset = () => {
    stopPolling();
    jobIdRef.current = null;
    setView('upload');
    setTranscript('');
    setSegments([]);
    setCurrentTime(0);
    setPlaybackRate(1);
    setIsEditing(false);
    setIsCopied(false);
    setClipStart(null);
    setClipEnd(null);
    setClipState('idle');
    setClipId(null);
    setDiarizeState('idle');
    setDiarizeError('');
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
    }
  };

  // ── Diarization ────────────────────────────────────────────────────────
  const handleDiarize = async () => {
    if (!jobIdRef.current) return;
    setDiarizeState('running');
    setDiarizeError('');
    try {
      const result = await api.diarizeJob(jobIdRef.current);
      setSegments(result.segments);
      setDiarizeState('done');
    } catch (err) {
      setDiarizeError((err as Error).message);
      setDiarizeState('error');
    }
  };

  // ── Clip extraction ────────────────────────────────────────────────────
  const handleExtractClip = async () => {
    if (clipStart === null || clipEnd === null || !jobIdRef.current) return;
    setClipState('extracting');
    setClipId(null);
    try {
      const { clip_id } = await api.extractClip(jobIdRef.current, clipStart, clipEnd);
      setClipId(clip_id);
      setClipState('ready');
    } catch (err) {
      setClipState('error');
    }
  };

  // ── Drag & drop ────────────────────────────────────────────────────────
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };
  const onDragLeave = () => setIsDragging(false);
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  // ── Copy ───────────────────────────────────────────────────────────────
  const copyTranscript = async () => {
    try {
      await navigator.clipboard.writeText(transcript);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch {
      // clipboard denied
    }
  };

  // ── Seek (click-to-seek) ───────────────────────────────────────────────
  const seekTo = (time: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = time;
    audio.play();
  };

  const handleSegmentClick = (seg: Segment, e: React.MouseEvent | React.KeyboardEvent) => {
    if ('shiftKey' in e && e.shiftKey) {
      // Shift-click: set clip end (must be after start)
      if (clipStart !== null && seg.end > clipStart) {
        setClipEnd(seg.end);
        setClipState('idle');
        setClipId(null);
      }
    } else {
      // Normal click: seek and set clip start
      seekTo(seg.start);
      setClipStart(seg.start);
      setClipEnd(null);
      setClipState('idle');
      setClipId(null);
    }
  };

  // ── File browser ───────────────────────────────────────────────────────
  const loadFiles = async () => {
    setFilesLoading(true);
    try {
      setFiles(await api.getFiles());
    } catch {
      setFiles([]);
    } finally {
      setFilesLoading(false);
    }
  };

  const handleTabChange = (tab: ActiveTab) => {
    setActiveTab(tab);
    if (tab === 'files') loadFiles();
  };

  const retranscribeFile = async (jobId: string, name: string) => {
    setActiveTab('transcribe');
    setFilename(name);
    setProgressLabel('Starting transcription…');
    setView('progress');
    try {
      const { job_id } = await api.retranscribe(jobId, enhancement);
      jobIdRef.current = job_id;
      setProgressLabel('Transcribing…');
      startPolling(job_id);
    } catch (err) {
      showError((err as Error).message);
    }
  };

  // ── Helpers ────────────────────────────────────────────────────────────
  const fmtSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  };

  const fmtDate = (iso: string) => {
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  };

  const hasSegments = segments.length > 0;

  return (
    <div className="transcribe-page">
      <div className="transcribe-inner">

        {/* Back link */}
        <Link to="/" className="transcribe-back">
          <ArrowLeft size={15} aria-hidden="true" />
          All tools
        </Link>

        {/* Page header */}
        <div className="transcribe-header">
          <div className="transcribe-header-icon">
            <Mic size={20} aria-hidden="true" />
          </div>
          <div>
            <h1 className="transcribe-title">Transcribe</h1>
            <p className="transcribe-subtitle">Audio &amp; video to text using Whisper</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="transcribe-tabs" role="tablist">
          <button
            className={`transcribe-tab ${activeTab === 'transcribe' ? 'active' : ''}`}
            role="tab"
            aria-selected={activeTab === 'transcribe'}
            onClick={() => handleTabChange('transcribe')}
          >
            Transcribe
          </button>
          <button
            className={`transcribe-tab ${activeTab === 'files' ? 'active' : ''}`}
            role="tab"
            aria-selected={activeTab === 'files'}
            onClick={() => handleTabChange('files')}
          >
            File history
          </button>
        </div>

        {/* ── Transcribe panel ──────────────────────────────────────────── */}
        {activeTab === 'transcribe' && (
          <div role="tabpanel">

            {/* Upload */}
            {view === 'upload' && (
              <>
                <div
                  className={`transcribe-dropzone ${isDragging ? 'dragging' : ''}`}
                  onDragOver={onDragOver}
                  onDragLeave={onDragLeave}
                  onDrop={onDrop}
                  onClick={() => fileInputRef.current?.click()}
                  role="button"
                  tabIndex={0}
                  aria-label="Drop audio or video file or click to browse"
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click(); }}
                >
                  <Upload size={32} className="transcribe-dropzone-icon" aria-hidden="true" />
                  <p className="transcribe-dropzone-title">Drag &amp; drop audio or video here</p>
                  <p className="transcribe-dropzone-sub">or click to browse</p>
                  <p className="transcribe-dropzone-formats">
                    MP3 · WAV · M4A · FLAC · OGG · WEBM · OPUS · AAC · MP4 · MKV · MOV
                  </p>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={ACCEPTED_MIME}
                    aria-hidden="true"
                    hidden
                    onChange={e => {
                      const file = e.target.files?.[0];
                      if (file) handleFile(file);
                    }}
                  />
                </div>
                <EnhancementPanel
                  value={enhancement}
                  onChange={setEnhancement}
                  models={audioModels}
                />
              </>
            )}

            {/* Progress */}
            {view === 'progress' && (
              <div className="transcribe-progress" aria-live="polite">
                <div className="transcribe-progress-file">
                  <Mic size={16} aria-hidden="true" />
                  <span>{filename}</span>
                </div>
                <div className="transcribe-progress-track" role="progressbar" aria-label="Transcription progress">
                  <div className="transcribe-progress-bar" />
                </div>
                <p className="transcribe-progress-label">{progressLabel}</p>
              </div>
            )}

            {/* Result */}
            {view === 'result' && (
              <div className="transcribe-result">
                <div className="transcribe-result-header">
                  <div className="transcribe-result-meta">
                    <h2 className="transcribe-result-heading">Transcription</h2>
                    <span className="transcribe-result-words">
                      {wordCount.toLocaleString()} word{wordCount !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <div className="transcribe-result-actions">
                    {hasSegments && (
                      <button
                        className={`transcribe-btn transcribe-btn--secondary ${isEditing ? 'active' : ''}`}
                        onClick={() => {
                          setIsEditing(e => !e);
                          if (!isEditing) setTimeout(() => textareaRef.current?.focus(), 0);
                        }}
                        aria-pressed={isEditing}
                      >
                        <Edit3 size={15} aria-hidden="true" />
                        {isEditing ? 'Done' : 'Edit'}
                      </button>
                    )}
                    {!hasSegments && (
                      <button
                        className={`transcribe-btn transcribe-btn--secondary ${isEditing ? 'active' : ''}`}
                        onClick={() => {
                          setIsEditing(e => !e);
                          if (!isEditing) setTimeout(() => textareaRef.current?.focus(), 0);
                        }}
                        aria-pressed={isEditing}
                      >
                        <Edit3 size={15} aria-hidden="true" />
                        {isEditing ? 'Done' : 'Edit'}
                      </button>
                    )}
                    <button
                      className={`transcribe-btn transcribe-btn--secondary ${isCopied ? 'copied' : ''}`}
                      onClick={copyTranscript}
                    >
                      <Copy size={15} aria-hidden="true" />
                      {isCopied ? 'Copied!' : 'Copy'}
                    </button>

                    {/* Export dropdown */}
                    <div className="transcribe-export-wrap" ref={exportRef}>
                      <button
                        className="transcribe-btn transcribe-btn--secondary transcribe-export-btn"
                        onClick={() => setExportOpen(o => !o)}
                        aria-haspopup="menu"
                        aria-expanded={exportOpen}
                      >
                        <Download size={15} aria-hidden="true" />
                        Export
                        <ChevronDown size={13} aria-hidden="true" className={`transcribe-chevron${exportOpen ? ' open' : ''}`} />
                      </button>
                      {exportOpen && (
                        <div className="transcribe-export-menu" role="menu">
                          <a
                            role="menuitem"
                            className="transcribe-export-item"
                            href={api.getExportUrl(jobIdRef.current!)}
                            download
                            onClick={() => setExportOpen(false)}
                          >
                            TXT — plain text
                          </a>
                          {hasSegments && (
                            <>
                              <a
                                role="menuitem"
                                className="transcribe-export-item"
                                href={api.getSrtExportUrl(jobIdRef.current!)}
                                download
                                onClick={() => setExportOpen(false)}
                              >
                                SRT — subtitles
                              </a>
                              <a
                                role="menuitem"
                                className="transcribe-export-item"
                                href={api.getVttExportUrl(jobIdRef.current!)}
                                download
                                onClick={() => setExportOpen(false)}
                              >
                                VTT — web subtitles
                              </a>
                            </>
                          )}
                        </div>
                      )}
                    </div>

                    <button className="transcribe-btn transcribe-btn--ghost" onClick={reset}>
                      <RotateCcw size={15} aria-hidden="true" />
                      New file
                    </button>
                  </div>
                </div>

                {/* Audio player */}
                <div className="transcribe-player-wrap">
                  {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                  <audio
                    ref={audioRef}
                    className="transcribe-audio"
                    controls
                    aria-label="Uploaded audio"
                    aria-describedby="transcribe-transcript"
                  />
                  {playbackRate !== 1 && (
                    <span className="transcribe-speed-badge" aria-label={`Playback speed ${playbackRate}x`}>
                      {playbackRate}x
                    </span>
                  )}
                </div>

                {/* Keyboard shortcut hint */}
                <p className="transcribe-shortcuts-hint" aria-label="Keyboard shortcuts">
                  <kbd>Space</kbd> play/pause
                  <span className="transcribe-shortcuts-sep">·</span>
                  <kbd>J</kbd>/<kbd>L</kbd> ±10s
                  <span className="transcribe-shortcuts-sep">·</span>
                  <kbd>[</kbd>/<kbd>]</kbd> speed
                </p>

                {/* Speaker diarization panel */}
                {hasSegments && (
                  <div className="transcribe-diarize-panel">
                    <button
                      className="transcribe-btn transcribe-btn--secondary transcribe-btn--sm"
                      onClick={handleDiarize}
                      disabled={diarizeState === 'running'}
                      title="Identify speakers in the transcript"
                    >
                      {diarizeState === 'running' ? 'Diarizing…' : diarizeState === 'done' ? 'Re-diarize' : 'Identify speakers'}
                    </button>
                    {diarizeState === 'done' && (
                      <span className="transcribe-diarize-status">Speaker labels applied</span>
                    )}
                    {diarizeState === 'error' && (
                      <span className="transcribe-diarize-error">{diarizeError}</span>
                    )}
                  </div>
                )}

                {/* Click-to-seek segments OR editable textarea */}
                {hasSegments && !isEditing ? (
                  <>
                    <div
                      id="transcribe-transcript"
                      className="transcribe-segments"
                      aria-label="Transcription — click to seek, shift+click to select clip end"
                      role="region"
                    >
                      {segments.map((seg, i) => {
                        const active = currentTime >= seg.start && currentTime < seg.end;
                        const inClip = clipStart !== null && clipEnd !== null
                          ? seg.start >= clipStart && seg.end <= clipEnd
                          : clipStart !== null && seg.start === clipStart;
                        const hasSpeaker = (seg as Segment & { speaker?: string }).speaker != null;
                        const speaker = (seg as Segment & { speaker?: string }).speaker;
                        const showSpeakerLabel = hasSpeaker && (i === 0 || (segments[i - 1] as Segment & { speaker?: string }).speaker !== speaker);
                        return (
                          <span key={i} className="transcribe-segment-wrap">
                            {showSpeakerLabel && (
                              <span
                                className="transcribe-speaker-label"
                                style={{ color: speakerColor(speaker) }}
                                aria-label={`Speaker: ${speaker}`}
                              >
                                {speaker}
                              </span>
                            )}
                            <span
                              className={`transcribe-segment${active ? ' active' : ''}${inClip ? ' clip-selected' : ''}`}
                              onClick={e => handleSegmentClick(seg, e)}
                              role="button"
                              tabIndex={0}
                              aria-label={`${seg.text.trim()} at ${Math.floor(seg.start / 60)}:${String(Math.floor(seg.start % 60)).padStart(2, '0')}`}
                              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleSegmentClick(seg, e); } }}
                            >
                              {seg.text}{' '}
                            </span>
                          </span>
                        );
                      })}
                    </div>

                    {/* Clip extraction panel */}
                    {clipStart !== null && (
                      <div className="transcribe-clip-panel">
                        <Scissors size={13} className="transcribe-clip-icon" aria-hidden="true" />
                        <span className="transcribe-clip-range">
                          {clipEnd !== null
                            ? `${clipStart.toFixed(1)}s – ${clipEnd.toFixed(1)}s`
                            : `From ${clipStart.toFixed(1)}s — shift+click end segment`}
                        </span>
                        {clipEnd !== null && (
                          <button
                            className="transcribe-btn transcribe-btn--secondary transcribe-btn--sm"
                            onClick={handleExtractClip}
                            disabled={clipState === 'extracting'}
                          >
                            {clipState === 'extracting' ? 'Extracting…' : 'Extract clip'}
                          </button>
                        )}
                        {clipState === 'ready' && clipId && jobIdRef.current && (
                          <a
                            className="transcribe-btn transcribe-btn--primary transcribe-btn--sm"
                            href={api.getClipDownloadUrl(jobIdRef.current, clipId)}
                            download
                          >
                            <Download size={13} aria-hidden="true" />
                            Download clip
                          </a>
                        )}
                        <button
                          className="transcribe-btn transcribe-btn--ghost transcribe-btn--sm"
                          onClick={() => { setClipStart(null); setClipEnd(null); setClipState('idle'); setClipId(null); }}
                          aria-label="Clear clip selection"
                        >
                          ×
                        </button>
                      </div>
                    )}
                  </>
                ) : (
                  <textarea
                    id="transcribe-transcript"
                    ref={textareaRef}
                    className={`transcribe-textarea ${isEditing ? 'editable' : ''}`}
                    value={transcript}
                    readOnly={!isEditing}
                    onChange={e => setTranscript(e.target.value)}
                    spellCheck={false}
                    aria-label="Transcription text"
                  />
                )}
              </div>
            )}

            {/* Error */}
            {view === 'error' && (
              <div className="transcribe-error" role="alert" aria-live="assertive">
                <div className="transcribe-error-icon" aria-hidden="true">!</div>
                <p className="transcribe-error-msg">{errorMsg}</p>
                <button className="transcribe-btn transcribe-btn--primary" onClick={reset}>
                  Try again
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── Files panel ───────────────────────────────────────────────── */}
        {activeTab === 'files' && (
          <div role="tabpanel">
            {filesLoading && (
              <p className="transcribe-files-empty">Loading…</p>
            )}
            {!filesLoading && files.length === 0 && (
              <div className="transcribe-files-empty">
                <Mic size={32} className="transcribe-files-empty-icon" aria-hidden="true" />
                <p>No files uploaded yet.</p>
                <p className="transcribe-files-empty-sub">Files you transcribe will appear here.</p>
              </div>
            )}
            {!filesLoading && files.length > 0 && (
              <ul className="transcribe-files-list" aria-label="Uploaded files">
                {files.map(meta => (
                  <li key={meta.job_id} className="transcribe-file-item">
                    <Mic size={16} className="transcribe-file-icon" aria-hidden="true" />
                    <div className="transcribe-file-info">
                      <span className="transcribe-file-name">
                        {meta.filename ?? meta.audio_file}
                      </span>
                      <span className="transcribe-file-meta">
                        {fmtSize(meta.size)} · {fmtDate(meta.uploaded_at)}
                      </span>
                    </div>
                    <button
                      className="transcribe-btn transcribe-btn--primary transcribe-btn--sm"
                      onClick={() => retranscribeFile(meta.job_id, meta.filename ?? meta.audio_file)}
                    >
                      Transcribe
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
