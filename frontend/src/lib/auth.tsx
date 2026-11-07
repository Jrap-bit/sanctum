'use client';
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { api, ApiError } from './api';
import type { Capability, User } from './types';

type AuthContextValue = {user: User | null; loading: boolean; error: Error | null; refresh: () => Promise<void>; has: (cap: Capability) => boolean; logout: () => Promise<void>};
const AuthContext = createContext<AuthContextValue | null>(null);
export function AuthProvider({children}: {children: React.ReactNode}) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const sessionVersion = useRef(0);
  const router = useRouter();
  const pathname = usePathname();
  const pathRef = useRef(pathname); pathRef.current = pathname;
  const refresh = useCallback(async () => {
    const version = ++sessionVersion.current;
    setLoading(true); setError(null);
    try {
      const current = await api<User>('/auth/me');
      if (version === sessionVersion.current) setUser(current);
    } catch (failure) {
      if (version !== sessionVersion.current) return;
      setUser(null); setError(failure as Error);
      if (failure instanceof ApiError && failure.status === 401 && !['/login', '/activate'].includes(pathRef.current)) router.replace('/login?expired=1');
      throw failure;
    } finally {if (version === sessionVersion.current) setLoading(false);}
  }, [router]);
  useEffect(() => {void refresh().catch(() => {}); return () => {sessionVersion.current++;};}, [refresh]);
  useEffect(() => {
    const expired = () => {sessionVersion.current++; setLoading(false); setUser(null); setError(null); router.replace('/login?expired=1');};
    window.addEventListener('sanctum:expired', expired);
    return () => window.removeEventListener('sanctum:expired', expired);
  }, [router]);
  const logout = async () => {
    await api('/auth/logout', {method: 'POST', signal: AbortSignal.timeout(15000)});
    sessionVersion.current++; setUser(null);
    window.location.replace('/login');
  };
  return <AuthContext.Provider value={{user, loading, error, refresh, has: cap => Boolean(user?.capabilities.includes(cap)), logout}}>{children}</AuthContext.Provider>;
}
export function useAuth() {const value = useContext(AuthContext); if (!value) throw new Error('Missing AuthProvider'); return value;}
