'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Require } from '@/components/shell';
import { Badge, DateText, Message, Panel, State, WorkflowSteps, SectionHeader } from '@/components/ui';
import { api, patientPath, post } from '@/lib/api';
import { useAction, useResource } from '@/lib/hooks';
import type { Health, Job, Source } from '@/lib/types';

export default function NewSummary() {
  const id = useParams<{patientId: string}>().patientId;
  const base = `${patientPath(id)}/summaries`;
  const sources = useResource<{items: Source[]}>(`${base}/eligible-sources`);
  const health = useResource<Health>('/health');
  const action = useAction();
  const [kind, setKind] = useState<'single_session' | 'longitudinal'>('single_session');
  const [selected, setSelected] = useState<string[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [jobError, setJobError] = useState<Error | null>(null);
  const [pollAttempt, setPollAttempt] = useState(0);
  const processing = Boolean(job && ['queued', 'running'].includes(job.state));
  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.state)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const updated = await api<Job>(`/jobs/${encodeURIComponent(job.id)}`, {signal: controller.signal});
        if (controller.signal.aborted) return;
        setJobError(null); setJob(updated);
        if (['queued', 'running'].includes(updated.state)) timer = setTimeout(poll, 2500);
      } catch (failure) {if (!controller.signal.aborted) setJobError(failure as Error);}
    };
    timer = setTimeout(poll, 2500);
    return () => {controller.abort(); clearTimeout(timer);};
  }, [job?.id, job?.state, pollAttempt]);
  const chosen = sources.data?.items.filter(source => selected.includes(source.id)) || [];
  const words = chosen.reduce((sum, source) => sum + (source.wordCount || 0), 0);
  const tooMany = chosen.length > 30 || words > 30000;
  const locked = action.pending || processing;
  const generate = async () => {
    if (locked || tooMany || !chosen.length || (kind === 'single_session' && chosen.length !== 1) || health.data?.llm !== 'healthy') return;
    setJobError(null);
    const result = await action.run(() => post<Job>(base, {kind, sourceVersions: chosen.map(source => ({id: source.id, version: source.version, type: source.type}))}));
    if (result) setJob(result);
  };
  const cancel = async () => {
    if (!job) return;
    const result = await action.run(() => post(`/jobs/${encodeURIComponent(job.id)}/cancel`, {}));
    if (result !== undefined) {setJob({...job, state: 'cancelled'}); setJobError(null);}
  };
  return <Require cap="summaries:write">
    <SectionHeader title="New AI summary" description="Choose the exact records to summarize."/>
    <WorkflowSteps steps={['Choose sources', 'Generate draft', 'Review & accept']} current={job ? job.state === 'completed' ? 2 : 1 : 0}/>
    <Panel title="What are you making?" icon="sparkle">
      <div className="inline-note">AI output is a draft. You will review it before it can be used.</div>
      {health.loading ? <p role="status">Checking generation availability…</p> : health.data?.llm !== 'healthy' && <div className="notice warning">{health.data?.llm ? 'The local LLM is unavailable.' : 'The server has not reported LLM availability.'} Generation is paused. Manual notes remain available.</div>}
      <fieldset className="choice-group" disabled={locked}><legend className="sr-only">Summary type</legend>
        <label className="pill-choice"><input type="radio" name="kind" checked={kind === 'single_session'} onChange={() => setKind('single_session')}/> Single-session summary</label>
        <label className="pill-choice"><input type="radio" name="kind" checked={kind === 'longitudinal'} onChange={() => setKind('longitudinal')}/> Longitudinal briefing</label>
      </fieldset>
    </Panel>
    <Panel title="Choose sources" icon="notes">
      <State loading={sources.loading} error={sources.error} retry={() => void sources.reload()} empty={!sources.data?.items.length} emptyTitle="No eligible sources" emptyMessage="Finalize a session note or confirm a transcription before requesting a summary.">
        {sources.data?.items.map(source => <label className="pill-choice" key={source.id}><input type="checkbox" disabled={locked} checked={selected.includes(source.id)} onChange={event => setSelected(event.target.checked ? [...selected, source.id] : selected.filter(value => value !== source.id))}/><span><strong>{source.title}</strong><br/><small><DateText date={source.eventDate}/> · {source.type} · Version {source.version} · {source.wordCount ?? 'Unknown'} words</small></span></label>)}
      </State>
      <p className="muted small">Selected: {chosen.length} sources · {words} words. Limit: 30 sources / 30,000 words.</p>
      {kind === 'single_session' && chosen.length > 1 && <p className="notice warning">Select exactly one source for a single-session summary, or choose Longitudinal briefing.</p>}
      {tooMany && <div className="notice danger" role="alert">Selection exceeds the limit. Reduce the source set.</div>}
      <Message error={action.error || jobError}/>
      <button className="button primary" disabled={locked || !chosen.length || tooMany || (kind === 'single_session' && chosen.length !== 1) || health.data?.llm !== 'healthy'} onClick={() => void generate()}>Generate draft</button>
    </Panel>
    {job && <Panel title="Draft progress" icon="activity"><div className="row" role="status"><Badge>{job.state}</Badge>{job.progress != null && <span>{job.progress}%</span>}</div><p className="muted small">{job.message || 'Processing selected source versions locally.'}</p>
      {job.resultId && job.state === 'completed' && <Link className="button primary" href={`${base}/${encodeURIComponent(job.resultId)}`}>Review draft</Link>}
      <div className="row">{processing && <button className="button" disabled={action.pending} onClick={() => void cancel()}>Cancel job</button>}
        {jobError && <button className="button" onClick={() => {setJobError(null); setPollAttempt(value => value + 1);}}>Retry status check</button>}
        {job.state === 'failed' && <button className="button" disabled={action.pending} onClick={() => void action.run(() => post<Job>(`/jobs/${encodeURIComponent(job.id)}/retry`, {})).then(value => {if (value) {setJobError(null); setJob(value);}})}>Retry generation</button>}
      </div>
    </Panel>}
  </Require>;
}
