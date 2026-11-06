import { useState } from 'react';
import { ChefHat, ExternalLink, FileJson, FileText, Loader } from 'lucide-react';
import * as api from '../../api/client';
import { parseJson } from './registry';
import './results.css';

export type RecipeFormat = 'markdown' | 'jsonld';

interface RecipeToolsProps {
  /** Format of `text`. */
  format: RecipeFormat;
  text: string;
  /** Already-known text for each format, so switching back is instant. */
  cached?: Partial<Record<RecipeFormat, string>>;
  /** Called with the other format's text after a switch. */
  onConvert: (format: RecipeFormat, text: string) => void;
  sourceUrl?: string;
  mealieReady: boolean;
}

/**
 * Markdown / JSON-LD switch and "Send to Mealie" for a recipe result.
 * JSON-LD → Markdown is instant (done in code); Markdown → JSON-LD is parsed
 * in code for Lumina's own recipes and only falls back to the LLM otherwise.
 */
export default function RecipeTools({ format, text, cached, onConvert, sourceUrl, mealieReady }: RecipeToolsProps) {
  const [converting, setConverting] = useState(false);
  const [sending, setSending] = useState(false);
  const [link, setLink] = useState('');
  const [error, setError] = useState('');

  const switchTo = async (target: RecipeFormat) => {
    if (target === format || converting) return;
    setError('');
    const known = cached?.[target];
    if (known) { onConvert(target, known); return; }
    setConverting(true);
    try {
      if (target === 'markdown') {
        const { markdown } = await api.recipeToMarkdown(parseJson(text) ?? text);
        onConvert('markdown', markdown);
      } else {
        const recipe = await api.convertRecipeToJsonLD(text, sourceUrl);
        onConvert('jsonld', JSON.stringify(recipe, null, 2));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Conversion failed');
    } finally {
      setConverting(false);
    }
  };

  const send = async () => {
    setSending(true);
    setError('');
    try {
      const input = format === 'jsonld' ? { recipe: parseJson(text) ?? text } : { markdown: text };
      setLink((await api.sendRecipeToMealie(input, sourceUrl)).url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sending to Mealie failed');
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <div className="recipe-format-switch" role="group" aria-label="Recipe format">
        <button
          className={`summarize-action-btn${format === 'markdown' ? ' active' : ''}`}
          aria-pressed={format === 'markdown'}
          onClick={() => switchTo('markdown')}
          disabled={converting}
        >
          <FileText size={14} aria-hidden="true" /> Markdown
        </button>
        <button
          className={`summarize-action-btn${format === 'jsonld' ? ' active' : ''}`}
          aria-pressed={format === 'jsonld'}
          onClick={() => switchTo('jsonld')}
          disabled={converting}
          title="schema.org Recipe JSON-LD — imports into Mealie and other recipe managers"
        >
          {converting
            ? <Loader size={13} className="summarize-tts-spin" aria-hidden="true" />
            : <FileJson size={14} aria-hidden="true" />} JSON-LD
        </button>
      </div>
      {mealieReady && (link ? (
        <a className="summarize-action-btn" href={link} target="_blank" rel="noreferrer">
          <ExternalLink size={14} aria-hidden="true" /> Open in Mealie
        </a>
      ) : (
        <button className="summarize-action-btn" onClick={send} disabled={sending} title="Create this recipe in Mealie">
          {sending
            ? <><Loader size={13} className="summarize-tts-spin" aria-hidden="true" /> Sending…</>
            : <><ChefHat size={14} aria-hidden="true" /> Send to Mealie</>}
        </button>
      ))}
      {error && <span className="summarize-jsonld-error" role="alert">{error}</span>}
    </>
  );
}
