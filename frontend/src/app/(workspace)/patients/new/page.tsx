'use client';
import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { post, patientPath } from '@/lib/api';
import { useAction, useResource } from '@/lib/hooks';
import { useAuth } from '@/lib/auth';
import { Require } from '@/components/shell';
import { Field, Message, PageHeader, Panel, WorkflowSteps } from '@/components/ui';
import type { Patient, User } from '@/lib/types';
import { Icon } from '@/components/icon';
export default function NewPatient(){
  const router=useRouter();const {user,has}=useAuth();const action=useAction();const [name,setName]=useState('');const [dob,setDob]=useState('');const [assignee,setAssignee]=useState('');
  const users=useResource<{items:User[]}>(has('users:manage')?'/admin/users':null);
  const chosen=assignee||(!has('users:manage')&&has('clinical:write')?user?.id:'');
  const submit=async(e:FormEvent)=>{e.preventDefault();if(dob&&dob>new Date().toISOString().slice(0,10)){action.setError(new Error('Birth date cannot be in the future.'));return;}const p=await action.run(()=>post<Patient>('/patients',{displayName:name.trim(),dateOfBirth:dob||null,initialPractitionerId:chosen}));if(p)router.push(patientPath(p.id));};
  return <Require cap="patients:create"><PageHeader title="Add a patient"/><WorkflowSteps steps={['Patient details','Care assignment','Ready']} current={1}/><div className="grid"><Panel title="Patient details" icon="patient"><form id="patient-form" onSubmit={submit} className="stack"><Message error={action.error}/><Field label="Display name"><input value={name} onChange={e=>setName(e.target.value)} required maxLength={160} placeholder="Name shown in the clinic"/></Field><Field label="Date of birth"><input type="date" max={new Date().toISOString().slice(0,10)} value={dob} onChange={e=>setDob(e.target.value)}/></Field><div className="inline-note"><Icon name="shield" size={17}/>Only add identity details here. Session notes belong in the patient workspace.</div></form></Panel><Panel title="Care assignment" icon="handover"><div className="stack">{has('users:manage')?<Field label="First practitioner"><select required form="patient-form" value={assignee} onChange={e=>setAssignee(e.target.value)}><option value="">Choose a practitioner</option>{users.data?.items.filter(u=>u.capabilities.includes('clinical:write')).map(u=><option value={u.id} key={u.id}>{u.displayName}</option>)}</select></Field>:<div className="focus-card"><strong>Assigned to you</strong><p>You can begin documenting after the record is created.</p></div>}<div className="inline-note"><Icon name="key" size={17}/>Patient access can be changed later through Assignments.</div><button form="patient-form" className="button primary" disabled={action.pending||!name.trim()||!chosen}>{action.pending?'Creating…':'Create patient'} <Icon name="arrow" size={16}/></button></div></Panel></div></Require>;
}
