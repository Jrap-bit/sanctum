'use client';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { PatientTabs } from '@/components/shell';
import { Badge, PageHeader, State } from '@/components/ui';
import { useResource } from '@/lib/hooks';
import { patientPath } from '@/lib/api';
import type { Patient } from '@/lib/types';
export default function PatientLayout({ children }: { children: React.ReactNode }) { const id = useParams<{ patientId: string }>().patientId; const { data: p, loading, error } = useResource<Patient>(patientPath(id)); const [denied,setDenied] = useState(false); useEffect(() => { setDenied(false); const revoke = () => setDenied(true); window.addEventListener('sanctum:denied',revoke); return () => window.removeEventListener('sanctum:denied',revoke); },[id]); if (denied) return <div className="state error" role="alert"><strong>Access denied</strong><p>Your current patient access was revoked or this action is outside your scope. The patient view was cleared.</p></div>; return <State loading={loading} error={error}>{p && <><PageHeader meta={p.id} title={p.displayName} description={p.assignment ? `In the care of ${p.assignment}` : 'Assignment not shown'} action={<div className="row"><Badge>{p.status}</Badge><Link className="button" href="/patients">All patients</Link></div>}/><PatientTabs id={id}/>{children}</>}</State>; }
