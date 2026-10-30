'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@/lib/auth';
import { useResource } from '@/lib/hooks';
import { patientPath } from '@/lib/api';
import type { Capability, Patient } from '@/lib/types';
import { Icon, type IconName } from './icon';
import { State } from './ui';

type Workflow = { id: string; label: string; description: string; icon: IconName; cap: Capability; path: string };
const clinicalWorkflows: Workflow[] = [
  { id: 'session', label: 'New session', description: 'Write & finalize a note', icon: 'notes', cap: 'clinical:write', path: '/sessions/new' },
  { id: 'import', label: 'Import & OCR', description: 'Upload & review records', icon: 'upload', cap: 'documents:write', path: '/documents' },
  { id: 'summary', label: 'AI summary', description: 'Draft from reviewed sources', icon: 'sparkle', cap: 'summaries:write', path: '/summaries/new' },
  { id: 'indicators', label: 'Indicators', description: 'Review documented conditions', icon: 'indicator', cap: 'clinical:read', path: '/indicators' },
  { id: 'report', label: 'Build report', description: 'Preview & export a PDF', icon: 'report', cap: 'reports:write', path: '/reports/new' },
];
const administrativeWorkflows: Workflow[] = [
  { id: 'people', label: 'Manage accounts', description: 'People & permissions', icon: 'users', cap: 'users:manage', path: '/admin/users' },
  { id: 'assignments', label: 'Assign patients', description: 'Assignments & handovers', icon: 'handover', cap: 'assignments:manage', path: '/admin/assignments' },
  { id: 'access', label: 'Access requests', description: 'Request patient scope', icon: 'key', cap: 'grants:request', path: '/access/grants' },
  { id: 'operations', label: 'System health', description: 'Services, jobs & recovery', icon: 'activity', cap: 'operations:manage', path: '/admin/operations' },
];

export function WorkflowLauncher() {
  const { has } = useAuth();
  const clinical = has('clinical:read');
  const workflows = (clinical ? clinicalWorkflows : administrativeWorkflows).filter(workflow => has(workflow.cap));
  const [selected, setSelected] = useState<Workflow | null>(null);
  const [query, setQuery] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const patientSearch = useRef<HTMLInputElement>(null);
  const { data, error, loading, reload } = useResource<{ items: Patient[] }>(selected ? '/patients?status=active' : null);
  const search = query.trim().toLowerCase();
  const patients = (data?.items || []).filter(patient => patient.status === 'active'
    && patient.allowedActions.includes('clinical:read')
    && (patient.displayName.toLowerCase().includes(search) || patient.id.toLowerCase().includes(search)));
  const closePicker = () => {
    dialog.current?.close();
    setSelected(null);
    setQuery('');
  };

  useEffect(() => {
    if (selected && !dialog.current?.open) {
      dialog.current?.showModal();
      patientSearch.current?.focus();
    }
    if (!selected && dialog.current?.open) dialog.current.close();
  }, [selected]);

  if (!workflows.length) return null;

  return <section className="workflow-launcher" aria-labelledby="workflow-heading">
    <div className="workflow-heading"><h2 id="workflow-heading">{clinical ? 'Clinical workflows' : 'Clinic tools'}</h2>{clinical && <span>Select a tool, then a patient</span>}</div>
    <div className="workflow-tools">
      {workflows.map(workflow => {
        const content = <><span className="workflow-tool-top"><span className="workflow-tool-icon"><Icon name={workflow.icon} size={23}/></span><Icon name="arrow" className="workflow-tool-arrow" size={18}/></span><strong>{workflow.label}</strong><span className="workflow-tool-description">{workflow.description}</span></>;
        return clinical
          ? <button type="button" className={`workflow-tool workflow-${workflow.id}`} key={workflow.id} aria-haspopup="dialog" onClick={() => { setQuery(''); setSelected(workflow); }}>{content}</button>
          : <Link className={`workflow-tool workflow-${workflow.id}`} href={workflow.path} key={workflow.id}>{content}</Link>;
      })}
    </div>
    <dialog ref={dialog} className={`workflow-dialog workflow-${selected?.id || 'session'}`} aria-labelledby="workflow-dialog-title" aria-describedby="workflow-dialog-description" onClose={event => {
      if (!event.currentTarget.open) { setSelected(null); setQuery(''); }
    }} onCancel={event => { event.preventDefault(); closePicker(); }} onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); closePicker(); return; }
      if (event.key !== 'Tab') return;
      const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), a[href]')).filter(control => control.getClientRects().length);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }} onClick={event => {
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closePicker();
    }}>
      <div className="workflow-dialog-header"><div><span className="workflow-dialog-icon"><Icon name={selected?.icon || 'patient'} size={23}/></span><h2 id="workflow-dialog-title">{selected?.label || 'Choose a patient'}</h2></div><button type="button" className="workflow-dialog-close" aria-label="Close patient selection" onClick={closePicker}><Icon name="close" size={21}/></button></div>
      <p id="workflow-dialog-description">Choose an active patient to continue.</p>
      <div className="directory-search"><Icon name="search" size={19}/><input ref={patientSearch} type="search" aria-label="Find a patient for this workflow" placeholder="Patient name or record ID" value={query} onChange={event => setQuery(event.target.value)}/></div>
      <div className="workflow-patient-results">
        <State loading={loading || (!data && !error)} error={error} empty={!patients.length} emptyTitle={search ? 'No matching patients' : 'No active patients available'} emptyMessage={search ? 'Try another name or record ID.' : 'This workflow requires an active patient within your clinical scope.'}>
          <ul>{patients.map(patient => <li key={patient.id}><Link href={`${patientPath(patient.id)}${selected?.path || ''}`} onClick={closePicker}><span className="workflow-patient-avatar">{patient.displayName.charAt(0)}</span><span><strong>{patient.displayName}</strong><small>{patient.id}</small></span><Icon name="arrow" size={18}/></Link></li>)}</ul>
        </State>
        {error && <button type="button" className="button" onClick={() => void reload()}>Retry patient list</button>}
      </div>
    </dialog>
  </section>;
}
