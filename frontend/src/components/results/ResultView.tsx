import { lazy, Suspense } from 'react';
import ReactMarkdown from 'react-markdown';
import { jsonRenderer, parseJson } from './registry';

const MindMapDiagram = lazy(() => import('../MindMapDiagram'));

interface ResultViewProps {
  text: string;
  outputType?: string;
  /** Show the rendered form (markdown / diagram / formatted JSON) vs raw text. */
  rendered: boolean;
  streaming?: boolean;
  /** Source URL, so timestamped results can link back into the video. */
  sourceUrl?: string;
}

/**
 * Renders a mode result according to its output type. Unknown JSON renderers
 * and unparseable JSON fall back to a formatted code block.
 */
export default function ResultView({ text, outputType, rendered, streaming, sourceUrl }: ResultViewProps) {
  if (!text) return null;

  if (!streaming && rendered) {
    if (outputType === 'mindmap') {
      return (
        <Suspense fallback={<div className="summarize-output">Loading diagram…</div>}>
          <MindMapDiagram markdown={text} />
        </Suspense>
      );
    }
    const renderer = jsonRenderer(outputType);
    if (renderer) {
      const data = parseJson(text);
      const Custom = data ? JSON_RENDERERS[renderer] : undefined;
      if (Custom) return <Custom data={data} sourceUrl={sourceUrl} />;
      return <pre className="summarize-output summarize-output--json">{data ? JSON.stringify(data, null, 2) : text}</pre>;
    }
  }

  const isMarkdown = rendered && !streaming && !jsonRenderer(outputType);
  return (
    <div
      className={[
        'summarize-output',
        streaming ? 'streaming' : '',
        isMarkdown ? 'markdown' : '',
        jsonRenderer(outputType) ? 'summarize-output--json' : '',
      ].filter(Boolean).join(' ')}
      aria-live={streaming ? 'off' : 'polite'}
      aria-busy={streaming}
      aria-label="Result"
    >
      {isMarkdown
        ? <ReactMarkdown>{text}</ReactMarkdown>
        : <>{text}{streaming && <span className="summarize-cursor" aria-hidden="true" />}</>}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type JsonRendererComponent = React.ComponentType<{ data: any; sourceUrl?: string }>;

/** Structured renderers keyed by the part after `json:`. Registered by later phases. */
export const JSON_RENDERERS: Record<string, JsonRendererComponent> = {};
