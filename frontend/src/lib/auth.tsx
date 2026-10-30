'use client';
import { createContext, useContext, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { api, ApiError } from './api';
import type { Capability, User } from './types';
type AuthContextValue = { user: User | null; loading: boolean; refresh: () => Promise<void>; has: (cap: Capability) => boolean; logout: () => Promise<void> };
const AuthContext = createContext<AuthContextValue | null>(null);
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter(); const pathname = usePathname();
  const refresh = async () => {
    setLoading(true);
    try { setUser(await api<User>('/auth/me')); }
    catch (e) { setUser(null); if (e instanceof ApiError && e.status === 401 && !['/login', '/activate'].includes(pathname)) router.replace('/login?expired=1'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void refresh(); /* initial session check */ }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const expired = () => { setUser(null); router.replace('/login?expired=1'); };
    window.addEventListener('sanctum:expired', expired);
    return () => window.removeEventListener('sanctum:expired', expired);
  }, [router]);
  const logout = async () => { try { await api('/auth/logout', { method: 'POST' }); } finally { setUser(null); router.replace('/login'); router.refresh(); } };
  return <AuthContext.Provider value={{ user, loading, refresh, has: cap => Boolean(user?.capabilities.includes(cap)), logout }}>{children}</AuthContext.Provider>;
}
export function useAuth() { const value = useContext(AuthContext); if (!value) throw new Error('Missing AuthProvider'); return value; }
