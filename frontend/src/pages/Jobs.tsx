import { useState, useEffect, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft, ListTodo, RefreshCw, Loader, AlertTriangle,
  Inbox, ChevronDown, ChevronRight, RotateCcw,
} from 'lucide-react';
import { useJobs } from '../context/JobContext';
import type { PersistentJob, PersistentJobStatus, PersistentJobType } from '../types';
import * as api from '../api/client';
import './Jobs.css';

const STATUS_LABELS: Record<PersistentJobStatus, string> = {
  pending: 'Pending',
  queued: 'Queued',
  running: 'Running',
  done: 'Done',
  error: 'Error',
  cancelled: 'Cancelled',
};

const TYPE_LABELS: Record<PersistentJobType, string> = {
  transcribe: 'Transcribe',
  enhance: 'Enhance',
  extract: 'Extract',
  summarize: 'Summarize',
  download: 'Download',
};

const TYPE_ICONS: Record<PersistentJobType, string> = {
  transcribe: '🎙️',
  enhance: '✨',
  extract: '📄',
  summarize: '📝',
  download: '📥',
};

export default function Jobs() {
  const { jobs, activeCounts, refreshJobs, cancelJob, retryJob, isLoading, error } = useJobs();
  const [searchParams, setSearchParams] = useSearchParams();
  const [expandedJob, setExpandedJob] = useState<string | null>(null);
  const [filter, setFilter] = useState<{
    status: string | null;
    type: string | null;
  }>({ status: null, type: null });
  const [batchInput, setBatchInput] = useState('');
  const [batchJobType, setBatchJobType] = useState<string>('summarize');
  const [batchLoading, setBatchLoading] = useState(false);

  const selectedJobId = searchParams.get('id');

  useEffect(() => {
    refreshJobs();
  }, [refreshJobs]);

  useEffect(() => {
    if (selectedJobId) {
      setExpandedJob(selectedJobId);
    }
  }, [selectedJobId]);

  const filteredJobs = jobs.filter(job => {
    if (filter.status && job.status !== filter.status) return false;
    if (filter.type && job.type !== filter.type) return false;
    return true;
  });

  const handleJobClick = useCallback((job: PersistentJob) => {
    if (expandedJob === job.id) {
      setExpandedJob(null);
      setSearchParams({});
    } else {
      setExpandedJob(job.id);
      setSearchParams({ id: job.id });
    }
  }, [expandedJob, setSearchParams]);

  const handleCancel = useCallback(async (e: React.MouseEvent, jobId: string) => {
    e.stopPropagation();
    await cancelJob(jobId);
  }, [cancelJob]);

  const handleRetry = useCallback(async (e: React.MouseEvent, jobId: string) => {
    e.stopPropagation();
    await retryJob(jobId);
  }, [retryJob]);

  const handleBatchSubmit = useCallback(async () => {
    const urls = batchInput
      .split('\n')
      .map(line => line.trim())
      .filter(line => line.length > 0 && (line.startsWith('http://') || line.startsWith('https://')));

    if (urls.length === 0) return;

    setBatchLoading(true);
    try {
      await api.createBatchJobs({ urls, job_type: batchJobType });
      setBatchInput('');
      await refreshJobs();
    } catch (err) {
      console.error('Batch submit failed:', err);
    } finally {
      setBatchLoading(false);
    }
  }, [batchInput, batchJobType, refreshJobs]);

  const formatTime = (iso: string) => {
    const date = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - date.getTime();

    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="jobs-page">
      <div className="jobs-inner">
        <Link to="/" className="jobs-back">
          <ArrowLeft size={15} aria-hidden="true" />
          All tools
        </Link>

        <header className="jobs-header">
          <div className="jobs-header-icon">
            <ListTodo size={20} aria-hidden="true" />
          </div>
          <div className="jobs-header-content">
            <h1 className="jobs-title">Jobs</h1>
            <p className="jobs-subtitle">Track and manage processing tasks</p>
            {(activeCounts.running > 0 || activeCounts.queued > 0) && (
              <div className="jobs-counts">
                {activeCounts.running > 0 && (
                  <span className="jobs-count-badge running">{activeCounts.running} running</span>
                )}
                {activeCounts.queued > 0 && (
                  <span className="jobs-count-badge queued">{activeCounts.queued} queued</span>
                )}
              </div>
            )}
          </div>
        </header>

        <div className="jobs-filters">
          <select
            className="jobs-filter-select"
            value={filter.status || ''}
            onChange={e => setFilter(f => ({ ...f, status: e.target.value || null }))}
          >
            <option value="">All statuses</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select
            className="jobs-filter-select"
            value={filter.type || ''}
            onChange={e => setFilter(f => ({ ...f, type: e.target.value || null }))}
          >
            <option value="">All types</option>
            {Object.entries(TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <button className="jobs-refresh-btn" onClick={() => refreshJobs()} disabled={isLoading}>
            <RefreshCw size={14} aria-hidden="true" />
            {isLoading ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        <div className="jobs-batch">
          <div className="jobs-batch-header">
            <Inbox size={16} aria-hidden="true" />
            Batch Submit
          </div>
          <textarea
            className="jobs-batch-textarea"
            placeholder="Paste URLs here (one per line)..."
            value={batchInput}
            onChange={e => setBatchInput(e.target.value)}
            rows={3}
          />
          <div className="jobs-batch-actions">
            <div className="jobs-batch-type">
              <label htmlFor="batch-job-type">Job type:</label>
              <select
                id="batch-job-type"
                className="jobs-filter-select"
                value={batchJobType}
                onChange={e => setBatchJobType(e.target.value)}
              >
                <option value="summarize">Summarize</option>
                <option value="extract">Extract text only</option>
                <option value="download">Download (YouTube)</option>
              </select>
            </div>
            <button
              className="jobs-batch-submit"
              onClick={handleBatchSubmit}
              disabled={batchLoading || !batchInput.trim()}
            >
              {batchLoading ? (
                <>
                  <Loader size={14} className="job-status-spinner" aria-hidden="true" />
                  Submitting...
                </>
              ) : (
                'Submit Batch'
              )}
            </button>
          </div>
        </div>

        {error && (
          <div className="jobs-error">
            <AlertTriangle size={16} aria-hidden="true" />
            {error}
          </div>
        )}

        <div className="jobs-list">
          {filteredJobs.length === 0 ? (
            <div className="jobs-empty">
              <Inbox size={40} className="jobs-empty-icon" aria-hidden="true" />
              <p>No jobs found</p>
            </div>
          ) : (
            filteredJobs.map(job => (
              <JobCard
                key={job.id}
                job={job}
                expanded={expandedJob === job.id}
                onClick={() => handleJobClick(job)}
                onCancel={e => handleCancel(e, job.id)}
                onRetry={e => handleRetry(e, job.id)}
                formatTime={formatTime}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

interface JobCardProps {
  job: PersistentJob;
  expanded: boolean;
  onClick: () => void;
  onCancel: (e: React.MouseEvent) => void;
  onRetry: (e: React.MouseEvent) => void;
  formatTime: (iso: string) => string;
}

function JobCard({ job, expanded, onClick, onCancel, onRetry, formatTime }: JobCardProps) {
  const isActive = ['pending', 'queued', 'running'].includes(job.status);
  const canCancel = isActive;
  const canRetry = job.status === 'error' || job.status === 'cancelled';
  const typeIcon = TYPE_ICONS[job.type] || '📋';

  return (
    <div className="job-card">
      <div className="job-card-header" onClick={onClick}>
        {job.thumbnail ? (
          <img
            className="job-thumbnail"
            src={`data:image/webp;base64,${job.thumbnail}`}
            alt=""
          />
        ) : (
          <div className="job-thumbnail-placeholder">{typeIcon}</div>
        )}
        <div className="job-info">
          <h3 className="job-title">
            {job.source_title || job.source_ref || job.input_file || `Job ${job.id.slice(0, 8)}`}
          </h3>
          <div className="job-meta">
            <span className={`job-status ${job.status}`}>
              {job.status === 'running' && (
                <Loader size={12} className="job-status-spinner" aria-hidden="true" />
              )}
              {STATUS_LABELS[job.status]}
            </span>
            <span className="job-meta-separator">·</span>
            <span>{TYPE_LABELS[job.type]}</span>
            <span className="job-meta-separator">·</span>
            <span>{formatTime(job.created_at)}</span>
            {job.status_detail && (
              <>
                <span className="job-meta-separator">·</span>
                <span>{job.status_detail}</span>
              </>
            )}
          </div>
        </div>
        <div className="job-actions">
          {canRetry && (
            <button className="job-retry-btn" onClick={onRetry}>
              <RotateCcw size={14} aria-hidden="true" />
              Retry
            </button>
          )}
          {canCancel && (
            <button className="job-cancel-btn" onClick={onCancel}>
              Cancel
            </button>
          )}
          {expanded ? (
            <ChevronDown size={18} aria-hidden="true" />
          ) : (
            <ChevronRight size={18} aria-hidden="true" />
          )}
        </div>
      </div>

      {expanded && (
        <div className="job-expanded">
          {job.error && (
            <div className="job-error-msg">
              <AlertTriangle size={16} aria-hidden="true" />
              <span>{job.error}</span>
            </div>
          )}
          {job.result && (
            <>
              <div className="job-detail-label">Result</div>
              <div className="job-result">{job.result}</div>
            </>
          )}
          {!job.error && !job.result && (
            <p className="job-pending-msg">
              {job.status === 'running' ? 'Processing...' : 'No result yet'}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
