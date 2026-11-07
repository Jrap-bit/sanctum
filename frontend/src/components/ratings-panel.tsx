'use client';
import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { api, patientPath, post } from '@/lib/api';
import { useAction, useResource } from '@/lib/hooks';
import { Badge, ConfirmAction, Field, Message, Panel, State } from '@/components/ui';
type Rating={id:string;version:number;scaleName:string;value:number;state:string;freshness:string;eventDate:string|null;dateStatus:string;higherMeans:string;href:string;withdrawalReason?:string};
type RatingList={items:Rating[];allowedActions:string[]};
type Source={id:string;version:number;title:string;eventDate:string|null;dateStatus:string;href:string};
export default function RatingsPanel({patientId,onChange}:{patientId:string;onChange:()=>Promise<void>}){
 const base=`${patientPath(patientId)}/ratings`;const resource=useResource<RatingList>(base);const sources=useResource<{items:Source[]}>(`${base}/sources`);const action=useAction();
 const [sourceId,setSourceId]=useState('');const [scaleName,setScaleName]=useState('');const [value,setValue]=useState('');const [direction,setDirection]=useState('unknown');const [confirmed,setConfirmed]=useState(false);const [notice,setNotice]=useState('');
 const source=sources.data?.items.find(s=>s.id===sourceId);
 const refresh=async()=>{resource.setData(await api<RatingList>(base));await onChange();};
 const save=async(e:FormEvent)=>{e.preventDefault();if(!source)return;const result=await action.run(async()=>{await post(base,{sourceId,sourceVersion:source.version,scaleName,value:Number(value),higherMeans:direction,confirmed});await refresh();return true;});if(result){setNotice('Confirmed rating saved. Evaluate now to update the indicators.');setValue('');setConfirmed(false);}};
 return <Panel title="Confirmed ratings" icon="notes"><p>Record a rating explicitly documented in a finalized note. The system does not guess values from AI summaries. Use the same scale name only when the notes describe the same measure.</p>
 {resource.data?.allowedActions.includes('create')&&<details><summary>Add a rating from a session note</summary><form className="stack" style={{marginTop:16}} onSubmit={save}>
 <Field label="Source session"><select required disabled={action.pending} value={sourceId} onChange={e=>{setSourceId(e.target.value);setConfirmed(false);}}><option value="">Select a finalized note</option>{sources.data?.items.map(s=><option key={s.id} value={s.id}>{s.eventDate||'Undated'} · {s.title} · v{s.version} · {s.id.slice(0,8)}</option>)}</select></Field>
 {source&&<p><Link href={source.href} target="_blank" rel="noreferrer">Read source note ↗</Link> · Date: {source.eventDate||'Unknown'} ({source.dateStatus})</p>}
 <Field label="Scale name as documented" hint="Example: Self-reported anxiety. Do not combine different questionnaires or scales."><input required maxLength={100} disabled={action.pending} value={scaleName} onChange={e=>{setScaleName(e.target.value);setConfirmed(false);}}/></Field>
 <Field label="Rating (0–10)"><input type="number" required min={0} max={10} step="any" disabled={action.pending} value={value} onChange={e=>{setValue(e.target.value);setConfirmed(false);}}/></Field>
 <Field label="What does a higher number mean?"><select disabled={action.pending} value={direction} onChange={e=>{setDirection(e.target.value);setConfirmed(false);}}><option value="unknown">Not specified / unsure</option><option value="more_difficulty">More difficulty</option><option value="less_difficulty">Less difficulty</option></select></Field>
 <label className="checkbox"><input type="checkbox" required disabled={action.pending} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I checked the source note: this is the patient's rating at that session, on this named 0–10 scale.</label>
 <button className="button primary" disabled={action.pending||!confirmed||!source||value===''}>Save confirmed rating</button>
 </form></details>}
 <Message error={action.error||sources.error} success={notice}/><State loading={resource.loading} error={resource.error} empty={!resource.data?.items.length} emptyMessage="No confirmed ratings yet.">{resource.data?.items.map(r=><div className="list-item" key={r.id}><div className="row"><strong>{r.scaleName}: {r.value}/10</strong><Badge>{r.state}</Badge><Badge>{r.freshness}</Badge></div><p className="small muted">{r.eventDate||'Undated'} · {r.dateStatus} · Higher means {r.higherMeans.replaceAll('_',' ')}</p><Link href={r.href}>Source note ↗</Link>{r.withdrawalReason&&<p>Withdrawal reason: {r.withdrawalReason}</p>}{r.state==='confirmed'&&resource.data?.allowedActions.includes('withdraw')&&<div style={{marginTop:10}}><ConfirmAction label="Withdraw incorrect rating" consequence="This retains the original rating but excludes it from future evaluations. You can then record a corrected replacement." requireReason busy={action.pending} onConfirm={reason=>void action.run(async()=>{await post(`${base}/${r.id}/withdraw`,{expectedVersion:r.version,reason});await refresh();setNotice('Rating withdrawn. Previous evaluations are retained and marked stale.');})}/></div>}</div>)}</State>
 </Panel>;
}
