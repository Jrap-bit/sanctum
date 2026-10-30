'use client';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Require } from '@/components/shell';
import { SectionHeader, Panel, Message, WorkflowSteps } from '@/components/ui';
import { Icon } from '@/components/icon';
import { post, patientPath } from '@/lib/api';
import { useAction } from '@/lib/hooks';
import type { Session } from '@/lib/types';
export default function NewSession(){const id=useParams<{patientId:string}>().patientId;const router=useRouter();const action=useAction();const [date,setDate]=useState(new Date().toISOString().slice(0,10));const create=async()=>{const result=await action.run(()=>post<Session>(`${patientPath(id)}/sessions`,{eventDate:date}));if(result)router.replace(`${patientPath(id)}/sessions/${encodeURIComponent(result.id)}`);};return <Require cap="clinical:write"><SectionHeader title="Start a note" description="Choose the date, then write at your own pace."/><WorkflowSteps steps={['Choose date','Write note','Review & finalize']} current={0}/><div className="grid"><Panel title="When did this session happen?" icon="calendar"><div className="stack" style={{maxWidth:460}}><Message error={action.error}/><label className="field"><span>Session date</span><input type="date" value={date} onChange={e=>setDate(e.target.value)} required/></label><button className="button primary" disabled={action.pending} onClick={()=>void create()}>{action.pending?'Creating draft…':'Continue to editor'} <Icon name="arrow" size={16}/></button></div></Panel><div className="focus-card"><Icon name="notes" size={25}/><h2 style={{margin:'14px 0 5px'}}>Your draft stays editable</h2><p>Save it as you work. Finalize when the note is ready for the patient timeline.</p></div></div></Require>;}
