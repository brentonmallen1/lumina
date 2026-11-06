import { useState, useEffect, useCallback, useRef } from 'react';
import { ArrowLeft, Clock, Trash2, X, ChevronDown, ChevronUp, Sparkles, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import * as api from '../api/client';
import type { HistoryEntry } from '../types';
import ResultView from '../components/results/ResultView';
import RecipeTools, { type RecipeFormat } from '../components/results/RecipeTools';
import '../components/results/renderers';
import { BUILTIN_OUTPUT_TYPES } from '../components/results/registry';
import './Summarize.css'; // shared result action buttons
import './History.css';

const MODE_LABELS: Record<string, string> = {
  summary:         'Summary',
  tldr:            'TL;DR',
  key_points:      'Key Points',
  mind_map:        'Mind Map',
  action_items:    'Action Items',
  q_and_a:         'Q&A',
  meeting_minutes: 'Meeting Minutes',
  extract_list:    'Extract List',
  recipe:          'Recipe',
  recipe_jsonld:   'Recipe (JSON-LD)',
  mtg_precon:      'MTG Precon Upgrade',
};

const SOURCE_LABELS: Record<string, string> = {
  text:    'Text',
  audio:   'Audio',
  youtube: 'YouTube',
  url:     'URL',
  pdf:     'PDF',
  image:   'Image',
};

/** A saved recipe with a Markdown / JSON-LD switch and Send to Mealie. */
function HistoryRecipe({ entry, mealieReady }: { entry: HistoryEntry; mealieReady: boolean }) {
  const initial: RecipeFormat = entry.mode === 'recipe_jsonld' ? 'jsonld' : 'markdown';
  const [format, setFormat] = useState<RecipeFormat>(initial);
  const [texts, setTexts] = useState<Partial<Record<RecipeFormat, string>>>({ [initial]: entry.result });
  const text = texts[format] ?? entry.result;
  const sourceUrl = /^https?:\/\//.test(entry.source_detail) ? entry.source_detail : undefined;

  return (
    <>
      <div className="summarize-result-actions history-recipe-actions">
        <RecipeTools
          format={format}
          text={text}
          cached={texts}
          onConvert={(f, t) => { setTexts(prev => ({ ...prev, [f]: t })); setFormat(f); }}
          sourceUrl={sourceUrl}
          mealieReady={mealieReady}
        />
      </div>
      {format === 'jsonld' ? (
        <ResultView text={text} outputType="json:recipe" rendered />
      ) : (
        <div className="history-result-text"><ReactMarkdown>{text}</ReactMarkdown></div>
      )}
    </>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso + 'Z'); // treat as UTC
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
}

function truncate(text: string, max = 120): string {
  return text.length <= max ? text : text.slice(0, max).trimEnd() + '…';
}

type SearchResult = HistoryEntry & { snippet?: string };

export default function History() {
  const [entries,      setEntries]      = useState<HistoryEntry[]>([]);
  const [mealieReady,  setMealieReady]  = useState(false);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState('');
  const [expandedId,   setExpandedId]   = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [searchQuery,  setSearchQuery]  = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching,    setSearching]    = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setEntries(await api.getHistory());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Recipe entries offer "Send to Mealie" once it's set up in Settings → Integrations.
  useEffect(() => {
    api.getSettings().then(st => setMealieReady(Boolean(st.mealie_url && st.mealie_api_token))).catch(() => {});
  }, []);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = searchQuery.trim();
    if (!trimmed) {
      setSearchResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const results = await api.searchHistory(trimmed);
        setSearchResults(results);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [searchQuery]);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await api.deleteHistoryEntry(id);
      setEntries(prev => prev.filter(entry => entry.id !== id));
      setSearchResults(prev => prev.filter(entry => entry.id !== id));
      if (expandedId === id) setExpandedId(null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleClear = async () => {
    try {
      await api.clearHistory();
      setEntries([]);
      setSearchResults([]);
      setExpandedId(null);
      setConfirmClear(false);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const isSearching = searchQuery.trim().length > 0;
  const displayEntries: SearchResult[] = isSearching ? searchResults : entries;

  const renderEntry = (entry: SearchResult) => {
    const isOpen = expandedId === entry.id;
    return (
      <li key={entry.id} className={`history-item${isOpen ? ' open' : ''}`}>
        <div
          className="history-item-row"
          onClick={() => setExpandedId(isOpen ? null : entry.id)}
          role="button"
          tabIndex={0}
          onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setExpandedId(isOpen ? null : entry.id)}
          aria-expanded={isOpen}
          aria-label={`${MODE_LABELS[entry.mode] ?? entry.mode} result from ${formatDate(entry.created_at)} — ${isOpen ? 'collapse' : 'expand'}`}
        >
          <div className="history-item-meta">
            <span className="history-item-mode">
              {MODE_LABELS[entry.mode] ?? entry.mode}
            </span>
            <span className="history-item-source">
              {SOURCE_LABELS[entry.source] ?? entry.source}
            </span>
            {entry.source_detail && (
              <span className="history-item-source-detail" title={entry.source_detail}>
                {entry.source_detail.length > 60
                  ? entry.source_detail.slice(0, 57) + '…'
                  : entry.source_detail}
              </span>
            )}
            <span className="history-item-date">{formatDate(entry.created_at)}</span>
          </div>
          {isSearching && entry.snippet ? (
            <p
              className="history-item-preview history-item-snippet"
              dangerouslySetInnerHTML={{ __html: entry.snippet }}
            />
          ) : (
            <p className="history-item-preview">{truncate(entry.result)}</p>
          )}
          <div className="history-item-actions">
            <button
              className="history-icon-btn history-icon-btn--danger"
              onClick={e => handleDelete(e, entry.id)}
              aria-label="Delete entry"
              title="Delete"
            >
              <Trash2 size={13} />
            </button>
            <span className="history-item-chevron" aria-hidden="true">
              {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </span>
          </div>
        </div>

        {isOpen && (
          <div className="history-item-body">
            {entry.mode === 'recipe' || entry.mode === 'recipe_jsonld' ? (
              <HistoryRecipe entry={entry} mealieReady={mealieReady} />
            ) : BUILTIN_OUTPUT_TYPES[entry.mode] ? (
              <ResultView
                text={entry.result}
                outputType={BUILTIN_OUTPUT_TYPES[entry.mode]}
                rendered
                sourceUrl={entry.source === 'youtube' ? entry.source_detail : undefined}
              />
            ) : (
              <div className="history-result-text">
                <ReactMarkdown>{entry.result}</ReactMarkdown>
              </div>
            )}
            {entry.reasoning && (
              <details className="history-reasoning">
                <summary className="history-reasoning-summary">
                  Reasoning
                  <span className="history-reasoning-lines">
                    {entry.reasoning.split('\n').filter(Boolean).length} lines
                  </span>
                </summary>
                <pre className="history-reasoning-body">{entry.reasoning}</pre>
              </details>
            )}
          </div>
        )}
      </li>
    );
  };

  return (
    <div className="history-page">
      <div className="history-inner">

        <Link to="/" className="history-back">
          <ArrowLeft size={15} aria-hidden="true" />
          All tools
        </Link>

        <div className="history-header">
          <div className="history-header-icon">
            <Clock size={20} aria-hidden="true" />
          </div>
          <div>
            <h1 className="history-title">History</h1>
            <p className="history-subtitle">Past summarization results</p>
          </div>
        </div>

        {/* Search bar */}
        <div className="history-search-wrap">
          <Search size={15} className="history-search-icon" aria-hidden="true" />
          <input
            type="search"
            className="history-search"
            placeholder="Search results…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            aria-label="Search history"
          />
          {searchQuery && (
            <button
              className="history-search-clear"
              onClick={() => setSearchQuery('')}
              aria-label="Clear search"
            >
              <X size={13} />
            </button>
          )}
        </div>

        {error && (
          <div className="history-error" role="alert">
            {error}
            <button onClick={() => setError('')} aria-label="Dismiss"><X size={14} /></button>
          </div>
        )}

        {!loading && !isSearching && entries.length > 0 && (
          <div className="history-toolbar">
            {!confirmClear ? (
              <button className="history-btn history-btn--ghost" onClick={() => setConfirmClear(true)}>
                <Trash2 size={14} aria-hidden="true" />
                Clear all
              </button>
            ) : (
              <div className="history-confirm">
                <span>Delete all {entries.length} entries?</span>
                <button className="history-btn history-btn--danger" onClick={handleClear}>Yes, clear</button>
                <button className="history-btn history-btn--ghost" onClick={() => setConfirmClear(false)}>Cancel</button>
              </div>
            )}
          </div>
        )}

        {loading && <p className="history-empty">Loading…</p>}

        {!loading && searching && (
          <p className="history-empty">Searching…</p>
        )}

        {!loading && !searching && isSearching && displayEntries.length === 0 && (
          <div className="history-empty-state">
            <Search size={36} className="history-empty-icon" aria-hidden="true" />
            <p className="history-empty-title">No results found</p>
            <p className="history-empty-desc">No history entries match "{searchQuery}".</p>
          </div>
        )}

        {!loading && !isSearching && entries.length === 0 && (
          <div className="history-empty-state">
            <Clock size={36} className="history-empty-icon" aria-hidden="true" />
            <p className="history-empty-title">No history yet</p>
            <p className="history-empty-desc">Summarization results will appear here automatically after each run.</p>
            <Link to="/summarize" className="history-empty-cta">
              <Sparkles size={14} aria-hidden="true" />
              Start summarizing
            </Link>
          </div>
        )}

        {!loading && !searching && displayEntries.length > 0 && (
          <>
            {isSearching && (
              <p className="history-search-count">
                {displayEntries.length} result{displayEntries.length !== 1 ? 's' : ''}
              </p>
            )}
            <ul className="history-list">
              {displayEntries.map(renderEntry)}
            </ul>
          </>
        )}

      </div>
    </div>
  );
}
