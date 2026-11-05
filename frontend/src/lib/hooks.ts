'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';

export function useResource<T>(path: string | null) {
  const [resource, setResource] = useState<{path: string | null; data: T | null; loading: boolean; error: Error | null}>({path, data: null, loading: Boolean(path), error: null});
  const requestId = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const reload = useCallback(async () => {
    const current = ++requestId.current;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setResource({path, data: null, loading: Boolean(path), error: null});
    if (!path) return;
    try {
      const data = await api<T>(path, {signal: abort.signal});
      if (current === requestId.current) setResource({path, data, loading: false, error: null});
    } catch (error) {
      if (current === requestId.current && !abort.signal.aborted) setResource({path, data: null, loading: false, error: error as Error});
    }
  }, [path]);
  useEffect(() => { void reload(); return () => { requestId.current++; controller.current?.abort(); }; }, [reload]);
  useEffect(() => {
    const clear = () => {
      requestId.current++; controller.current?.abort();
      setResource({path, data: null, loading: false, error: new ApiError(401, 'EXPIRED', 'Session expired. Sign in again.')});
    };
    window.addEventListener('sanctum:expired', clear);
    return () => window.removeEventListener('sanctum:expired', clear);
  }, [path]);
  const setData = useCallback((value: T | null | ((old: T | null) => T | null)) => {
    setResource(old => ({...old, path, data: typeof value === 'function' ? (value as (old: T | null) => T | null)(old.path === path ? old.data : null) : value}));
  }, [path]);
  // A new route must never render the previous patient's data before its effect runs.
  const current = resource.path === path ? resource : {data: null, loading: Boolean(path), error: null};
  return {...current, reload, setData};
}

export function useAction() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const active = useRef(false);
  const run = async <T,>(operation: () => Promise<T>): Promise<T | undefined> => {
    if (active.current) return;
    active.current = true; setPending(true); setError(null);
    try { return await operation(); }
    catch (error) { setError(error instanceof Error ? error : new Error('The action could not be completed. Try again.')); }
    finally { active.current = false; setPending(false); }
  };
  return {pending, error, run, setError};
}
