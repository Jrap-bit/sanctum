'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { Require } from '@/components/shell';
import { Badge, DateText, Message, Panel, State, WorkflowSteps, SectionHeader } from '@/components/ui';
import { api, patientPath, post } from '@/lib/api';
import { useAction, useResource } from '@/lib/hooks';
import type { Job, Source, Summary } from '@/lib/types';
type AIStatus={state:string;model:string;maxSources:number;maxWords:number;maxSourceBytes:number};
export default function NewSummary() {
  const id=useParams<{patientId:string}>().patientId;const base=`${patientPath(id)}/summaries`;
  const sources=useResource<{items:Source[]}>(`${base}/eligible-sources`);
  const health=useResource<AIStatus>('/ai/status');const past=useResource<{items:Summary[]}>(base);
  const jobs=useResource<{items:Job[]}>(`${base}/generation-jobs`);const action=useAction();
  const [kind,setKind]=useState<'single_session'|'longitudinal'>('single_session');
  const [selected,setSelected]=useState<string[]>([]);const [job,setJob]=useState<Job|null>(null);
  const [jobError,setJobError]=useState<Error|null>(null);const requestKey=useRef<string|null>(null);
  const active=Boolean(job&&['queued','running'].includes(job.state));
  useEffect(()=>{if(!job){const pending=jobs.data?.items.find(j=>['queued','running'].includes(j.state));if(pending)setJob(pending);}},[jobs.data,job]);
  useEffect(()=>{
    if(!job||!['queued','running'].includes(job.state))return;
    let live=true;
    const timer=window.setInterval(()=>{void api<Job>(`/jobs/${job.id}`).then(updated=>{if(live){setJob(updated);setJobError(null);if(updated.state==='completed')void past.reload();}}).catch(e=>{if(live)setJobError(e as Error);});},2500);
    return()=>{live=false;window.clearInterval(timer);};
  },[job?.id,job?.state,past.reload]);
  const chosen=sources.data?.items.filter(s=>selected.includes(s.id))||[];
  const words=chosen.reduce((sum,s)=>sum+(s.wordCount||0),0);const bytes=chosen.reduce((sum,s)=>sum+(s.byteCount||0),0);
  const tooMany=chosen.length>(health.data?.maxSources||30)||words>(health.data?.maxWords||2000)||bytes>(health.data?.maxSourceBytes||8000);
  const generate=async()=>{
    if(active)return;
    requestKey.current ||= crypto.randomUUID();
    const result=await action.run(()=>post<Job>(base,{kind,requestKey:requestKey.current,sourceVersions:chosen.map(s=>({id:s.id,version:s.version,type:s.type}))}));
    if(result){setJob(result);setJobError(null);requestKey.current=null;}
  };
  const updateJob=async(operation:string)=>{if(!job)return;const result=await action.run(()=>post<Job>(`/jobs/${job.id}/${operation}`,{}));if(result)setJob(result);};
  return <Require cap="summaries:write"><SectionHeader title="New AI summary" description="Choose finalized source records for a local AI draft."/>
    <WorkflowSteps steps={['Choose sources','Generate draft','Review & accept']} current={active?1:0}/>
    <Panel title="What are you making?" icon="sparkle"><div className="inline-note">AI output needs clinician review. Suggested facts are reviewed separately.</div>
      <p>Local model: {health.data?.model||'Checking…'} <button className="button small-button" onClick={()=>void health.reload()}>Check model</button></p>
      {health.data?.state!=='healthy'&&<div className="notice warning">Generation is unavailable. Start Ollama and ensure the configured model is installed, then check again.</div>}
      <Message error={health.error}/>
      <div className="row"><label className="pill-choice"><input type="radio" disabled={active||action.pending} checked={kind==='single_session'} onChange={()=>{setKind('single_session');requestKey.current=null;}}/>One session</label><label className="pill-choice"><input type="radio" disabled={active||action.pending} checked={kind==='longitudinal'} onChange={()=>{setKind('longitudinal');requestKey.current=null;}}/>Across sessions</label></div>
      <p className="muted">{kind==='single_session'?'One session: a short summary of one finalized note. Example: what happened during Alex’s appointment today.':'Across sessions: a combined overview of the notes you select. Example: changes in Alex’s concerns, progress and treatment over several appointments.'}</p>
    </Panel>
    <Panel title="Choose sources" icon="notes"><State loading={sources.loading} error={sources.error} empty={!sources.data?.items.length} emptyMessage="Finalize a note or confirm reviewed document history before generating a summary.">{sources.data?.items.map(s=><label className="pill-choice" key={s.id}><input type="checkbox" disabled={active||action.pending} checked={selected.includes(s.id)} onChange={e=>{setSelected(e.target.checked?[...selected,s.id]:selected.filter(x=>x!==s.id));requestKey.current=null;}}/><span><strong>{s.title}</strong><br/><small>{s.dateStatus==='approximate'?'Approximately ':''}<DateText date={s.eventDate}/> · version {s.version} · {s.wordCount||0} words</small></span></label>)}</State>
      <p className="small muted">Selected: {chosen.length} sources · {words} words. Limit: {health.data?.maxSources||30} sources, {health.data?.maxWords||2000} words and {health.data?.maxSourceBytes||8000} bytes of source text. Oversized selections are rejected without truncation.</p>
      {tooMany&&<p className="notice danger">Choose fewer or shorter sources.</p>}<Message error={action.error||jobError}/>
      <div className="row"><button className="button primary" disabled={action.pending||active||!chosen.length||tooMany||(kind==='single_session'&&chosen.length!==1)||health.data?.state!=='healthy'} onClick={()=>void generate()}>Generate draft</button><button className="button" disabled={active||action.pending} onClick={()=>void sources.reload()}>Refresh sources</button></div>
    </Panel>
    {job&&<Panel title="Draft progress" icon="activity"><Badge>{job.state}</Badge><p>{job.message||'Processing the selected records locally. Keep the AI worker running.'}</p>
      {job.resultId&&<Link className="button primary" href={`${base}/${encodeURIComponent(job.resultId)}`}>Review draft</Link>}
      {active&&<button className="button" disabled={action.pending} onClick={()=>void updateJob('cancel')}>Cancel generation</button>}
      {['failed','cancelled'].includes(job.state)&&<button className="button" disabled={action.pending} onClick={()=>void updateJob('retry')}>Retry generation</button>}
    </Panel>}
    <Panel title="Previous summaries" icon="notes"><State loading={past.loading} error={past.error} empty={!past.data?.items.length}>{past.data?.items.map(s=><p key={s.id}><Link href={`${base}/${s.id}`}>{s.kind==='single_session'?'One-session summary':'Summary across sessions'} · {new Date(s.generatedAt).toLocaleString('en-GB',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'})}</Link> <Badge>{s.reviewState}</Badge> <Badge>{s.freshness}</Badge></p>)}</State></Panel>
  </Require>;
}
