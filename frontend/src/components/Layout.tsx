import { useEffect, useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { Clock, Settings, Zap, Sun, Moon, Loader, ListTodo } from 'lucide-react';
import { useTheme } from '../hooks/useTheme';
import { useJobs } from '../context/JobContext';
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
  const { activeCounts } = useJobs();
  const [model, setModel] = useState<string | null>(null);
  const [contextSize, setContextSize] = useState<number | null>(null);

  const hasActiveJobs = activeCounts.running > 0 || activeCounts.queued > 0;

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
            <span className="layout-model" title={`LLM: ${model}${contextSize ? ` (${formatContextSize(contextSize)} context)` : ''}`}>
              {model}
              {contextSize && <span className="layout-model-ctx">{formatContextSize(contextSize)}</span>}
            </span>
          )}
        </div>

        <nav className="layout-nav" aria-label="Global navigation">
          <Link
            to="/jobs"
            className={`layout-nav-btn ${hasActiveJobs ? 'layout-jobs-indicator' : ''} ${isJobs ? 'active' : ''}`}
            aria-label={hasActiveJobs ? `${activeCounts.running} running, ${activeCounts.queued} queued jobs` : 'Jobs'}
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
          </Link>
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
