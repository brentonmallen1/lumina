import { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from 'react';
import type { PersistentJob, ActiveJobCounts } from '../types';
import * as api from '../api/client';

const POLL_INTERVAL_MS = 2000;
const LOCAL_STORAGE_KEY = 'lumina_active_jobs';

interface SubmitJobParams {
  job_type: string;
  source_type: string;
  source_ref: string;
  source_title?: string;
  config?: Record<string, unknown>;
}

interface JobContextValue {
  jobs: PersistentJob[];
  activeJob: PersistentJob | null;
  activeCounts: ActiveJobCounts;
  isLoading: boolean;
  error: string | null;
  setActiveJob: (job: PersistentJob | null) => void;
  refreshJobs: () => Promise<void>;
  submitJob: (params: SubmitJobParams) => Promise<PersistentJob>;
  cancelJob: (jobId: string) => Promise<void>;
  retryJob: (jobId: string) => Promise<void>;
  pollJob: (jobId: string) => void;
  stopPolling: (jobId: string) => void;
}

const JobContext = createContext<JobContextValue | null>(null);

export function useJobs(): JobContextValue {
  const ctx = useContext(JobContext);
  if (!ctx) throw new Error('useJobs must be used within JobProvider');
  return ctx;
}

interface JobProviderProps {
  children: ReactNode;
}

export function JobProvider({ children }: JobProviderProps) {
  const [jobs, setJobs] = useState<PersistentJob[]>([]);
  const [activeJob, setActiveJob] = useState<PersistentJob | null>(null);
  const [activeCounts, setActiveCounts] = useState<ActiveJobCounts>({ running: 0, queued: 0 });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pollingJobs = useRef<Set<string>>(new Set());
  const pollInterval = useRef<ReturnType<typeof setInterval> | null>(null);

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

  const cancelJobAction = useCallback(async (jobId: string) => {
    try {
      const updated = await api.cancelJob(jobId);
      setJobs(prev => prev.map(j => j.id === jobId ? updated : j));
      if (activeJob?.id === jobId) {
        setActiveJob(updated);
      }
      pollingJobs.current.delete(jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel job');
    }
  }, [activeJob]);

  const retryJobAction = useCallback(async (jobId: string) => {
    try {
      const updated = await api.retryJob(jobId);
      setJobs(prev => prev.map(j => j.id === jobId ? updated : j));
      if (activeJob?.id === jobId) {
        setActiveJob(updated);
      }
      pollingJobs.current.add(jobId);
      saveActiveJobIds(Array.from(pollingJobs.current));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to retry job');
    }
  }, [activeJob]);

  const pollJob = useCallback((jobId: string) => {
    pollingJobs.current.add(jobId);
    saveActiveJobIds(Array.from(pollingJobs.current));
  }, []);

  const stopPolling = useCallback((jobId: string) => {
    pollingJobs.current.delete(jobId);
    saveActiveJobIds(Array.from(pollingJobs.current));
  }, []);

  const submitJob = useCallback(async (params: SubmitJobParams): Promise<PersistentJob> => {
    const job = await api.createJob(params);
    setJobs(prev => [job, ...prev]);
    pollingJobs.current.add(job.id);
    saveActiveJobIds(Array.from(pollingJobs.current));
    setActiveCounts(prev => ({ ...prev, running: prev.running + 1 }));
    return job;
  }, []);

  const pollActiveJobs = useCallback(async () => {
    if (pollingJobs.current.size === 0) return;

    const jobIds = Array.from(pollingJobs.current);
    const updates: PersistentJob[] = [];
    const completed: string[] = [];

    for (const jobId of jobIds) {
      try {
        const job = await api.getJob(jobId);
        updates.push(job);
        if (['done', 'error', 'cancelled'].includes(job.status)) {
          completed.push(jobId);
        }
      } catch {
        completed.push(jobId);
      }
    }

    if (updates.length > 0) {
      setJobs(prev => {
        const map = new Map(prev.map(j => [j.id, j]));
        for (const job of updates) {
          map.set(job.id, job);
        }
        return Array.from(map.values()).sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        );
      });

      if (activeJob && updates.find(j => j.id === activeJob.id)) {
        const updated = updates.find(j => j.id === activeJob.id);
        if (updated) setActiveJob(updated);
      }
    }

    for (const jobId of completed) {
      pollingJobs.current.delete(jobId);
    }
    saveActiveJobIds(Array.from(pollingJobs.current));

    const counts = await api.getActiveJobCounts().catch(() => ({ running: 0, queued: 0 }));
    setActiveCounts(counts);
  }, [activeJob]);

  useEffect(() => {
    const savedIds = loadActiveJobIds();
    if (savedIds.length > 0) {
      for (const id of savedIds) {
        pollingJobs.current.add(id);
      }
    }
    refreshJobs();
  }, [refreshJobs]);

  useEffect(() => {
    pollInterval.current = setInterval(pollActiveJobs, POLL_INTERVAL_MS);
    return () => {
      if (pollInterval.current) {
        clearInterval(pollInterval.current);
      }
    };
  }, [pollActiveJobs]);

  const value: JobContextValue = {
    jobs,
    activeJob,
    activeCounts,
    isLoading,
    error,
    setActiveJob,
    refreshJobs,
    submitJob,
    cancelJob: cancelJobAction,
    retryJob: retryJobAction,
    pollJob,
    stopPolling,
  };

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
