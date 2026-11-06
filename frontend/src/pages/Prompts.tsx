import { useState, useEffect, useCallback } from 'react';
import { ArrowLeft, Plus, Edit2, Trash2, RotateCcw, Save, X, BookOpen } from 'lucide-react';
import { Link } from 'react-router-dom';
import * as api from '../api/client';
import type { Prompt } from '../types';
import './Prompts.css';

// Mode selector options come from the built-in prompts (GET /api/prompts);
// NEW_MODE lets the user name a brand-new mode slug.
const NEW_MODE = '__new__';

/** "My Mode!" → "my_mode" */
const toSlug = (s: string) => s.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

// ── Editor form state ──────────────────────────────────────────────────────

interface FormState {
  name:          string;
  mode:          string;
  system_prompt: string;
  template:      string;
}

const EMPTY_FORM: FormState = {
  name:          '',
  mode:          'summary',
  system_prompt: '',
  template:      '',
};

// ── Component ──────────────────────────────────────────────────────────────

export default function Prompts() {
  const [prompts, setPrompts]     = useState<Prompt[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error,   setError]       = useState('');

  // Editor state
  const [editing,   setEditing]   = useState<Prompt | null>(null);   // null = new
  const [showForm,  setShowForm]  = useState(false);
  const [form,      setForm]      = useState<FormState>(EMPTY_FORM);
  const [saving,    setSaving]    = useState(false);
  const [formError, setFormError] = useState('');
  const [newModeSlug, setNewModeSlug] = useState('');

  // Reset confirm
  const [confirmReset, setConfirmReset] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPrompts(await api.getPrompts());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Form helpers ───────────────────────────────────────────────────────────

  const openNew = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setNewModeSlug('');
    setFormError('');
    setShowForm(true);
  };

  const openEdit = (p: Prompt) => {
    setEditing(p);
    setForm({
      name:          p.name,
      mode:          p.mode,
      system_prompt: p.system_prompt,
      template:      p.template,
    });
    setFormError('');
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
    setFormError('');
  };

  const setField = (key: keyof FormState, value: string) =>
    setForm(f => ({ ...f, [key]: value }));

  const handleSave = async () => {
    if (!form.name.trim())     { setFormError('Name is required.'); return; }
    const mode = form.mode === NEW_MODE ? toSlug(newModeSlug || form.name) : form.mode;
    if (!mode) { setFormError('Give the new mode a name.'); return; }
    if (!form.template.trim()) { setFormError('Template is required.'); return; }
    if (!form.template.includes('{content}')) {
      setFormError('Template must include the {content} placeholder.');
      return;
    }

    setSaving(true);
    setFormError('');
    try {
      if (editing) {
        await api.updatePrompt(editing.id, {
          name:          form.name.trim(),
          system_prompt: form.system_prompt,
          template:      form.template,
        });
      } else {
        await api.createPrompt({
          name:          form.name.trim(),
          mode,
          system_prompt: form.system_prompt,
          template:      form.template,
        });
      }
      closeForm();
      await load();
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (p: Prompt) => {
    if (!confirm(`Delete "${p.name}"?`)) return;
    try {
      await api.deletePrompt(p.id);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleReset = async () => {
    try {
      await api.resetPrompts();
      setConfirmReset(false);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  const defaults = prompts.filter(p => p.is_default);
  const custom   = prompts.filter(p => !p.is_default);
  // Built-in modes, plus any custom-only modes, for the mode selector.
  const modeOptions = Array.from(
    new Map(
      // customs first so a built-in's label wins for shared modes
      [...prompts].sort((a, b) => Number(a.is_default) - Number(b.is_default))
        .map(p => [p.mode, { value: p.mode, label: p.is_default ? p.name : `${p.name} (${p.mode})` }]),
    ).values(),
  );
  if (editing && !modeOptions.some(m => m.value === form.mode)) {
    modeOptions.push({ value: form.mode, label: form.mode });
  }

  return (
    <div className="prompts-page">
      <div className="prompts-inner">

        <Link to="/" className="prompts-back">
          <ArrowLeft size={15} aria-hidden="true" />
          All tools
        </Link>

        <div className="prompts-header">
          <div className="prompts-header-icon">
            <BookOpen size={20} aria-hidden="true" />
          </div>
          <div>
            <h1 className="prompts-title">Prompts</h1>
            <p className="prompts-subtitle">Manage summarization prompt templates</p>
          </div>
        </div>

        {error && (
          <div className="prompts-error" role="alert">
            {error}
            <button onClick={() => setError('')} aria-label="Dismiss"><X size={14} /></button>
          </div>
        )}

        {/* Toolbar */}
        <div className="prompts-toolbar">
          <button className="prompts-btn prompts-btn--primary" onClick={openNew}>
            <Plus size={15} aria-hidden="true" />
            New Prompt
          </button>
          {!confirmReset ? (
            <button className="prompts-btn prompts-btn--ghost" onClick={() => setConfirmReset(true)}>
              <RotateCcw size={14} aria-hidden="true" />
              Reset Defaults
            </button>
          ) : (
            <div className="prompts-reset-confirm">
              <span>Reset all built-in prompts to defaults?</span>
              <button className="prompts-btn prompts-btn--danger" onClick={handleReset}>Yes, reset</button>
              <button className="prompts-btn prompts-btn--ghost" onClick={() => setConfirmReset(false)}>Cancel</button>
            </div>
          )}
        </div>

        {loading && <p className="prompts-empty">Loading…</p>}

        {!loading && (
          <>
            {/* Built-in prompts */}
            <section className="prompts-section">
              <h2 className="prompts-section-title">Built-in</h2>
              <ul className="prompts-list">
                {defaults.map(p => (
                  <li key={p.id} className="prompts-item">
                    <div className="prompts-item-info">
                      <span className="prompts-item-name">{p.name}</span>
                      <span className="prompts-item-mode">{p.mode}</span>
                    </div>
                    <div className="prompts-item-actions">
                      <button
                        className="prompts-icon-btn"
                        onClick={() => openEdit(p)}
                        title="Edit"
                        aria-label={`Edit ${p.name}`}
                      >
                        <Edit2 size={14} />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>

            {/* Custom prompts */}
            {custom.length > 0 && (
              <section className="prompts-section">
                <h2 className="prompts-section-title">Custom</h2>
                <ul className="prompts-list">
                  {custom.map(p => (
                    <li key={p.id} className="prompts-item">
                      <div className="prompts-item-info">
                        <span className="prompts-item-name">{p.name}</span>
                        <span className="prompts-item-mode">{p.mode}</span>
                      </div>
                      <div className="prompts-item-actions">
                        <button
                          className="prompts-icon-btn"
                          onClick={() => openEdit(p)}
                          title="Edit"
                          aria-label={`Edit ${p.name}`}
                        >
                          <Edit2 size={14} />
                        </button>
                        <button
                          className="prompts-icon-btn prompts-icon-btn--danger"
                          onClick={() => handleDelete(p)}
                          title="Delete"
                          aria-label={`Delete ${p.name}`}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {custom.length === 0 && defaults.length === 0 && (
              <p className="prompts-empty">No prompts found.</p>
            )}
          </>
        )}

      </div>

      {/* ── Editor drawer / modal ──────────────────────────────────────────── */}
      {showForm && (
        <div className="prompts-overlay" onClick={closeForm}>
          <div className="prompts-drawer" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">

            <div className="prompts-drawer-header">
              <h2 className="prompts-drawer-title">
                {editing ? `Edit: ${editing.name}` : 'New Prompt'}
              </h2>
              <button className="prompts-icon-btn" onClick={closeForm} aria-label="Close">
                <X size={16} />
              </button>
            </div>

            {formError && (
              <div className="prompts-form-error" role="alert">{formError}</div>
            )}

            <div className="prompts-form">

              <div className="prompts-field">
                <label className="prompts-label" htmlFor="pf-name">Name</label>
                <input
                  id="pf-name"
                  type="text"
                  className="prompts-input"
                  value={form.name}
                  onChange={e => setField('name', e.target.value)}
                  placeholder="e.g. Meeting Summary"
                  maxLength={80}
                />
              </div>

              <div className="prompts-field">
                <label className="prompts-label" htmlFor="pf-mode">
                  Mode
                  {editing && <span className="prompts-label-hint">Mode cannot be changed after creation</span>}
                </label>
                <select
                  id="pf-mode"
                  className="prompts-select"
                  value={form.mode}
                  onChange={e => setField('mode', e.target.value)}
                  disabled={!!editing}
                >
                  {modeOptions.map(m => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                  {!editing && <option value={NEW_MODE}>New mode…</option>}
                </select>
                {form.mode === NEW_MODE && !editing && (
                  <input
                    type="text"
                    className="prompts-input"
                    style={{ marginTop: 8 }}
                    value={newModeSlug}
                    onChange={e => setNewModeSlug(e.target.value)}
                    placeholder={`Mode id, e.g. ${toSlug(form.name) || 'podcast_notes'}`}
                    aria-label="New mode id"
                  />
                )}
              </div>

              <div className="prompts-field">
                <label className="prompts-label" htmlFor="pf-system">
                  System Prompt
                  <span className="prompts-label-hint">Sets the model's persona and behavior (optional)</span>
                </label>
                <textarea
                  id="pf-system"
                  className="prompts-textarea"
                  value={form.system_prompt}
                  onChange={e => setField('system_prompt', e.target.value)}
                  placeholder="You are a helpful assistant..."
                  rows={4}
                />
              </div>

              <div className="prompts-field">
                <label className="prompts-label" htmlFor="pf-template">
                  Template
                  <span className="prompts-label-hint">
                    Must include <code>{'{content}'}</code> — replaced with source text at runtime
                  </span>
                </label>
                <textarea
                  id="pf-template"
                  className="prompts-textarea prompts-textarea--tall"
                  value={form.template}
                  onChange={e => setField('template', e.target.value)}
                  placeholder={"Summarize the following content:\n\n{content}"}
                  rows={7}
                  spellCheck={false}
                />
              </div>

            </div>

            <div className="prompts-drawer-footer">
              <button className="prompts-btn prompts-btn--ghost" onClick={closeForm}>
                Cancel
              </button>
              <button
                className="prompts-btn prompts-btn--primary"
                onClick={handleSave}
                disabled={saving}
              >
                <Save size={14} aria-hidden="true" />
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>

          </div>
        </div>
      )}
    </div>
  );
}
