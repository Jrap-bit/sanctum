'use client';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Require } from '@/components/shell';
import { SectionHeader, Panel, Message, WorkflowSteps } from '@/components/ui';
import { Icon } from '@/components/icon';
import { post, patientPath } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useAction } from '@/lib/hooks';
import type { Session } from '@/lib/types';

function todayInClinic(timeZone?: string) {
  const parts = new Intl.DateTimeFormat('en-US', {timeZone, year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(new Date());
  const part = (type: string) => parts.find(p => p.type === type)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

export default function NewSession() {
  const id = useParams<{patientId: string}>().patientId;
  const router = useRouter();
  const { user } = useAuth();
  const action = useAction();
  const today = todayInClinic(user?.clinicTimezone);
  const [date, setDate] = useState(today);
  const create = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (date && date > todayInClinic(user?.clinicTimezone)) {
      action.setError(new Error('Session date cannot be in the future. Choose today or an earlier date, or leave it blank if unknown.'));
      return;
    }
    const result = await action.run(() => post<Session>(`${patientPath(id)}/sessions`, {eventDate: date || null}));
    if (result) router.replace(`${patientPath(id)}/sessions/${encodeURIComponent(result.id)}`);
  };
  return <Require cap="clinical:write">
    <SectionHeader title="Start a note" description="Choose the date, then write at your own pace."/>
    <WorkflowSteps steps={['Choose date', 'Write note', 'Review & finalize']} current={0}/>
    <div className="grid"><Panel title="When did this session happen?" icon="calendar">
      <form className="stack" style={{maxWidth: 460}} onSubmit={create}>
        <Message error={action.error}/>
        <label className="field"><span>Session date (leave blank if unknown)</span>
          <input type="date" max={today} value={date} onChange={e => {setDate(e.target.value); action.setError(null);}} aria-describedby="session-date-help"/>
        </label>
        <p id="session-date-help" className="small muted">Use the date the session happened—today or earlier. A future follow-up due date is separate from this note.</p>
        <button className="button primary" disabled={action.pending}>{action.pending ? 'Creating draft…' : 'Continue to editor'} <Icon name="arrow" size={16}/></button>
      </form>
    </Panel><div className="focus-card"><Icon name="notes" size={25}/><h2 style={{margin: '14px 0 5px'}}>Your draft stays editable</h2><p>Save it as you work. Finalize when the note is ready for the patient timeline.</p></div></div>
  </Require>;
}
