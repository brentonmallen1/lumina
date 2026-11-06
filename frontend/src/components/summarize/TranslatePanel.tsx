import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Languages, Loader, Volume2 } from 'lucide-react';
import * as api from '../../api/client';

const LANGUAGES = [
  'Spanish', 'French', 'German', 'Portuguese', 'Italian', 'Chinese', 'Japanese', 'Korean',
  'Russian', 'Arabic', 'Hindi', 'Dutch', 'Swedish', 'Polish', 'Turkish',
];

interface TranslatePanelProps {
  /** Text to translate. The translation resets whenever this changes. */
  text: string;
  ttsEnabled: boolean;
  ttsLoading: boolean;
  onReadAloud: (text: string) => void;
}

export default function TranslatePanel({ text, ttsEnabled, ttsLoading, onReadAloud }: TranslatePanelProps) {
  const [lang, setLang] = useState('Spanish');
  const [translation, setTranslation] = useState('');
  const [state, setState] = useState<'idle' | 'streaming' | 'done' | 'error'>('idle');
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  // A different result (mode switch, re-run) invalidates the old translation.
  useEffect(() => {
    abortRef.current?.abort();
    setTranslation('');
    setState('idle');
    return () => abortRef.current?.abort();
  }, [text]);

  const run = async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setTranslation('');
    setError('');
    setState('streaming');
    let acc = '';
    await api.translateStream(text, lang, {
      onChunk: chunk => { acc += chunk; setTranslation(acc); },
      onDone: () => setState('done'),
      onError: msg => { setError(msg); setState('error'); },
    }, controller.signal);
  };

  return (
    <div className="summarize-translate-panel">
      <div className="summarize-translate-controls">
        <Languages size={14} className="summarize-translate-icon" aria-hidden="true" />
        <select
          className="summarize-translate-select"
          value={lang}
          onChange={e => { setLang(e.target.value); setTranslation(''); setState('idle'); }}
          aria-label="Target language"
        >
          {LANGUAGES.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
        <button className="summarize-action-btn" onClick={run} disabled={state === 'streaming'}>
          {state === 'streaming' ? 'Translating…' : state === 'done' ? 'Re-translate' : 'Translate'}
        </button>
      </div>
      {state === 'error' && <p className="summarize-translate-error">{error}</p>}
      {(state === 'streaming' || state === 'done') && translation && (
        <div className="summarize-translate-result">
          {state === 'done'
            ? <div className="markdown"><ReactMarkdown>{translation}</ReactMarkdown></div>
            : <>{translation}<span className="summarize-cursor" aria-hidden="true" /></>}
        </div>
      )}
      {ttsEnabled && state === 'done' && translation && (
        <div className="summarize-translate-tts">
          <button
            className="summarize-action-btn"
            onClick={() => onReadAloud(translation)}
            disabled={ttsLoading}
            title="Read translation aloud"
          >
            {ttsLoading
              ? <><Loader size={13} className="summarize-tts-spin" aria-hidden="true" /> Generating…</>
              : <><Volume2 size={13} aria-hidden="true" /> Read Aloud</>}
          </button>
        </div>
      )}
    </div>
  );
}
