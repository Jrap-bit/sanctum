'use client';
import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { api, patientPath, post } from '@/lib/api';
import { useAction, useResource } from '@/lib/hooks';
import { Badge, ConfirmAction, Field, Message, Panel, State } from '@/components/ui';
type Medication={id:string;version:number;medicationName:string;changeStatus:string;quotation:string;state:string;freshness:string;eventDate:string|null;dateStatus:string;href:string;withdrawalReason?:string};
type MedicationList={items:Medication[];allowedActions:string[]};
type Source={id:string;version:number;title:string;eventDate:string|null;dateStatus:string;href:string};
export default function MedicationsPanel({patientId,onChange}:{patientId:string;onChange:()=>Promise<void>}){
 const base=`${patientPath(patientId)}/medications`;const resource=useResource<MedicationList>(base);const sources=useResource<{items:Source[]}>(`${base}/sources`);const action=useAction();
 const [sourceId,setSourceId]=useState('');const [medicationName,setMedicationName]=useState('');const [changeStatus,setChangeStatus]=useState('uncertain');const [quotation,setQuotation]=useState('');const [confirmed,setConfirmed]=useState(false);const [notice,setNotice]=useState('');
 const source=sources.data?.items.find(s=>s.id===sourceId);
 const refresh=async()=>{resource.setData(await api<MedicationList>(base));await onChange();};
 const save=async(e:FormEvent)=>{e.preventDefault();if(!source)return;const result=await action.run(async()=>{await post(base,{sourceId,sourceVersion:source.version,medicationName,changeStatus,quotation,confirmed});await refresh();return true;});if(result){setNotice('Confirmed medication saved. Evaluate now to update the indicators.');setQuotation('');setConfirmed(false);}};
 return <Panel title="Confirmed medications" icon="notes"><p>Record medication changes documented for the patient at a session.</p>
 {resource.data?.allowedActions.includes('create')&&<details><summary>Add a medication from a session note</summary><form className="stack" style={{marginTop:16}} onSubmit={save}>
 <Field label="Source session"><select required disabled={action.pending} value={sourceId} onChange={e=>{setSourceId(e.target.value);setConfirmed(false);}}><option value="">Select a finalized note</option>{sources.data?.items.map(s=><option key={s.id} value={s.id}>{s.eventDate||'Undated'} · {s.title} · v{s.version} · {s.id.slice(0,8)}</option>)}</select></Field>
 {source&&<p><Link href={source.href} target="_blank" rel="noreferrer">Read source note ↗</Link> · Date: {source.eventDate||'Unknown'} ({source.dateStatus})</p>}
 <Field label="Medication name as documented"><input required maxLength={160} disabled={action.pending} value={medicationName} onChange={e=>{setMedicationName(e.target.value);setConfirmed(false);}}/></Field>
 <Field label="What does the note document?"><select disabled={action.pending} value={changeStatus} onChange={e=>{setChangeStatus(e.target.value);setConfirmed(false);}}><option value="uncertain">Uncertain / not specified</option><option value="changed">A change was documented</option><option value="no_change">Explicitly no change</option></select></Field>
 <Field label="Supporting quotation" hint="Copy the relevant words from the source note."><textarea required minLength={3} maxLength={2000} disabled={action.pending} value={quotation} onChange={e=>{setQuotation(e.target.value);setConfirmed(false);}}/></Field>
 <label className="checkbox"><input type="checkbox" required disabled={action.pending} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I checked the source note: this entry describes the patient's medication status at that session, not someone else's medication, an older event, or a proposed future change.</label>
 <button className="button primary" disabled={action.pending||!confirmed||!source||!quotation.trim()}>Save confirmed medication</button>
 </form></details>}
 <Message error={action.error||sources.error} success={notice}/><State loading={resource.loading} error={resource.error} empty={!resource.data?.items.length} emptyMessage="No confirmed medications yet.">{resource.data?.items.map(r=><div className="list-item" key={r.id}><div className="row"><strong>{r.medicationName}</strong><Badge>{r.state}</Badge><Badge>{r.freshness}</Badge></div><p className="small muted">{r.eventDate||'Undated'} · {r.dateStatus} · {{changed:'Change documented',no_change:'No change documented',uncertain:'Uncertain'}[r.changeStatus]}</p><blockquote>{r.quotation}</blockquote><Link href={r.href}>Source note ↗</Link>{r.withdrawalReason&&<p>Withdrawal reason: {r.withdrawalReason}</p>}{r.state==='confirmed'&&resource.data?.allowedActions.includes('withdraw')&&<div style={{marginTop:10}}><ConfirmAction label="Withdraw incorrect medication" consequence="This retains the original medication but excludes it from future evaluations. You can then record a corrected replacement." requireReason busy={action.pending} onConfirm={reason=>void action.run(async()=>{await post(`${base}/${r.id}/withdraw`,{expectedVersion:r.version,reason});await refresh();setNotice('Medication withdrawn. Previous evaluations are retained and marked stale.');})}/></div>}</div>)}</State>
 </Panel>;
}
