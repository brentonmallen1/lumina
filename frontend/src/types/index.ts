export type JobStatus = 'pending' | 'enhancing' | 'processing' | 'done' | 'error';

// New persistent job types
export type PersistentJobStatus = 'pending' | 'queued' | 'running' | 'done' | 'error' | 'cancelled';
export type PersistentJobType = 'transcribe' | 'enhance' | 'extract' | 'summarize' | 'download';

export interface PersistentJob {
  id: string;
  type: PersistentJobType;
  status: PersistentJobStatus;
  status_detail: string;
  config: Record<string, unknown>;
  source_type: string | null;
  source_ref: string | null;
  source_title: string | null;
  thumbnail: string | null;
  content_hash: string | null;
  result: string | null;
  result_meta: {
    segments?: Segment[];
    language?: string;
    mode?: string;
    char_count?: number;
    [key: string]: unknown;
  };
  error: string | null;
  input_file: string | null;
  output_file: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  parent_job_id: string | null;
  batch_id: string | null;
}

export interface ActiveJobCounts {
  running: number;
  queued: number;
}

export interface CacheEntry {
  cached: boolean;
  content_hash: string;
  source_type?: string;
  title?: string;
  created_at?: string;
  accessed_at?: string;
  text_length?: number;
}

export interface CacheStats {
  total_entries: number;
  total_text_bytes: number;
  total_thumbnail_bytes: number;
}

export interface Word {
  word: string;
  start: number;
  end: number;
}

export interface Segment {
  start: number;
  end: number;
  text: string;
  words?: Word[];
}

export interface Job {
  status: JobStatus;
  status_detail: string;
  result: string | null;
  segments: Segment[];
  language: string;
  error: string | null;
  filename: string | null;
  audio_path: string;
}

export interface AppInfo {
  status: string;
  engine: string;
  model: string | null;
  gpu_available: boolean;
  gpu_name: string | null;
}

export interface FileMeta {
  job_id: string;
  filename: string | null;
  audio_file: string;
  size: number;
  uploaded_at: string;
}

export interface Settings {
  app_name: string;
  // Transcription
  transcription_engine: string;
  whisper_model_size: string;
  compute_type: string;
  language: string;
  // Application
  max_upload_size_mb: string;
  audio_cache_ttl_hours: string;
  // Security
  auth_enabled: string;
  auth_username: string;
  auth_password: string;
  api_key: string;
  // Ollama
  ollama_url: string;
  ollama_model: string;
  ollama_timeout: string;
  ollama_thinking_enabled: string;
  ollama_token_budget: string;
  ollama_context_size: string;
  ollama_vision_override: string;
  // Enhancement defaults
  enhance_normalize: string;
  enhance_denoise: string;
  enhance_isolate: string;
  enhance_upsample: string;
  // External integrations
  hf_token: string;
  // Text-to-Speech
  tts_enabled: string;
  tts_voice: string;
  // YouTube
  youtube_cookies: string;
}

export interface TTSVoice {
  name: string;
  gender: 'male' | 'female';
  accent: 'american' | 'british';
}

export type TTSVoiceMap = Record<string, TTSVoice>;

export interface TTSStatus {
  package: boolean;
  weights: boolean;
}

export interface EngineCapability {
  available: boolean;
  reason: string | null;
}

export interface Capabilities {
  gpu: boolean;
  engines: Record<string, EngineCapability>;
}

export interface OllamaModel {
  name: string;
  size: number;
  parameter_size: string;
}

export interface EnhancementOptions {
  normalize: boolean;
  denoise:   boolean;
  isolate:   boolean;
  upsample:  boolean;
}

export interface ModelStatus {
  package: boolean;
  weights: boolean;
}

export type AudioModelMap = Record<string, ModelStatus>;

export interface SettingsUpdateResponse {
  settings: Settings;
  restart_required: boolean;
}

export interface Prompt {
  id:            string;
  name:          string;
  mode:          string;
  system_prompt: string;
  template:      string;
  is_default:    boolean;
  created_at:    string;
  updated_at:    string;
}

export interface ChatMessage {
  role:    'user' | 'assistant';
  content: string;
}

export interface HistoryEntry {
  id:            string;
  mode:          string;
  source:        string;
  source_detail: string;
  result:        string;
  reasoning:     string;
  created_at:    string;
}

export interface Feed {
  id:             string;
  url:            string;
  title:          string;
  last_checked:   string | null;
  last_entry_id:  string | null;
  check_interval: number;
  auto_summarize: number;
  summarize_mode: string;
  created_at:     string;
}

export interface YouTubeVideoInfo {
  title:            string;
  duration_seconds: number | null;
  thumbnail:        string | null;
  uploader:         string;
}

export interface YouTubeDownloadJob {
  status:        'pending' | 'done' | 'error';
  status_detail: string;
  output_file:   string | null;
  filename:      string | null;
  error:         string | null;
}

export interface PipelineStep {
  step:        string;
  output_file: string;
  timestamp:   string;
}

export interface PipelineSession {
  session_id:    string;
  filename:      string | null;
  original_file: string;
  current_file:  string;
  steps:         PipelineStep[];
  transcription: string | null;
  status:        'idle' | 'processing' | 'error';
  status_detail: string;
  error:         string | null;
}

export interface FeedEntry {
  id:         string;
  feed_id:    string;
  entry_id:   string;
  title:      string;
  audio_url:  string;
  published:  string;
  status:     'pending' | 'downloading' | 'processing' | 'done' | 'error';
  job_id:     string | null;
  created_at: string;
}
