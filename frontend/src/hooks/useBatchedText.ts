import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Accumulate streamed text in a ref and flush to React state at most once per
 * animation frame. Streaming hundreds of tokens per second through setState
 * re-renders the whole page per token; this keeps it to ~60 renders/s.
 *
 * Returns [text, api] where api.current() reads the latest value synchronously.
 */
export function useBatchedText() {
  const [text, setText] = useState('');
  const ref = useRef('');
  const frame = useRef<number | null>(null);

  const flush = useCallback(() => {
    frame.current = null;
    setText(ref.current);
  }, []);

  const schedule = useCallback(() => {
    if (frame.current === null) frame.current = requestAnimationFrame(flush);
  }, [flush]);

  const append = useCallback((chunk: string) => {
    ref.current += chunk;
    schedule();
  }, [schedule]);

  const set = useCallback((value: string) => {
    ref.current = value;
    if (frame.current !== null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
    }
    setText(value);
  }, []);

  const current = useCallback(() => ref.current, []);

  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
  }, []);

  return [text, { append, set, current }] as const;
}
