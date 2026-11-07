'use client';
import MedicationsPanel from '@/components/medications-panel';
import ConcernsPanel from '@/components/concerns-panel';
import RatingsPanel from '@/components/ratings-panel';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { useAuth } from '@/lib/auth';
import { Require } from '@/components/shell';
import { Badge, EvidenceLinks, Message, Panel, State, TimeText, SectionHeader } from '@/components/ui';
import { api, patientPath, post } from '@/lib/api';
import { useAction, useResource } from '@/lib/hooks';
import type { Indicator } from '@/lib/types';
type Result=Indicator&{ruleId?:string;version:number;evaluationId:string;reviewComment?:string;reviewedBy?:string;reviewedAt?:string};
type Results={items:Result[];allowedActions:string[];evaluationId:string|null};
const outcomes={matched:'Overdue',not_matched:'Not overdue',not_evaluable:'Cannot determine'};
const ratingOutcomes={matched:'Increase threshold met',not_matched:'Below increase threshold',not_evaluable:'Cannot determine'};
export default function IndicatorsPage(){
 const id=useParams<{patientId:string}>().patientId;const base=`${patientPath(id)}/indicators`;
 const {data,loading,error,reload,setData}=useResource<Results>(base);
 const history=useResource<{items:{id:string;evaluatedAt:string}[]}>(`${base}/history/runs`);
 const {has}=useAuth();const action=useAction();const [comments,setComments]=useState<Record<string,string>>({});const [notice,setNotice]=useState('');const [historical,setHistorical]=useState(false);
 const evaluate=async()=>{const updated=await action.run(()=>post<Results>(base+'/evaluate',{}));if(updated){setData(updated);setHistorical(false);setNotice('Evaluation saved. Unchanged inputs reuse the same result.');void history.reload();}};
 const review=async(item:Result,decision:string)=>{const updated=await action.run(()=>post<Results>(`${base}/${item.id}/review`,{decision,comment:comments[item.id]||null,evaluationId:item.evaluationId,expectedVersion:item.version}));if(updated){setData(updated);setNotice('Your review was saved. The calculated result and task state are unchanged.');}};
 const openHistory=async(runId:string)=>{const updated=await action.run(()=>api<Results>(runId?`${base}/history/runs/${runId}`:base));if(updated){setData(updated);setHistorical(Boolean(runId));setNotice('');}};
 return <Require cap="clinical:read"><SectionHeader title="Indicators" description="Review patient indicators."/>
 <MedicationsPanel patientId={id} onChange={async()=>{setData(await api<Results>(base));setHistorical(false);}}/><ConcernsPanel patientId={id} onChange={async()=>{setData(await api<Results>(base));setHistorical(false);}}/><RatingsPanel patientId={id} onChange={async()=>{const updated=await api<Results>(base);setData(updated);setHistorical(false);}}/><Panel title="Evaluate documented inputs" icon="indicator" action={has('indicators:write')&&!historical&&data?.allowedActions?.includes('evaluate')?<button className="button primary" disabled={action.pending} onClick={()=>void evaluate()}>Evaluate now</button>:undefined}>
 <p>An open task is overdue only when its due date is before today in the clinic timezone. A task due today is not overdue. An open task without a due date cannot be evaluated.</p>
 <p className="small muted">Results use the published rule settings shown below. Open a source note to review or correct the recorded information.</p>
 {history.data?.items.length? <label className="field"><span>View an evaluation</span><select className="control" disabled={action.pending} value={historical?data?.evaluationId||'':''} onChange={e=>void openHistory(e.target.value)}><option value="">Latest evaluation</option>{history.data.items.map(run=><option key={run.id} value={run.id}>{new Date(run.evaluatedAt).toLocaleString('en-GB')}</option>)}</select></label>:null}
 <Message error={action.error||history.error} success={notice}/>{action.error&&<button className="button" disabled={action.pending} onClick={()=>void openHistory('')}>Refresh latest evaluation</button>}
 </Panel>
 {historical&&<p className="notice warning">Viewing a saved evaluation. Its original results and review decisions are read-only.</p>}
 <State loading={loading} error={error} retry={()=>void reload()} empty={!data?.items.length} emptyMessage="Choose Evaluate now to check confirmed ratings and recorded follow-up tasks."><div className="grid">{data?.items.map(item=><Panel key={item.id} title={item.name} action={<div className="row"><Badge>{!item.enabled?'Disabled':item.ruleId==='missing-documentation'?({matched:'Information missing',not_matched:'Required fields recorded',not_evaluable:'Cannot determine'}[item.outcome]):item.ruleId==='medication-change'?({matched:'Change documented',not_matched:'No change in window',not_evaluable:'Cannot determine'}[item.outcome]):item.ruleId==='repeated-concern'?({matched:'Repetition threshold met',not_matched:'Below repetition threshold',not_evaluable:'Cannot determine'}[item.outcome]):item.ruleId==='difficulty-scale'?ratingOutcomes[item.outcome]:outcomes[item.outcome]}</Badge><Badge>{item.freshness}</Badge></div>}>
 <p>{item.explanation}</p>{item.freshness==='stale'&&<p className="notice warning">The inputs, rule settings or clinic date changed. Run a new evaluation before reviewing this result.</p>}
 <p className="small muted">Rule version {item.ruleVersion} · Evaluated <TimeText date={item.evaluatedAt}/></p>
 {item.conditions.map((c,i)=><div className="list-item row between" key={i}><span>{c.label}</span><strong>{c.value}</strong></div>)}<EvidenceLinks items={item.evidence}/>
 <div style={{marginTop:16}}><Badge>{item.reviewState||'unreviewed'}</Badge>{item.reviewedBy&&<p className="small muted">Reviewed by {item.reviewedBy} · <TimeText date={item.reviewedAt}/></p>}{item.reviewComment&&<p>{item.reviewComment}</p>}
 {has('indicators:write')&&item.allowedActions.includes('review')&&<><p className="small muted">Acknowledge means you have seen the result. Dismiss records that you do not need to act on this reminder. Neither button completes the follow-up task.</p><label className="field"><span>Review comment (optional)</span><input disabled={action.pending} maxLength={2000} value={comments[item.id]||''} onChange={e=>setComments({...comments,[item.id]:e.target.value})}/></label><div className="row" style={{marginTop:12}}><button className="button" disabled={action.pending} onClick={()=>void review(item,'acknowledge')}>Acknowledge</button><button className="button" disabled={action.pending} onClick={()=>void review(item,'dismiss')}>Dismiss reminder</button></div></>}
 </div></Panel>)}</div></State>{error&&<button className="button" onClick={()=>void reload()}>Try again</button>}
 </Require>;
}
