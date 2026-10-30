'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useAuth } from '@/lib/auth';
import { useResource } from '@/lib/hooks';
import { patientPath } from '@/lib/api';
import type { Patient } from '@/lib/types';
import { Badge, PageHeader, State } from '@/components/ui';
import { Icon } from '@/components/icon';
import { WorkflowLauncher } from '@/components/workflow-launcher';

export default function PatientsPage() {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<'active' | 'archived'>('active');
  const { has } = useAuth();
  const { data, error, loading, reload } = useResource<{ items: Patient[] }>(`/patients?status=${status}`);
  const search = query.trim().toLowerCase();
  const patients = (data?.items || []).filter(patient => patient.displayName.toLowerCase().includes(search) || patient.id.toLowerCase().includes(search));

  return <>
    <PageHeader title="Patients" action={has('patients:create') && <Link className="button primary" href="/patients/new"><Icon name="plus" size={18}/>Add patient</Link>}/>
    <WorkflowLauncher/>
    <section className="panel patient-directory" aria-label="Patient directory">
      <div className="directory-toolbar">
        <div className="directory-search">
          <Icon name="search" size={20}/>
          <input type="search" aria-label="Search patient name or ID" placeholder="Search by name or record ID" value={query} onChange={event => setQuery(event.target.value)}/>
        </div>
        <select className="control" aria-label="Patient status" value={status} onChange={event => setStatus(event.target.value as 'active' | 'archived')}>
          <option value="active">Active patients</option><option value="archived">Archived patients</option>
        </select>
        <button className="button" onClick={() => void reload()} disabled={loading}>Refresh</button>
      </div>
      {!loading && !error && <p className="directory-count" aria-live="polite">{search ? `${patients.length} of ${data?.items.length || 0}` : patients.length} {patients.length === 1 && !search ? 'patient' : 'patients'}</p>}
      <State loading={loading} error={error} empty={!patients.length} emptyTitle={search ? 'No matching patients' : `No ${status} patients`} emptyMessage={search ? 'Try another name or record ID.' : status === 'archived' ? 'Archived patient records will appear here.' : has('patients:create') ? 'Add a patient to create a record.' : 'Ask your administrator to assign patient access.'}>
        <table className="table directory-table">
          <caption className="sr-only">{status === 'active' ? 'Active' : 'Archived'} patient records</caption>
          <thead><tr><th scope="col">Patient</th><th scope="col">Record ID</th><th scope="col">Practitioner</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Open record</span></th></tr></thead>
          <tbody>{patients.map(patient => <tr key={patient.id}>
            <td className="directory-name"><Link href={patientPath(patient.id)}><span className="directory-avatar" aria-hidden="true">{patient.displayName.charAt(0)}</span><span>{patient.displayName}</span></Link></td>
            <td data-label="Record ID">{patient.id}</td>
            <td data-label="Practitioner">{patient.assignment || 'Unassigned'}</td>
            <td className="directory-status"><Badge>{patient.status}</Badge></td>
            <td className="directory-open"><Link href={patientPath(patient.id)} aria-label={`Open record for ${patient.displayName}`}><span>Open record</span><Icon name="arrow" size={17}/></Link></td>
          </tr>)}</tbody>
        </table>
      </State>
    </section>
  </>;
}
