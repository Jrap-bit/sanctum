'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api, ApiError, patch, patientPath, post } from '@/lib/api';
import type { Assertion, NoteField, Session, Temporality } from '@/lib/types';
import { Badge, DateText, Field, Message, Panel, TimeText } from './ui';
type Content = Pick<Session, 'text' | 'eventDate' | 'concerns' | 'observations' | 'interventions' | 'medicationReported'>;
const sections = [['concerns','Concerns'],['observations','Observations'],['interventions','Interventions'],['medicationReported','Medication as reported']] as const;
export function SessionEditor({ initial, patientId }: { initial: Session; patientId: string }) {
  const router = useRouter(); const path = `${patientPath(patientId)}/sessions/${encodeURIComponent(initial.id)}`;
  const [content, setContent] = useState<Content>({ text: initial.text || '', eventDate: initial.eventDate, concerns: initial.concerns || [], observations: initial.observations || [], interventions: initial.interventions || [], medicationReported: initial.medicationReported || [] });
  const [session, setSession] = useState(initial); const [state, setState] = useState<'saved'|'unsaved'|'saving'|'unconfirmed'|'conflict'>('saved'); const [error, setError] = useState<Error | null>(null); const [savedAt, setSavedAt] = useState(initial.updatedAt); const [latest, setLatest] = useState<Session | null>(null); const [reason, setReason] = useState(''); const [busy, setBusy] = useState(false);
  const revision = useRef(0);
  const acknowledged = useRef(0);
  const saving = useRef<Promise<void> | null>(null);
  const busyRef = useRef(false);
  const contentRef = useRef(content);
  const versionRef = useRef(initial.version);
  const stateRef = useRef(state);
  const sessionRef = useRef(initial);
  const canEdit = session.state === 'draft' && session.allowedActions.includes('edit');

  const setSaveState = useCallback((next: typeof state) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const change = (next: Content) => {
    if (busyRef.current || !canEdit) return;
    revision.current++;
    contentRef.current = next;
    setContent(next);
    // Typing must not silently clear an unresolved server conflict.
    setSaveState(stateRef.current === 'conflict' ? 'conflict' : 'unsaved');
  };

  const save = useCallback(async () => {
    if (saving.current) { await saving.current; return; }
    if (revision.current === acknowledged.current || stateRef.current === 'conflict'
      || sessionRef.current.state !== 'draft' || !sessionRef.current.allowedActions.includes('edit')) return;
    const sentRevision = revision.current;
    const snapshot = contentRef.current;
    setSaveState('saving');
    setError(null);
    const operation = (async () => {
      try {
        const updated = await patch<Session>(path, { ...snapshot, expectedVersion: versionRef.current });
        versionRef.current = updated.version;
        sessionRef.current = updated;
        setSession(updated);
        acknowledged.current = sentRevision;
        setSavedAt(updated.updatedAt);
        setSaveState(revision.current === sentRevision ? 'saved' : 'unsaved');
      } catch (e) {
        const err = e as Error;
        setError(err);
        if (err instanceof ApiError && err.status === 409) {
          setSaveState('conflict');
          try { setLatest(await api<Session>(path)); } catch { /* Keep unsaved local text. */ }
        } else setSaveState('unconfirmed');
      }
    })();
    saving.current = operation;
    try { await operation; } finally { saving.current = null; }
  }, [path, setSaveState]);

  useEffect(() => {
    if (state !== 'unsaved' || busy || !canEdit) return;
    const timer = setTimeout(() => void save(), 3500);
    return () => clearTimeout(timer);
  }, [content, state, save, busy, canEdit]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (revision.current !== acknowledged.current) e.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);

  const finalize = async () => {
    if (busyRef.current || !canEdit || stateRef.current === 'conflict') return;
    const current = contentRef.current;
    if (!current.text.trim() && !sections.some(([key]) => current[key].some(x => x.text.trim()))) {
      setError(new Error('Add a note or a structured entry before finalizing.'));
      return;
    }
    busyRef.current = true;
    setBusy(true);
    try {
      // First wait for an in-flight autosave; then save any newer edits as well.
      await save();
      if (revision.current !== acknowledged.current) await save();
      if (revision.current !== acknowledged.current) return;
      if (!window.confirm('Finalize this version? It will become read-only.')) return;
      const final = await post<Session>(`${path}/finalize`, { expectedVersion: versionRef.current });
      sessionRef.current = final;
      versionRef.current = final.version;
      setSession(final);
      setSaveState('saved');
      router.refresh();
    } catch (e) { setError(e as Error); }
    finally { busyRef.current = false; setBusy(false); }
  };

  const amend = async () => {
    if (busyRef.current || !reason.trim() || !session.allowedActions.includes('amend')) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const draft = await post<Session>(`${path}/amendments`, { reason: reason.trim(), expectedVersion: session.version });
      router.push(`${patientPath(patientId)}/sessions/${encodeURIComponent(draft.id)}`);
      router.refresh();
    } catch (e) { setError(e as Error); }
    finally { busyRef.current = false; setBusy(false); }
  };
  const updateField = (key: typeof sections[number][0], i: number, field: keyof NoteField, value: string) => { const items = [...content[key]]; items[i] = { ...items[i], [field]: value }; change({ ...content, [key]: items }); };
  return <div className="editor-layout">
    <div>
      <Panel title={session.state==='draft'?'Session draft':'Finalized note'} icon="notes" action={<Badge>{session.state}</Badge>}>
        <Message error={error}/>{session.amendmentReason&&<div className="notice">Amendment reason: {session.amendmentReason}</div>}
        {state==='conflict'&&<div className="notice warning" role="alert"><strong>Another version was saved.</strong> Your text is still here. Compare it with the server copy before retrying.{latest&&<details className="compact-details"><summary>View latest saved text · v{latest.version}</summary><pre className="json-details">{latest.text}</pre>{latest.state==='draft'&&latest.allowedActions.includes('edit')?<button className="button" onClick={()=>{versionRef.current=latest.version;sessionRef.current=latest;setSession(latest);setSaveState('unsaved');setLatest(null);}}>Retry with my edits</button>:<p>This server version is read-only. Copy your unsaved text before leaving this page.</p>}</details>}</div>}
        {canEdit?<fieldset disabled={busy} style={{border:0,padding:0,margin:0,minWidth:0}}><div className="stack">
          <div className="fields"><Field label="Session date"><input type="date" value={content.eventDate||''} onChange={e=>change({...content,eventDate:e.target.value||null})}/></Field></div>
          <Field label="What happened in this session?"><textarea className="note-textarea" placeholder="Write the session note here…" value={content.text} onChange={e=>change({...content,text:e.target.value})}/></Field>
          <div className="inline-note">Structured details are optional. Add them when you need to make assertion or time explicit.</div>
          <div className="structured-list">{sections.map(([key,label])=><details key={key} className="structured-section"><summary><span>{label}</span><span className="section-count">{content[key].length||'Optional'}</span></summary><div className="structured-body"><button type="button" className="button small-button" onClick={()=>change({...content,[key]:[...content[key],{text:'',assertion:'unknown',temporality:'unknown'}]})}>+ Add detail</button>{content[key].map((item,i)=><div className="muted-box" key={i} style={{marginTop:10}}><div className="fields"><Field label="Description"><input value={item.text} onChange={e=>updateField(key,i,'text',e.target.value)}/></Field><Field label="Assertion"><select value={item.assertion} onChange={e=>updateField(key,i,'assertion',e.target.value as Assertion)}><option value="unknown">Unknown</option><option value="present">Present</option><option value="denied">Denied</option><option value="possible">Possible</option></select></Field><Field label="Time"><select value={item.temporality} onChange={e=>updateField(key,i,'temporality',e.target.value as Temporality)}><option value="unknown">Unknown</option><option value="current">Current</option><option value="historical">Historical</option></select></Field></div><button type="button" className="button ghost small-button" onClick={()=>change({...content,[key]:content[key].filter((_,index)=>index!==i)})}>Remove</button></div>)}</div></details>)}</div>
        </div></fieldset>:<><div className="read-only-note">{session.text||'No free text'}</div>{sections.map(([key,label])=>session[key]?.length?<details className="structured-section" key={key}><summary>{label} · {session[key].length}</summary>{session[key].map((x,i)=><p key={i}>{x.text} · <Badge>{x.assertion}</Badge> · {x.temporality}</p>)}</details>:null)}</>}
      </Panel>
      {session.versions?.length?<Panel title="Earlier versions" icon="clock">{session.versions.map(v=><div className="list-item" key={v.id}><strong>Version {v.version}</strong> · {v.author||'Unknown author'} · <TimeText date={v.updatedAt}/>{v.amendmentReason&&<p>Reason: {v.amendmentReason}</p>}<details className="compact-details"><summary>Read version</summary><pre className="json-details">{v.text}</pre>{sections.map(([key,label])=>v[key]?.length?<div key={key}><strong>{label}</strong>{v[key].map((entry,index)=><p key={index}>{entry.text} · {entry.assertion} · {entry.temporality}</p>)}</div>:null)}</details></div>)}</Panel>:null}
    </div>
    <div className="editor-sidebar"><Panel title={canEdit?'Save & finalize':'Version details'} icon="check"><div className="editor-meta"><span>Session date</span><strong><DateText date={session.eventDate}/></strong></div><div className="editor-meta"><span>Author</span><strong>{session.author||'Current practitioner'}</strong></div><div className="editor-meta"><span>Version</span><strong>{session.version}</strong></div>
      {canEdit?<><div className={`notice ${state==='saved'?'success':state==='conflict'?'danger':'warning'}`} role="status">{state==='saved'?`Saved ${savedAt?new Date(savedAt).toLocaleTimeString('en-GB'):''}`:state==='saving'?'Saving…':state==='unsaved'?'Unsaved changes':state==='conflict'?'Conflict · edits preserved':'Save not confirmed · retry'}</div><div className="stack"><button className="button" disabled={state==='saving'||busy||state==='conflict'||revision.current===acknowledged.current} onClick={()=>void save()}>Save draft</button><button className="button primary" disabled={busy||state==='conflict'} onClick={()=>void finalize()}>Finalize note</button></div><p className="small muted" style={{marginTop:13}}>Finalized versions become read-only.</p></>:<><div className="notice success">{session.state==='finalized'?'This version is read-only.':'This draft requires its author and an active patient to edit.'}</div><details className="compact-details"><summary>Need to amend it?</summary><div className="stack" style={{marginTop:13}}><Field label="Reason for amendment"><textarea value={reason} onChange={e=>setReason(e.target.value)} placeholder="Why is a new version needed?"/></Field><button className="button" disabled={busy||!reason.trim()||!session.allowedActions?.includes('amend')} onClick={()=>void amend()}>Create amendment</button></div></details></>}
    </Panel></div>
  </div>;
}
