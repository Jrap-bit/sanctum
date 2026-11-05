'use client';
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { api, ApiError } from './api';
import type { Capability, User } from './types';
type AuthContextValue = { user: User | null; loading: boolean; refresh: () => Promise<void>; has: (cap: Capability) => boolean; logout: () => Promise<void> };
const AuthContext = createContext<AuthContextValue | null>(null);
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const sessionVersion = useRef(0);
  const router = useRouter(); const pathname = usePathname();
  const refresh = async () => {
    const version = ++sessionVersion.current;
    setLoading(true);
    try { const current = await api<User>('/auth/me'); if (version === sessionVersion.current) setUser(current); }
    catch (e) { if (version !== sessionVersion.current) return; setUser(null); if (e instanceof ApiError && e.status === 401 && !['/login', '/activate'].includes(pathname)) router.replace('/login?expired=1'); }
    finally { if (version === sessionVersion.current) setLoading(false); }
  };
  useEffect(() => { void refresh(); /* initial session check */ }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const expired = () => { sessionVersion.current++; setLoading(false); setUser(null); router.replace('/login?expired=1'); };
    window.addEventListener('sanctum:expired', expired);
    return () => window.removeEventListener('sanctum:expired', expired);
  }, [router]);
  const logout = async () => {
    // Keep the workspace visible if the server could not end the session.
    await api('/auth/logout', { method: 'POST', signal: AbortSignal.timeout(15000) });
    sessionVersion.current++;
    setUser(null);
    // A full navigation discards private page state and rechecks the cookie.
    window.location.replace('/login');
  };
  return <AuthContext.Provider value={{ user, loading, refresh, has: cap => Boolean(user?.capabilities.includes(cap)), logout }}>{children}</AuthContext.Provider>;
}
export function useAuth() { const value = useContext(AuthContext); if (!value) throw new Error('Missing AuthProvider'); return value; }
