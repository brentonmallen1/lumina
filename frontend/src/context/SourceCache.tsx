import { createContext, useContext, useRef, useCallback, type ReactNode } from 'react';

export interface CachedSource {
  content:    string;
  label:      string;  // URL or filename — for display
  sourceType: string;  // 'youtube' | 'url' | 'audio' | 'pdf'
}

interface SourceCacheContextValue {
  get: (key: string) => CachedSource | null;
  set: (key: string, value: CachedSource) => void;
}

const SourceCacheContext = createContext<SourceCacheContextValue | null>(null);

const STORAGE_KEY = 'whisper-source-cache';

function loadFromStorage(): Record<string, CachedSource> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, CachedSource>) : {};
  } catch {
    return {};
  }
}

export function SourceCacheProvider({ children }: { children: ReactNode }) {
  const cacheRef = useRef<Record<string, CachedSource>>(loadFromStorage());

  const get = useCallback((key: string): CachedSource | null => {
    return cacheRef.current[key] ?? null;
  }, []);

  const set = useCallback((key: string, value: CachedSource) => {
    cacheRef.current[key] = value;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(cacheRef.current));
    } catch {
      // sessionStorage quota exceeded or unavailable — cache still lives in memory
    }
  }, []);

  return (
    <SourceCacheContext.Provider value={{ get, set }}>
      {children}
    </SourceCacheContext.Provider>
  );
}

export function useSourceCache(): SourceCacheContextValue {
  const ctx = useContext(SourceCacheContext);
  if (!ctx) throw new Error('useSourceCache must be used inside SourceCacheProvider');
  return ctx;
}
