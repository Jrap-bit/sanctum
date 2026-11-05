'use client';
import { FormEvent, useState } from 'react';
import { Require } from '@/components/shell';
import { Badge, ConfirmAction, Field, Message, PageHeader, Panel, State } from '@/components/ui';
import { Icon } from '@/components/icon';
import { useAuth } from '@/lib/auth';
import { post } from '@/lib/api';
import { useAction, useResource } from '@/lib/hooks';
import type { Capability, User } from '@/lib/types';
const labels:Record<Capability,string>={
  'patients:read':'View patients','patients:create':'Add patients','clinical:read':'Read clinical records','clinical:write':'Write notes','documents:write':'Review documents','summaries:write':'Review AI drafts','indicators:write':'Evaluate indicators','reports:write':'Build reports','users:manage':'Manage people','assignments:manage':'Manage assignments','grants:request':'Request access','grants:approve':'Approve access','rules:publish':'Publish rules','audit:read':'View activity log','operations:manage':'Manage system','patients:delete':'Delete patients'
};
const presets:{name:string;hint:string;icon:'notes'|'users'|'shield';caps:Capability[]}[]=[
  {name:'Practitioner',hint:'Patient care and notes',icon:'notes',caps:['patients:read','patients:create','clinical:read','clinical:write','documents:write','summaries:write','indicators:write','reports:write','grants:request']},
  {name:'Administrator',hint:'Accounts and assignments',icon:'users',caps:['patients:read','patients:create','users:manage','assignments:manage','grants:request','audit:read','operations:manage']},
  {name:'Clinical oversight',hint:'Scoped review and rules',icon:'shield',caps:['patients:read','clinical:read','reports:write','grants:approve','rules:publish','audit:read']}
];
type Account = User & { active: boolean; credentialsReady: boolean; resetRequired: boolean };
type CredentialAction = { purpose: 'activation' | 'reset'; url: string; expiresAt: string };
type AccountResult = { user: Account; credentialAction: CredentialAction | null };
export default function UsersPage() {
  const { user } = useAuth();
  const { data, loading, error, reload } = useResource<{items: Account[]}>('/admin/users');
  const action = useAction();
  const [username, setUsername] = useState('');
  const [name, setName] = useState('');
  const [caps, setCaps] = useState<Capability[]>([]);
  const [role, setRole] = useState<number | null>(null);
  const [notice, setNotice] = useState('');
  const [credential, setCredential] = useState<(CredentialAction & {name: string}) | null>(null);
  const [copyNotice, setCopyNotice] = useState('');
  const showResult = (result: AccountResult, message: string) => {
    setNotice(message); setCopyNotice('');
    setCredential(result.credentialAction ? {...result.credentialAction, name: result.user.displayName} : null);
  };
  const create = async (e: FormEvent) => {
    e.preventDefault(); setNotice('');
    const result = await action.run(() => post<AccountResult>('/admin/users', {username, displayName: name, capabilities: caps}));
    if (!result) return;
    showResult(result, 'Account created. Share the activation link privately with this person.');
    setUsername(''); setName(''); setCaps([]); setRole(null); await reload();
  };
  const update = async (account: Account, operation: string) => {
    setNotice('');
    const result = await action.run(() => post<AccountResult>(`/admin/users/${encodeURIComponent(account.id)}/${operation}`, {}));
    if (!result) return;
    showResult(result, operation === 'deactivate' ? 'Account deactivated. Previous sessions have ended.' : result.credentialAction ? 'New link ready. Any previous link has been cancelled.' : 'Account reactivated. The person can sign in again.');
    await reload();
  };
  return <Require cap="users:manage"><PageHeader title="People & roles"/>
    <Message error={action.error} success={notice}/>
    {credential && <Panel title={`${credential.purpose === 'activation' ? 'Activation' : 'Password reset'} link for ${credential.name}`}>
      <div className="stack"><p>Share this link privately. It works once and expires {new Date(credential.expiresAt).toLocaleString()}. Copy it before leaving this page.</p>
        <Field label="One-use link"><input readOnly value={credential.url} onFocus={e => e.target.select()}/></Field>
        <div className="row"><button className="button" onClick={async () => {
          try { await navigator.clipboard.writeText(credential.url); setCopyNotice('Link copied.'); }
          catch { setCopyNotice('Select the link above and copy it manually.'); }
        }}>Copy link</button><button className="button ghost" onClick={() => setCredential(null)}>Dismiss link</button></div>
        {copyNotice && <p role="status">{copyNotice}</p>}
      </div>
    </Panel>}
    <div className="grid"><Panel title="Add a teammate" icon="users"><form className="stack" onSubmit={create}>
      <Field label="Name"><input required maxLength={160} value={name} onChange={e => setName(e.target.value)} placeholder="Display name"/></Field>
      <Field label="Username" hint="3–64 letters, numbers, dots, underscores or hyphens."><input required minLength={3} maxLength={64} pattern="[a-zA-Z0-9_.\-]{3,64}" value={username} onChange={e => setUsername(e.target.value)} placeholder="Sign-in name"/></Field>
      <div className="field"><span>Start with a role</span><div className="preset-grid">{presets.map((p, i) => <button type="button" key={p.name} className={`preset-card ${role === i ? 'selected' : ''}`} onClick={() => {setRole(i); setCaps(p.caps);}}><Icon name={p.icon} size={20}/><strong>{p.name}</strong><small>{p.hint}</small></button>)}</div></div>
      {role !== null && <details className="compact-details"><summary>Fine-tune permissions · {caps.length} selected</summary><p className="small muted">Choose permissions within the selected role.</p><div className="permission-grid">{presets[role].caps.map(cap => <label className="checkbox" key={cap}><input type="checkbox" checked={caps.includes(cap)} onChange={e => setCaps(e.target.checked ? [...caps, cap] : caps.filter(c => c !== cap))}/>{labels[cap]}</label>)}</div></details>}
      <button className="button primary" disabled={action.pending || !caps.length || !name.trim()}><Icon name="plus" size={16}/> Create account</button>
    </form></Panel>
    <Panel title="Team members" icon="patient"><State loading={loading} error={error} empty={!data?.items.length}>{data?.items.map(u => <div className="list-item" key={u.id}>
      <div className="row between"><div className="row"><span className="avatar">{u.displayName.charAt(0)}</span><span><strong>{u.displayName}</strong><small style={{display: 'block'}}>@{u.username}</small></span></div><Badge>{!u.credentialsReady ? 'Pending activation' : !u.active ? 'Inactive' : u.resetRequired ? 'Password reset pending' : 'Active'}</Badge></div>
      <details className="compact-details" style={{margin: '12px 0'}}><summary>{u.capabilities.length} permissions</summary><p className="small muted">{u.capabilities.map(c => labels[c] || c).join(' · ') || 'None'}</p></details>
      {u.id === user?.id ? <p className="small muted">Your account. Another administrator can manage your access.</p> : <div className="row">
        {u.active && u.credentialsReady && <ConfirmAction label="Issue reset" consequence="This signs the person out and blocks their old password. Share the new reset link so they can regain access." busy={action.pending} onConfirm={() => void update(u, 'reset-credential')}/>}
        {u.active ? <ConfirmAction label="Deactivate" consequence="Active sessions end. Earlier authored notes keep their attribution." busy={action.pending} onConfirm={() => void update(u, 'deactivate')}/> : <button className="button small-button" disabled={action.pending} onClick={() => void update(u, 'reactivate')}>{u.credentialsReady ? 'Reactivate' : 'Issue new activation link'}</button>}
      </div>}
    </div>)}</State></Panel></div>
  </Require>;
}
