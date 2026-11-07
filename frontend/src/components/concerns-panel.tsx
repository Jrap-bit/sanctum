'use client';
import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { api, patientPath, post } from '@/lib/api';
import { useAction, useResource } from '@/lib/hooks';
import { Badge, ConfirmAction, Field, Message, Panel, State } from '@/components/ui';
type Concern={id:string;version:number;concernCode:string;assertion:string;temporality:string;subject:string;quotation:string;state:string;freshness:string;eventDate:string|null;dateStatus:string;href:string;withdrawalReason?:string};
type ConcernList={items:Concern[];allowedActions:string[]};
type Source={id:string;version:number;title:string;eventDate:string|null;dateStatus:string;href:string};
export default function ConcernsPanel({patientId,onChange}:{patientId:string;onChange:()=>Promise<void>}){
 const base=`${patientPath(patientId)}/concerns`;const resource=useResource<ConcernList>(base);const sources=useResource<{items:Source[]}>(`${base}/sources`);const action=useAction();
 const [sourceId,setSourceId]=useState('');const [concernCode,setConcernCode]=useState('sleep_difficulty');const [assertion,setAssertion]=useState('unknown');const [temporality,setTemporality]=useState('unknown');const [subject,setSubject]=useState('unknown');const [quotation,setQuotation]=useState('');const [confirmed,setConfirmed]=useState(false);const [notice,setNotice]=useState('');
 const source=sources.data?.items.find(s=>s.id===sourceId);
 const refresh=async()=>{resource.setData(await api<ConcernList>(base));await onChange();};
 const save=async(e:FormEvent)=>{e.preventDefault();if(!source)return;const result=await action.run(async()=>{await post(base,{sourceId,sourceVersion:source.version,concernCode,assertion,temporality,subject,quotation,confirmed});await refresh();return true;});if(result){setNotice('Confirmed concern saved. Evaluate now to update the indicators.');setQuotation('');setConfirmed(false);}};
 return <Panel title="Confirmed concerns" icon="notes"><p>Confirm what the source note says about a concern. Use the same category across sessions.</p>
 {resource.data?.allowedActions.includes('create')&&<details><summary>Add a concern from a session note</summary><form className="stack" style={{marginTop:16}} onSubmit={save}>
 <Field label="Source session"><select required disabled={action.pending} value={sourceId} onChange={e=>{setSourceId(e.target.value);setConfirmed(false);}}><option value="">Select a finalized note</option>{sources.data?.items.map(s=><option key={s.id} value={s.id}>{s.eventDate||'Undated'} · {s.title} · v{s.version} · {s.id.slice(0,8)}</option>)}</select></Field>
 {source&&<p><Link href={source.href} target="_blank" rel="noreferrer">Read source note ↗</Link> · Date: {source.eventDate||'Unknown'} ({source.dateStatus})</p>}
 {([
 ['Concern category',concernCode,setConcernCode,{sleep_difficulty:'Sleep difficulty',anxiety:'Anxiety',low_mood:'Low mood',concentration_difficulty:'Concentration difficulty',fatigue:'Fatigue',irritability:'Irritability',social_avoidance:'Social avoidance',work_stress:'Work-related stress'}],
 ['What does the note say?',assertion,setAssertion,{present:'Reported or observed',denied:'Explicitly denied',possible:'Possible / uncertain',unknown:'Not specified'}],
 ['When did it apply?',temporality,setTemporality,{current:'At that session',historical:'Earlier history',unknown:'Not specified'}],
 ['Who is it about?',subject,setSubject,{patient:'The patient',other:'Someone else',unknown:'Not specified'}]
 ] as const).map(([title,value,setter,options])=><Field key={title} label={title}><select disabled={action.pending} value={value} onChange={e=>{setter(e.target.value);setConfirmed(false);}}>{Object.entries(options).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></Field>)}
 <Field label="Supporting quotation" hint="Copy the relevant words from the source note."><textarea required minLength={3} maxLength={2000} disabled={action.pending} value={quotation} onChange={e=>{setQuotation(e.target.value);setConfirmed(false);}}/></Field>
 <label className="checkbox"><input type="checkbox" required disabled={action.pending} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I checked the source note: the category, timing, person and reported/denied status match the quoted text.</label>
 <button className="button primary" disabled={action.pending||!confirmed||!source||!quotation.trim()}>Save confirmed concern</button>
 </form></details>}
 <Message error={action.error||sources.error} success={notice}/><State loading={resource.loading} error={resource.error} empty={!resource.data?.items.length} emptyMessage="No confirmed concerns yet.">{resource.data?.items.map(r=><div className="list-item" key={r.id}><div className="row"><strong>{r.concernCode.replaceAll('_',' ')}</strong><Badge>{r.state}</Badge><Badge>{r.freshness}</Badge></div><p className="small muted">{r.eventDate||'Undated'} · {r.dateStatus} · {{present:'Reported or observed',denied:'Explicitly denied',possible:'Possible / uncertain',unknown:'Not specified'}[r.assertion]} · {{current:'At that session',historical:'Earlier history',unknown:'Time not specified'}[r.temporality]} · {{patient:'The patient',other:'Someone else',unknown:'Person not specified'}[r.subject]}</p><blockquote>{r.quotation}</blockquote><Link href={r.href}>Source note ↗</Link>{r.withdrawalReason&&<p>Withdrawal reason: {r.withdrawalReason}</p>}{r.state==='confirmed'&&resource.data?.allowedActions.includes('withdraw')&&<div style={{marginTop:10}}><ConfirmAction label="Withdraw incorrect concern" consequence="This retains the original concern but excludes it from future evaluations. You can then record a corrected replacement." requireReason busy={action.pending} onConfirm={reason=>void action.run(async()=>{await post(`${base}/${r.id}/withdraw`,{expectedVersion:r.version,reason});await refresh();setNotice('Concern withdrawn. Previous evaluations are retained and marked stale.');})}/></div>}</div>)}</State>
 </Panel>;
}
