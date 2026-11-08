'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { Require } from '@/components/shell';
import { Badge, DateText, Field, Message, Panel, State, WorkflowSteps, SectionHeader } from '@/components/ui';
import { JobProgress } from '@/components/job-progress';
import { api, patientPath, post } from '@/lib/api';
import { useAction, useResource } from '@/lib/hooks';
import type { Job, Source, Summary } from '@/lib/types';
import { useJobStream, type JobEvent } from '@/lib/ws';
type AIStatus={state:string;model:string;maxSources:number;maxWords:number;maxSourceBytes:number};
type ModelItem = { id: string; available: boolean; digest?: string | null };
type ModelsResponse = { default: string; items: ModelItem[] };
export default function NewSummary() {
  const id=useParams<{patientId:string}>().patientId;const base=`${patientPath(id)}/summaries`;
  const sources=useResource<{items:Source[]}>(`${base}/eligible-sources`);
  const health=useResource<AIStatus>('/ai/status');const past=useResource<{items:Summary[]}>(base);
  const models=useResource<ModelsResponse>('/models');
  const jobs=useResource<{items:Job[]}>(`${base}/generation-jobs`);const action=useAction();
  const [kind,setKind]=useState<'single_session'|'longitudinal'>('single_session');
  const [selected,setSelected]=useState<string[]>([]);const [job,setJob]=useState<Job|null>(null);
  const [selectedModel,setSelectedModel]=useState<string>('');
  const [jobError,setJobError]=useState<Error|null>(null);const requestKey=useRef<string|null>(null);
  const [pollAttempt,setPollAttempt]=useState(0);
  const active=Boolean(job&&['queued','running'].includes(job.state));
  const showPicker = !models.error && Boolean(models.data);
  const currentModel = selectedModel || models.data?.default || '';

  const finished = async (event: JobEvent) => {
    const targetId = event.jobId || job?.id;
    if (!targetId) return;
    try {
      const updated = await api<Job>(`/jobs/${encodeURIComponent(targetId)}`);
      setJob(updated);
      setJobError(null);
      void past.reload();
    } catch (err) {
      setJobError(err as Error);
    }
  };

  const { event, text, live } = useJobStream(job?.id ?? null, finished);

  useEffect(()=>{if(!job){const pending=jobs.data?.items.find(j=>['queued','running'].includes(j.state));if(pending)setJob(pending);}},[jobs.data,job]);
  useEffect(()=>{
    if(!job||!['queued','running'].includes(job.state)||live)return;
    const controller=new AbortController();
    let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try {
        const updated=await api<Job>(`/jobs/${encodeURIComponent(job.id)}`,{signal:controller.signal});
        if(controller.signal.aborted)return;
        setJob(updated);setJobError(null);
        if(updated.state==='completed')void past.reload();
        if(['queued','running'].includes(updated.state)&&!live)timer=setTimeout(poll,2500);
      } catch(error) {if(!controller.signal.aborted)setJobError(error as Error);}
    };
    timer=setTimeout(poll,2500);
    return()=>{controller.abort();clearTimeout(timer);};
  },[job?.id,job?.state,past.reload,pollAttempt,live]);
  const chosen=sources.data?.items.filter(s=>selected.includes(s.id))||[];
  const words=chosen.reduce((sum,s)=>sum+(s.wordCount||0),0);const bytes=chosen.reduce((sum,s)=>sum+(s.byteCount||0),0);
  const tooMany=chosen.length>(health.data?.maxSources||30)||words>(health.data?.maxWords||2000)||bytes>(health.data?.maxSourceBytes||8000);
  const generate=async()=>{
    if(active||action.pending||tooMany||!chosen.length||(kind==='single_session'&&chosen.length!==1)||health.data?.state!=='healthy')return;
    requestKey.current ||= crypto.randomUUID();
    const payload: {
      kind: 'single_session' | 'longitudinal';
      requestKey: string;
      sourceVersions: { id: string; version: number; type: string }[];
      model?: string;
    } = {
      kind,
      requestKey: requestKey.current,
      sourceVersions: chosen.map(s => ({ id: s.id, version: s.version, type: s.type })),
    };
    if (showPicker && currentModel) {
      payload.model = currentModel;
    }
    const result=await action.run(()=>post<Job>(base,payload));
    if(result){setJob(result);setJobError(null);requestKey.current=null;}
  };
  const updateJob=async(operation:string)=>{if(!job)return;const result=await action.run(()=>post<Job>(`/jobs/${encodeURIComponent(job.id)}/${operation}`,{}));if(result){setJob(result);setJobError(null);}};
  return <Require cap="summaries:write"><SectionHeader title="New AI summary" description="Choose finalized source records for a local AI draft."/>
    <WorkflowSteps steps={['Choose sources','Generate draft','Review & accept']} current={job?job.state==='completed'?2:1:0}/>
    <Panel title="What are you making?" icon="sparkle"><div className="inline-note">AI output needs clinician review. Suggested facts are reviewed separately.</div>
      <p>Local model: {currentModel || health.data?.model || 'Checking…'} <button className="button small-button" onClick={()=>void health.reload()}>Check model</button></p>
      {showPicker && (
        <Field label="Model">
          <select
            title="Model"
            disabled={active || action.pending}
            value={currentModel}
            onChange={e => setSelectedModel(e.target.value)}
          >
            {models.data?.items.map(m => (
              <option key={m.id} value={m.id} disabled={!m.available}>
                {m.id}{!m.available ? ' (not installed)' : ''}
              </option>
            ))}
          </select>
        </Field>
      )}
      {health.loading?<p role="status">Checking generation availability…</p>:health.data?.state!=='healthy'&&<div className="notice warning">{health.data?.state?'The local model is unavailable. Start Ollama and check the configured model.':'The server has not reported model availability.'} Generation is paused. Check again to retry.</div>}
      <Message error={health.error}/>
      <fieldset className="choice-group" disabled={active||action.pending}><legend className="sr-only">Summary type</legend><label className="pill-choice"><input name="kind" type="radio" disabled={active||action.pending} checked={kind==='single_session'} onChange={()=>{setKind('single_session');requestKey.current=null;}}/>One session</label><label className="pill-choice"><input name="kind" type="radio" disabled={active||action.pending} checked={kind==='longitudinal'} onChange={()=>{setKind('longitudinal');requestKey.current=null;}}/>Across sessions</label></fieldset>
      <p className="muted">{kind==='single_session'?'One session: a short summary of one finalized note. Example: what happened during Alex’s appointment today.':'Across sessions: a combined overview of the notes you select. Example: changes in Alex’s concerns, progress and treatment over several appointments.'}</p>
    </Panel>
    <Panel title="Choose sources" icon="notes"><State loading={sources.loading} error={sources.error} retry={()=>void sources.reload()} empty={!sources.data?.items.length} emptyMessage="Finalize a note or confirm reviewed document history before generating a summary.">{sources.data?.items.map(s=><label className="pill-choice" key={s.id}><input type="checkbox" disabled={active||action.pending} checked={selected.includes(s.id)} onChange={e=>{setSelected(e.target.checked?[...selected,s.id]:selected.filter(x=>x!==s.id));requestKey.current=null;}}/><span><strong>{s.title}</strong><br/><small>{s.dateStatus==='approximate'?'Approximately ':''}<DateText date={s.eventDate}/> · version {s.version} · {s.wordCount||0} words</small></span></label>)}</State>
      <p className="small muted">Selected: {chosen.length} sources · {words} words. Limit: {health.data?.maxSources||30} sources, {health.data?.maxWords||2000} words and {health.data?.maxSourceBytes||8000} bytes of source text. Oversized selections are rejected without truncation.</p>
      {kind==='single_session'&&chosen.length>1&&<p className="notice warning">Select exactly one source for one session, or choose Across sessions.</p>}{tooMany&&<p className="notice danger">Choose fewer or shorter sources.</p>}<Message error={action.error||jobError}/>
      <div className="row"><button className="button primary" disabled={action.pending||active||!chosen.length||tooMany||(kind==='single_session'&&chosen.length!==1)||health.data?.state!=='healthy'} onClick={()=>void generate()}>Generate draft</button><button className="button" disabled={active||action.pending} onClick={()=>void sources.reload()}>Refresh sources</button></div>
    </Panel>
    {job&&<Panel title="Draft progress" icon="activity"><Badge>{event?.state ?? job.state}</Badge>
      <JobProgress label="Draft progress" event={event} fallback={job.progress}/>
      <p>{job.message||'Processing the selected records locally. Keep the AI worker running.'}</p>
      {!['completed', 'failed', 'cancelled'].includes(job.state) && Boolean(text) && (
        <div style={{ marginTop: 12 }}>
          <strong>Live preview (not yet verified or saved)</strong>
          <p style={{ whiteSpace: 'pre-wrap' }}>{text}</p>
        </div>
      )}
      {job.resultId&&job.state==='completed'&&<Link className="button primary" href={`${base}/${encodeURIComponent(job.resultId)}`}>Review draft</Link>}
      {jobError&&<button className="button" onClick={()=>{setJobError(null);setPollAttempt(value=>value+1);}}>Retry status check</button>}
      {active&&<button className="button" disabled={action.pending} onClick={()=>void updateJob('cancel')}>Cancel generation</button>}
      {['failed','cancelled'].includes(job.state)&&<button className="button" disabled={action.pending} onClick={()=>void updateJob('retry')}>Retry generation</button>}
    </Panel>}
    <Panel title="Previous summaries" icon="notes"><State loading={past.loading} error={past.error} retry={()=>void past.reload()} empty={!past.data?.items.length}>{past.data?.items.map(s=><p key={s.id}><Link href={`${base}/${s.id}`}>{s.kind==='single_session'?'One-session summary':'Summary across sessions'} · {new Date(s.generatedAt).toLocaleString('en-GB',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'})}</Link> <Badge>{s.reviewState}</Badge> <Badge>{s.freshness}</Badge></p>)}</State></Panel>
  </Require>;
}
