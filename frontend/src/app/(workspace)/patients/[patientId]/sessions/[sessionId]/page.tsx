'use client';
import { useParams } from 'next/navigation';
import { SessionEditor } from '@/components/session-editor';
import { SectionHeader, State } from '@/components/ui';
import { Require } from '@/components/shell';
import { useResource } from '@/lib/hooks';
import { patientPath } from '@/lib/api';
import type { Session } from '@/lib/types';
export default function SessionPage() { const { patientId, sessionId } = useParams<{patientId:string;sessionId:string}>(); const { data, loading, error } = useResource<Session>(`${patientPath(patientId)}/sessions/${encodeURIComponent(sessionId)}`); return <Require cap="clinical:read"><SectionHeader title="Session note" description="Write, save, then finalize when ready."/><State loading={loading} error={error}>{data && <SessionEditor key={data.id} initial={data} patientId={patientId}/>}</State></Require>; }
