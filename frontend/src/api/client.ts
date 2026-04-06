import type { AppInfo, FileMeta, Job, Settings, SettingsUpdateResponse } from '../types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

// ── Engine ─────────────────────────────────────────────────────────────────

export function getInfo(): Promise<AppInfo> {
  return request<AppInfo>('/api/info');
}

export function getReady(): Promise<{ status: string; message: string }> {
  return request('/api/ready');
}

// ── Transcription ──────────────────────────────────────────────────────────

export function uploadFile(file: File): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('file', file);
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

export function getFiles(): Promise<FileMeta[]> {
  return request<FileMeta[]>('/api/files');
}

export function retranscribe(jobId: string): Promise<{ job_id: string }> {
  return request(`/api/retranscribe/${jobId}`, { method: 'POST' });
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
