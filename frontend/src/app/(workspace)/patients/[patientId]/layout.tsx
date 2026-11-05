'use client';
import { useParams, usePathname } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { PatientTabs } from '@/components/shell';
import { Badge, PageHeader, State } from '@/components/ui';
import { useResource } from '@/lib/hooks';
import { api, ApiError, patientPath } from '@/lib/api';
import { PatientContext } from '@/lib/patient';
import type { Patient } from '@/lib/types';

export default function PatientLayout({children}: {children: React.ReactNode}) {
  const id = useParams<{patientId: string}>().patientId;
  const pathname = usePathname();
  const base = patientPath(id);
  const {data: patient, loading, error, reload, setData} = useResource<Patient>(base);
  const [denied, setDenied] = useState(false);
  useEffect(() => {
    setDenied(false);
    let live = true;
    const checkScope = (event: Event) => {
      const path = (event as CustomEvent<{path?: string}>).detail?.path;
      if (path === base) {setDenied(true); return;}
      if (!path?.startsWith(`${base}/`)) return;
      // A forbidden action or an unimplemented endpoint does not prove that
      // patient access was revoked. Recheck scope before discarding local edits.
      void api<Patient>(base).then(current => {if (live) setData(current);}).catch(failure => {
        if (live && failure instanceof ApiError && [403, 404].includes(failure.status)) setDenied(true);
      });
    };
    window.addEventListener('sanctum:denied', checkScope);
    return () => {live = false; window.removeEventListener('sanctum:denied', checkScope);};
  }, [base, setData]);
  if (denied) return <div className="state error" role="alert"><strong>Patient access unavailable</strong><p>Your access to this patient could not be verified. Return to the directory to check your current scope.</p><Link className="button" href="/patients">All patients</Link></div>;
  const clinical = Boolean(patient?.allowedActions.includes('clinical:read'));
  return <State loading={loading} error={error} retry={() => void reload()}>{patient && <PatientContext.Provider value={{patient, reload}}>
    <PageHeader meta={patient.id} title={patient.displayName} description={patient.assignment ? `In the care of ${patient.assignment}` : 'Assignment not shown'} action={<div className="row"><Badge>{patient.status}</Badge><Link className="button" href="/patients">All patients</Link></div>}/>
    {clinical && <PatientTabs id={id}/>}
    {!clinical && pathname !== base ? <div className="state error" role="alert"><strong>Clinical access required</strong><p>Your account can view this patient’s identity and assignment. Clinical records require a separate grant.</p><Link className="button" href={base}>Patient overview</Link></div> : children}
  </PatientContext.Provider>}</State>;
}
