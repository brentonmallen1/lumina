import { useState, useEffect, useCallback } from 'react';
import { ArrowLeft, Rss, Plus, Trash2, RefreshCw, ChevronDown, ChevronUp, X, ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';
import * as api from '../api/client';
import type { Feed, FeedEntry } from '../types';
import './Feeds.css';

const STATUS_LABELS: Record<string, string> = {
  pending:     'Pending',
  downloading: 'Downloading',
  processing:  'Processing',
  done:        'Done',
  error:       'Error',
};

function formatDate(iso: string | null): string {
  if (!iso) return 'Never';
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export default function Feeds() {
  const [available,   setAvailable]   = useState(true);
  const [unavailMsg,  setUnavailMsg]  = useState('');
  const [feeds,       setFeeds]       = useState<Feed[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState('');
  const [expandedId,  setExpandedId]  = useState<string | null>(null);
  const [entries,     setEntries]     = useState<Record<string, FeedEntry[]>>({});
  const [addUrl,      setAddUrl]      = useState('');
  const [adding,      setAdding]      = useState(false);
  const [addError,    setAddError]    = useState('');
  const [checking,    setChecking]    = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [status, list] = await Promise.all([api.getFeedsStatus(), api.getFeeds()]);
      setAvailable(status.available);
      setUnavailMsg(status.reason);
      setFeeds(list);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleExpand = async (id: string) => {
    const open = expandedId === id;
    setExpandedId(open ? null : id);
    if (!open && !entries[id]) {
      try {
        const list = await api.getFeedEntries(id);
        setEntries(prev => ({ ...prev, [id]: list }));
      } catch { /* silently fail */ }
    }
  };

  const handleAdd = async () => {
    if (!addUrl.trim()) return;
    setAdding(true);
    setAddError('');
    try {
      const feed = await api.createFeed({ url: addUrl.trim() });
      setFeeds(prev => [feed, ...prev]);
      setAddUrl('');
    } catch (err) {
      setAddError((err as Error).message);
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteFeed(id);
      setFeeds(prev => prev.filter(f => f.id !== id));
      if (expandedId === id) setExpandedId(null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleCheck = async (id: string) => {
    setChecking(id);
    try {
      await api.checkFeedNow(id);
      // Refresh entries after a short delay
      setTimeout(async () => {
        try {
          const list = await api.getFeedEntries(id);
          setEntries(prev => ({ ...prev, [id]: list }));
        } catch { /* ignore */ }
        setChecking(null);
      }, 2000);
    } catch (err) {
      setError((err as Error).message);
      setChecking(null);
    }
  };

  return (
    <div className="feeds-page">
      <div className="feeds-inner">

        <Link to="/" className="feeds-back">
          <ArrowLeft size={15} aria-hidden="true" />
          All tools
        </Link>

        <div className="feeds-header">
          <div className="feeds-header-icon">
            <Rss size={20} aria-hidden="true" />
          </div>
          <div>
            <h1 className="feeds-title">RSS &amp; Podcast Monitor</h1>
            <p className="feeds-subtitle">Auto-transcribe and summarize new episodes</p>
          </div>
        </div>

        {!available && (
          <div className="feeds-unavail" role="alert">
            <strong>Feed monitoring unavailable:</strong> {unavailMsg}
            <br />
            <code>uv sync --extra feeds</code> to enable.
          </div>
        )}

        {error && (
          <div className="feeds-error" role="alert">
            {error}
            <button onClick={() => setError('')} aria-label="Dismiss"><X size={14} /></button>
          </div>
        )}

        {/* Add feed form */}
        {available && (
          <div className="feeds-add-wrap">
            <input
              type="url"
              className="feeds-add-input"
              placeholder="RSS or podcast feed URL…"
              value={addUrl}
              onChange={e => { setAddUrl(e.target.value); setAddError(''); }}
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
              aria-label="Feed URL"
            />
            <button
              className="feeds-btn feeds-btn--primary"
              onClick={handleAdd}
              disabled={adding || !addUrl.trim()}
            >
              <Plus size={15} aria-hidden="true" />
              {adding ? 'Adding…' : 'Add feed'}
            </button>
            {addError && <p className="feeds-add-error">{addError}</p>}
          </div>
        )}

        {loading && <p className="feeds-empty">Loading…</p>}

        {!loading && feeds.length === 0 && (
          <div className="feeds-empty-state">
            <Rss size={36} className="feeds-empty-icon" aria-hidden="true" />
            <p className="feeds-empty-title">No feeds yet</p>
            <p className="feeds-empty-desc">Add an RSS or podcast feed URL above to start monitoring.</p>
          </div>
        )}

        {!loading && feeds.length > 0 && (
          <ul className="feeds-list">
            {feeds.map(feed => {
              const isOpen = expandedId === feed.id;
              const feedEntries = entries[feed.id] || [];
              return (
                <li key={feed.id} className={`feeds-item${isOpen ? ' open' : ''}`}>
                  <div className="feeds-item-row">
                    <div className="feeds-item-info" onClick={() => handleExpand(feed.id)} role="button" tabIndex={0}
                      onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && handleExpand(feed.id)}>
                      <span className="feeds-item-title">{feed.title || feed.url}</span>
                      {feed.title && <span className="feeds-item-url">{feed.url}</span>}
                      <span className="feeds-item-meta">
                        Last checked: {formatDate(feed.last_checked)}
                      </span>
                    </div>
                    <div className="feeds-item-actions">
                      <button
                        className="feeds-icon-btn"
                        onClick={() => handleCheck(feed.id)}
                        disabled={checking === feed.id}
                        title="Check for new episodes"
                        aria-label="Refresh feed"
                      >
                        <RefreshCw size={13} className={checking === feed.id ? 'spinning' : ''} />
                      </button>
                      <button
                        className="feeds-icon-btn feeds-icon-btn--danger"
                        onClick={() => handleDelete(feed.id)}
                        title="Remove feed"
                        aria-label="Remove feed"
                      >
                        <Trash2 size={13} />
                      </button>
                      <span className="feeds-item-chevron" aria-hidden="true">
                        {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </span>
                    </div>
                  </div>

                  {isOpen && (
                    <div className="feeds-item-body">
                      {feedEntries.length === 0 ? (
                        <p className="feeds-entries-empty">No entries found yet.</p>
                      ) : (
                        <ul className="feeds-entries-list">
                          {feedEntries.map(entry => (
                            <li key={entry.id} className="feeds-entry-item">
                              <div className="feeds-entry-info">
                                <span className="feeds-entry-title">{entry.title}</span>
                                <span className="feeds-entry-meta">
                                  {formatDate(entry.published)}
                                </span>
                              </div>
                              <div className="feeds-entry-right">
                                <span className={`feeds-entry-status feeds-entry-status--${entry.status}`}>
                                  {STATUS_LABELS[entry.status] ?? entry.status}
                                </span>
                                {entry.audio_url && (
                                  <a
                                    href={entry.audio_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="feeds-icon-btn"
                                    title="Open audio URL"
                                    aria-label="Open audio source"
                                  >
                                    <ExternalLink size={12} />
                                  </a>
                                )}
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

      </div>
    </div>
  );
}
