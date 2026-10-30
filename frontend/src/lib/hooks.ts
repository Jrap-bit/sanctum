'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<ApiError | Error | null>(null);
  const requestId = useRef(0);
  const reload = useCallback(async () => {
    const current = ++requestId.current;
    if (!path) { setData(null); setLoading(false); return; }
    setLoading(true); setError(null); setData(null);
    try { const result = await api<T>(path); if (current === requestId.current) setData(result); }
    catch (e) { if (current === requestId.current) { setData(null); setError(e as Error); } }
    finally { if (current === requestId.current) setLoading(false); }
  }, [path]);
  useEffect(() => { void reload(); return () => { requestId.current++; }; }, [reload]);
  useEffect(() => {
    const clear = () => { requestId.current++; setData(null); setLoading(false); setError(new ApiError(401, 'EXPIRED', 'Session expired')); };
    window.addEventListener('sanctum:expired', clear);
    return () => window.removeEventListener('sanctum:expired', clear);
  }, []);
  return { data, loading, error, reload, setData };
}
export function useAction() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const run = async <T,>(operation: () => Promise<T>): Promise<T | undefined> => {
    if (pending) return;
    setPending(true); setError(null);
    try { return await operation(); } catch (e) { setError(e as Error); } finally { setPending(false); }
  };
  return { pending, error, run, setError };
}
