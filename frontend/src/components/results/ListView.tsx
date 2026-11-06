import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { timestampUrl } from './timestamps';
import './results.css';

interface ListItem {
  rank?: number | null;
  title: string;
  detail?: string;
  timestamp?: string | null;
}

export interface ExtractedList {
  found?: boolean;
  list_title?: string;
  expected_count?: number | null;
  items?: ListItem[];
  honorable_mentions?: ListItem[];
}

function Timestamp({ ts, sourceUrl }: { ts?: string | null; sourceUrl?: string }) {
  if (!ts) return null;
  const href = timestampUrl(sourceUrl, ts);
  return href
    ? <a className="result-ts" href={href} target="_blank" rel="noreferrer">{ts}</a>
    : <span className="result-ts">{ts}</span>;
}

function toMarkdown(data: ExtractedList): string {
  const line = (i: ListItem) =>
    `${i.rank != null ? `${i.rank}. ` : '- '}**${i.title}**${i.timestamp ? ` (${i.timestamp})` : ''}${i.detail ? ` — ${i.detail}` : ''}`;
  const parts = [`## ${data.list_title || 'List'}`, '', ...(data.items ?? []).map(line)];
  if (data.honorable_mentions?.length) {
    parts.push('', '### Honorable mentions', '', ...data.honorable_mentions.map(line));
  }
  return parts.join('\n');
}

export default function ListView({ data, sourceUrl }: { data: ExtractedList; sourceUrl?: string }) {
  const [copied, setCopied] = useState(false);
  const items = data.items ?? [];
  const mentions = data.honorable_mentions ?? [];

  if (data.found === false || items.length === 0) {
    return <div className="result-empty">No ranked or numbered list was found in this content.</div>;
  }

  const expected = data.expected_count ?? null;
  const short = expected !== null && items.length < expected;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toMarkdown(data));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard unavailable */ }
  };

  return (
    <div className="result-structured">
      <div className="result-structured-head">
        <div>
          {data.list_title && <h3 className="result-structured-title">{data.list_title}</h3>}
          <p className={`result-count${short ? ' result-count--short' : ''}`}>
            {expected !== null ? `${items.length} of ${expected} items found` : `${items.length} items`}
            {short && ' — some items may have been missed; try re-running or turning on thinking.'}
          </p>
        </div>
        <button className="summarize-action-btn" onClick={copy}>
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          {copied ? 'Copied' : 'Copy as Markdown'}
        </button>
      </div>

      <ol className="result-list">
        {items.map((item, i) => (
          <li key={`${item.title}-${i}`} className="result-list-item">
            <span className="result-rank" aria-hidden="true">{item.rank ?? '•'}</span>
            <div className="result-list-body">
              <div className="result-list-title-row">
                <span className="result-list-title">{item.title}</span>
                <Timestamp ts={item.timestamp} sourceUrl={sourceUrl} />
              </div>
              {item.detail && <p className="result-list-detail">{item.detail}</p>}
            </div>
          </li>
        ))}
      </ol>

      {mentions.length > 0 && (
        <>
          <h4 className="result-subhead">Honorable mentions</h4>
          <ul className="result-list result-list--plain">
            {mentions.map((item, i) => (
              <li key={`${item.title}-${i}`} className="result-list-item">
                <div className="result-list-body">
                  <div className="result-list-title-row">
                    <span className="result-list-title">{item.title}</span>
                    <Timestamp ts={item.timestamp} sourceUrl={sourceUrl} />
                  </div>
                  {item.detail && <p className="result-list-detail">{item.detail}</p>}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
