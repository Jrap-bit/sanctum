'use client';

import { FormEvent, useEffect, useState } from 'react';
import { post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { Message } from '@/components/ui';

const ROLES = [
  { value: 'clinician', label: 'Clinician', description: 'Patient records, notes, document imports, AI review and reports.' },
  { value: 'admin', label: 'Administrator', description: 'Accounts and operations. No access to clinical content.' },
  { value: 'oversight', label: 'Clinical oversight', description: 'Reviews access requests and publishes rule versions.' },
  { value: 'clinical_admin', label: 'Clinical administrator', description: 'Administrator and oversight together, including permanent patient deletion.' },
];

export default function ChooseRolePage() {
  const { user, loading } = useAuth();
  const [role, setRole] = useState('clinician');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (user && user.capabilities.length > 0) window.location.replace('/patients');
  }, [user]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post('/auth/role', { role });
      window.location.replace('/patients');
    } catch (failure) {
      setError(failure as Error);
      setBusy(false);
    }
  };

  return <div className="auth-screen">
    <main className="auth-main">
      <section className="auth-card" aria-labelledby="role-title">
        <h2 id="role-title">Choose your role</h2>
        {!loading && !user && <div className="notice warning">Sign in to continue.</div>}
        <Message error={error}/>
        <form onSubmit={submit}>
          <fieldset style={{ border: 0, padding: 0, margin: 0, display: 'grid', gap: 12 }}>
            <legend className="sr-only">Role</legend>
            {ROLES.map(option => <label key={option.value} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
              <input type="radio" name="role" value={option.value} checked={role === option.value} onChange={() => setRole(option.value)} style={{ marginTop: 4, width: 'auto' }}/>
              <span><strong>{option.label}</strong><br/><small>{option.description}</small></span>
            </label>)}
          </fieldset>
          <button className="button primary auth-submit" disabled={busy || loading || !user} style={{ marginTop: 18 }}>{busy ? 'Saving…' : 'Continue'}</button>
        </form>
      </section>
    </main>
  </div>;
}
