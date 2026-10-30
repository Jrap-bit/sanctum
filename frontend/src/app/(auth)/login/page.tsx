'use client';

import { FormEvent, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useResource } from '@/lib/hooks';
import type { Health } from '@/lib/types';
import { Icon } from '@/components/icon';
import { Field, Message } from '@/components/ui';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useAuth();
  const health = useResource<Health>('/health');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
      await refresh();
      const next = params.get('next');
      router.replace(next && next.startsWith('/') && !next.startsWith('//') ? next : '/patients');
    } catch {
      setError(new Error('Sign-in failed. Check your username and password.'));
    } finally {
      setBusy(false);
    }
  };

  return <div className="auth-screen">
    <main className="auth-main">
      <header className="auth-header">
        <div className="auth-brand" aria-label="Sanctum">
          <span className="brand-mark"><Icon name="sparkle" size={36}/></span>
          <h1 className="auth-brand-name">sanctum</h1>
        </div>
        <p className="auth-definition">Therapy records, organized.</p>
        <p className="auth-description">Notes, documents, and AI drafts you review.</p>
      </header>
      <section className="auth-card" aria-labelledby="login-title">
        <h2 id="login-title">Sign in</h2>
        {process.env.NEXT_PUBLIC_DEMO_MODE === '1' && <details className="auth-demo-access"><summary><Icon name="key" size={16}/><span>Synthetic demo access</span><Icon name="chevron" size={14}/></summary><dl className="auth-demo-credentials"><div><dt>Username</dt><dd><code>clinician</code><code>admin</code><code>oversight</code></dd></div><div><dt>Password</dt><dd><code>demo123</code></dd></div></dl><p>Demo data resets on restart.</p></details>}
        {params.has('expired') && <div className="notice warning">Your session ended. Please sign in again.</div>}
        {health.error && <div className="notice warning">Local service unavailable. Try again when it’s online.</div>}
        {health.data?.database && health.data.database !== 'healthy' && <div className="notice warning">The records service needs attention.</div>}
        <Message error={error}/>
        <form onSubmit={submit}>
          <Field label="Username"><input autoComplete="username" required value={username} onChange={e => setUsername(e.target.value)}/></Field>
          <Field label="Password"><div className="auth-password"><input type={show ? 'text' : 'password'} autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)}/><button type="button" onClick={() => setShow(!show)} aria-label={show ? 'Hide password' : 'Show password'}>{show ? 'Hide' : 'Show'}</button></div></Field>
          <button className="button primary auth-submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}<span aria-hidden="true">↗</span></button>
        </form>
        <p className="auth-help"><span>Need access or a password reset?</span><span>Contact your clinic administrator.</span></p>
      </section>
    </main>
  </div>;
}
