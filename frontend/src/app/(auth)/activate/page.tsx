'use client';
import { FormEvent, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { post } from '@/lib/api';
import { Field, Message } from '@/components/ui';
export default function ActivatePage() { const token = useSearchParams().get('token') || ''; const router = useRouter(); const [password, setPassword] = useState(''); const [confirm, setConfirm] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState<Error | null>(null); const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => { e.preventDefault(); if (password !== confirm) { setError(new Error('Passwords do not match.')); return; } setBusy(true); setError(null); try { await post('/auth/activate', { token, password }); setDone(true); router.replace('/login'); } catch (e) { setError(e as Error); } finally { setBusy(false); } };
  return <div className="center-screen"><div className="panel auth-card"><div className="eyebrow">SANCTUM / ACCOUNT</div><h1>Make it yours</h1>{!token ? <div className="notice danger">This password-setting link is missing a token. Request a new link from your administrator.</div> : done ? <p>Password saved. <Link href="/login">Sign in</Link>.</p> : <form onSubmit={submit} className="stack"><p className="muted">Choose a password for your clinic account.</p><Message error={error}/><Field label="New password"><input type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={password} onChange={e => setPassword(e.target.value)}/></Field><Field label="Confirm password"><input type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={confirm} onChange={e => setConfirm(e.target.value)}/></Field><button className="button primary" disabled={busy}>{busy ? 'Saving…' : 'Set password'}</button></form>}</div></div>;
}
