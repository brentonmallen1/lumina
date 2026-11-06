/** "1:02:03" | "4:05" | "[4:05]" → seconds, or null. */
export function parseTimestamp(ts: string | null | undefined): number | null {
  if (!ts) return null;
  const m = ts.trim().replace(/^\[|\]$/g, '').match(/^(?:(\d+):)?(\d{1,2}):(\d{2})$/);
  if (!m) return null;
  return Number(m[1] ?? 0) * 3600 + Number(m[2]) * 60 + Number(m[3]);
}

/** Link to a moment in a YouTube video, or null for non-YouTube sources. */
export function timestampUrl(sourceUrl: string | undefined, ts: string | null | undefined): string | null {
  const seconds = parseTimestamp(ts);
  if (!sourceUrl || seconds === null) return null;
  try {
    const url = new URL(sourceUrl);
    const host = url.hostname.replace(/^www\.|^m\./, '');
    if (host !== 'youtube.com' && host !== 'youtu.be') return null;
    url.searchParams.set('t', `${seconds}s`);
    return url.toString();
  } catch {
    return null;
  }
}
