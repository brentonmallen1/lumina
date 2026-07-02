import { useEffect, useState, useRef } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { Clock, Settings, Zap, Sun, Moon, Loader, ListTodo, ExternalLink, X, AlertTriangle } from 'lucide-react';
import { useTheme } from '../hooks/useTheme';
import { useJobs } from '../context/JobContext';
import type { PersistentJob } from '../types';
import * as api from '../api/client';
import './Layout.css';

function formatContextSize(size: number): string {
  if (size >= 1000) return `${Math.round(size / 1000)}k`;
  return String(size);
}

export default function Layout() {
  const location = useLocation();
  const isSettings = location.pathname === '/settings';
  const isHistory  = location.pathname === '/history';
  const isJobs     = location.pathname === '/jobs';
  const { isDark, toggle } = useTheme();
  const { activeCounts, jobs } = useJobs();
  const [model, setModel] = useState<string | null>(null);
  const [contextSize, setContextSize] = useState<number | null>(null);
  const [jobsPopoverOpen, setJobsPopoverOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  const hasActiveJobs = activeCounts.running > 0 || activeCounts.queued > 0;

  // Get active jobs and recent completed jobs for popover
  const activeJobs = jobs.filter(j => ['running', 'queued', 'pending'].includes(j.status));
  const recentCompletedJobs = jobs
    .filter(j => j.status === 'done')
    .slice(0, 3);
  const recentErrorJobs = jobs
    .filter(j => j.status === 'error')
    .slice(0, 2);

  // Close popover on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setJobsPopoverOpen(false);
      }
    };
    if (jobsPopoverOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [jobsPopoverOpen]);

  // Close popover when navigating
  useEffect(() => {
    setJobsPopoverOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    api.getSettings().then(s => {
      if (s.ollama_model) {
        setModel(s.ollama_model);
        fetchContextSize(s.ollama_context_size);
      }
    }).catch(() => {});

    const handleSettingsChanged = (e: Event) => {
      const settings = (e as CustomEvent).detail;
      if (settings?.ollama_model) {
        setModel(settings.ollama_model);
        fetchContextSize(settings.ollama_context_size);
      }
    };
    window.addEventListener('settings-changed', handleSettingsChanged);
    return () => window.removeEventListener('settings-changed', handleSettingsChanged);
  }, []);

  const fetchContextSize = (configuredSize?: string) => {
    if (configuredSize) {
      setContextSize(parseInt(configuredSize, 10));
    }
  };

  return (
    <div className="layout">
      <a href="#main-content" className="skip-link">Skip to main content</a>

      <header className="layout-header">
        <div className="layout-brand-group">
          <Link to="/" className="layout-brand">
            <Zap size={20} className="layout-brand-icon" aria-hidden="true" />
            <span className="layout-brand-name">Lumina</span>
          </Link>
          {model && (
            <Link
              to="/settings#ollama"
              className="layout-model"
              title={`LLM: ${model}${contextSize ? ` (${formatContextSize(contextSize)} context)` : ''} — Click to configure`}
            >
              {model}
              {contextSize && <span className="layout-model-ctx">{formatContextSize(contextSize)}</span>}
            </Link>
          )}
        </div>

        <nav className="layout-nav" aria-label="Global navigation">
          <div className="layout-jobs-wrapper" ref={popoverRef}>
            <button
              className={`layout-nav-btn ${hasActiveJobs ? 'layout-jobs-indicator' : ''} ${isJobs ? 'active' : ''}`}
              onClick={() => setJobsPopoverOpen(v => !v)}
              aria-label={hasActiveJobs ? `${activeCounts.running} running, ${activeCounts.queued} queued jobs` : 'Jobs'}
              aria-expanded={jobsPopoverOpen}
            >
              {hasActiveJobs ? (
                <>
                  <Loader size={18} className="layout-jobs-spinner" aria-hidden="true" />
                  <span className="layout-jobs-count">
                    {activeCounts.running > 0 && `${activeCounts.running} running`}
                    {activeCounts.running > 0 && activeCounts.queued > 0 && ' · '}
                    {activeCounts.queued > 0 && `${activeCounts.queued} queued`}
                  </span>
                </>
              ) : (
                <>
                  <ListTodo size={18} aria-hidden="true" />
                  <span className="layout-nav-label">Jobs</span>
                </>
              )}
            </button>

            {jobsPopoverOpen && (
              <div className="layout-jobs-popover">
                <div className="layout-jobs-popover-header">
                  <span>Jobs</span>
                  <button
                    className="layout-jobs-popover-close"
                    onClick={() => setJobsPopoverOpen(false)}
                    aria-label="Close"
                  >
                    <X size={14} />
                  </button>
                </div>

                {activeJobs.length === 0 && recentCompletedJobs.length === 0 && recentErrorJobs.length === 0 ? (
                  <div className="layout-jobs-popover-empty">No recent jobs</div>
                ) : (
                  <div className="layout-jobs-popover-list">
                    {activeJobs.map(job => (
                      <JobPopoverItem key={job.id} job={job} />
                    ))}
                    {recentErrorJobs.map(job => (
                      <JobPopoverItem key={job.id} job={job} />
                    ))}
                    {recentCompletedJobs.map(job => (
                      <JobPopoverItem key={job.id} job={job} />
                    ))}
                  </div>
                )}

                <Link
                  to="/jobs"
                  className="layout-jobs-popover-footer"
                  onClick={() => setJobsPopoverOpen(false)}
                >
                  View all jobs
                </Link>
              </div>
            )}
          </div>
          <button
            className="layout-nav-btn"
            onClick={toggle}
            aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {isDark ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
            <span className="layout-nav-label">{isDark ? 'Light' : 'Dark'}</span>
          </button>
          <Link
            to="/history"
            className={`layout-nav-btn ${isHistory ? 'active' : ''}`}
            aria-label="History"
          >
            <Clock size={18} aria-hidden="true" />
            <span className="layout-nav-label">History</span>
          </Link>
          <Link
            to="/settings"
            className={`layout-nav-btn ${isSettings ? 'active' : ''}`}
            aria-label="Settings"
          >
            <Settings size={18} aria-hidden="true" />
            <span className="layout-nav-label">Settings</span>
          </Link>
        </nav>
      </header>

      <main id="main-content" className="layout-main">
        <Outlet />
      </main>
    </div>
  );
}

function JobPopoverItem({ job }: { job: PersistentJob }) {
  const title = job.source_title || job.source_ref || job.input_file || `Job ${job.id.slice(0, 8)}`;
  const isActive = ['running', 'queued', 'pending'].includes(job.status);
  const canOpen = job.status === 'done' && (job.type === 'summarize' || job.type === 'extract');

  return (
    <div className={`layout-jobs-popover-item ${job.status}`}>
      <div className="layout-jobs-popover-item-content">
        <span className="layout-jobs-popover-item-title" title={title}>
          {title}
        </span>
        <span className={`layout-jobs-popover-item-status ${job.status}`}>
          {isActive && <Loader size={10} className="layout-jobs-spinner" />}
          {job.status === 'error' && <AlertTriangle size={10} />}
          {job.status_detail || job.status}
        </span>
      </div>
      {canOpen && (
        <Link
          to={`/summarize?jobId=${job.id}`}
          className="layout-jobs-popover-item-action"
          title="Open in Summarize"
        >
          <ExternalLink size={12} />
        </Link>
      )}
    </div>
  );
}
