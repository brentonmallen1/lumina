import { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef, type ReactNode } from 'react';
import type { PersistentJob, ActiveJobCounts } from '../types';
import * as api from '../api/client';

const POLL_INTERVAL_MS = 2000;
const LOCAL_STORAGE_KEY = 'lumina_active_jobs';
const TERMINAL = new Set(['done', 'error', 'cancelled']);

interface SubmitJobParams {
  job_type: string;
  source_type: string;
  source_ref: string;
  source_title?: string;
  config?: Record<string, unknown>;
}

interface JobContextValue {
  jobs: PersistentJob[];
  activeCounts: ActiveJobCounts;
  isLoading: boolean;
  error: string | null;
  refreshJobs: () => Promise<void>;
  submitJob: (params: SubmitJobParams) => Promise<PersistentJob>;
  cancelJob: (jobId: string) => Promise<void>;
  retryJob: (jobId: string) => Promise<void>;
}

const JobContext = createContext<JobContextValue | null>(null);

export function useJobs(): JobContextValue {
  const ctx = useContext(JobContext);
  if (!ctx) throw new Error('useJobs must be used within JobProvider');
  return ctx;
}

/** Cheap change check so unchanged polls don't re-render every consumer. */
function sameJob(a: PersistentJob | undefined, b: PersistentJob): boolean {
  return !!a && a.status === b.status && a.status_detail === b.status_detail
    && a.completed_at === b.completed_at && (a.result?.length ?? 0) === (b.result?.length ?? 0);
}

function mergeJobs(prev: PersistentJob[], updates: PersistentJob[]): PersistentJob[] {
  const map = new Map(prev.map(j => [j.id, j]));
  let changed = false;
  for (const job of updates) {
    if (!sameJob(map.get(job.id), job)) {
      map.set(job.id, job);
      changed = true;
    }
  }
  if (!changed) return prev;
  return Array.from(map.values()).sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
}

export function JobProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<PersistentJob[]>([]);
  const [activeCounts, setActiveCounts] = useState<ActiveJobCounts>({ running: 0, queued: 0 });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Jobs we follow until they finish (persisted so a reload keeps tracking them).
  const tracked = useRef<Set<string>>(new Set(loadActiveJobIds()));
  const polling = useRef(false);

  const track = (id: string, on: boolean) => {
    if (on) tracked.current.add(id);
    else tracked.current.delete(id);
    saveActiveJobIds(Array.from(tracked.current));
  };

  const refreshJobs = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [jobsRes, countsRes] = await Promise.all([
        api.listJobs({ limit: 50 }),
        api.getActiveJobCounts(),
      ]);
      setJobs(jobsRes.jobs);
      setActiveCounts(countsRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch jobs');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const cancelJob = useCallback(async (jobId: string) => {
    try {
      const updated = await api.cancelJob(jobId);
      setJobs(prev => mergeJobs(prev, [updated]));
      track(jobId, false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel job');
    }
  }, []);

  const retryJob = useCallback(async (jobId: string) => {
    try {
      const updated = await api.retryJob(jobId);
      setJobs(prev => mergeJobs(prev, [updated]));
      track(jobId, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to retry job');
    }
  }, []);

  const submitJob = useCallback(async (params: SubmitJobParams): Promise<PersistentJob> => {
    const job = await api.createJob(params);
    setJobs(prev => [job, ...prev]);
    track(job.id, true);
    setActiveCounts(prev => ({ ...prev, queued: prev.queued + 1 }));
    return job;
  }, []);

  const pollActiveJobs = useCallback(async () => {
    // Skip when nothing is tracked, the tab is hidden, or a poll is still in flight.
    if (tracked.current.size === 0 || document.hidden || polling.current) return;
    polling.current = true;
    try {
      const ids = Array.from(tracked.current);
      const results = await Promise.allSettled(ids.map(id => api.getJob(id)));
      const updates: PersistentJob[] = [];
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') {
          updates.push(r.value);
          if (TERMINAL.has(r.value.status)) track(ids[i], false);
        } else {
          track(ids[i], false); // deleted or unreachable — stop following
        }
      });
      if (updates.length) setJobs(prev => mergeJobs(prev, updates));
      const counts = await api.getActiveJobCounts().catch(() => null);
      if (counts) {
        setActiveCounts(prev => (prev.running === counts.running && prev.queued === counts.queued ? prev : counts));
      }
    } finally {
      polling.current = false;
    }
  }, []);

  useEffect(() => { refreshJobs(); }, [refreshJobs]);

  useEffect(() => {
    const interval = setInterval(pollActiveJobs, POLL_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) pollActiveJobs(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [pollActiveJobs]);

  const value = useMemo<JobContextValue>(() => ({
    jobs, activeCounts, isLoading, error, refreshJobs, submitJob, cancelJob, retryJob,
  }), [jobs, activeCounts, isLoading, error, refreshJobs, submitJob, cancelJob, retryJob]);

  return <JobContext.Provider value={value}>{children}</JobContext.Provider>;
}

function loadActiveJobIds(): string[] {
  try {
    const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveActiveJobIds(ids: string[]): void {
  try {
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Ignore storage errors
  }
}
