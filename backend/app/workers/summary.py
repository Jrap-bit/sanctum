"""Separate durable worker for local model inference; python -m app.summary_worker."""
from datetime import timedelta
from sqlalchemy import or_
from sqlalchemy import select
from uuid import uuid4
import time

from ..adapters import llm as ai
from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..core.database import SessionLocal
from ..db.models import AISummary
from ..db.models import AuditEvent
from ..db.models import Patient
from ..db.models import SummaryJob
from ..db.models import User
from ..db.models import now
from ..services.authorization import has_access
from ..services.summaries import sources_current


ERRORS={
    'model_unavailable':'The configured local model is unavailable. Start Ollama and check the installed model, then retry.',
    'unsupported_evidence':'The model returned a quotation that could not be verified. No draft was saved; retry generation.',
    'source_limit':'The selected records exceed the local model input limit. Create a smaller source selection.',
    'incomplete_generation':'The model stopped before finishing its draft. Retry with fewer sources.',
}


def authorised(db,job):
    user=db.get(User,job.requested_by);patient=db.get(Patient,job.patient_id)
    return bool(user and user.active and user.credentials_ready and not user.password_reset_required
        and {'clinical:read','summaries:write'}<=set(user.capabilities) and patient and patient.status=='active'
        and has_access(db,user,patient.id,write=True))


def audit(db,job,action,outcome='success'):
    db.add(AuditEvent(actor_id=job.requested_by,target_id=job.id,action=action,outcome=outcome,request_id=job.run_id or str(uuid4())))


def claim(factory):
    with factory() as db:
        job=db.scalar(select(SummaryJob).where(or_(SummaryJob.state=='queued',(SummaryJob.state=='running')&(SummaryJob.lease_until<now())))
            .order_by(SummaryJob.created_at).with_for_update(skip_locked=True).limit(1))
        if job is None:return None
        sources=decrypt(job.payload,f'summary-job:{job.patient_id}:{job.id}')['sources']
        if not authorised(db,job) or not sources_current(db,job.patient_id,sources):
            job.state='cancelled';job.message='Generation cancelled because access or selected source records changed.';job.run_id=None;job.lease_until=None
            audit(db,job,'summary.generation_cancelled');db.commit();return ()
        if job.attempts>=3:
            job.state='failed';job.message='Generation was interrupted repeatedly. Check the worker and retry.';job.lease_until=None
            audit(db,job,'summary.generation_failed','failure');db.commit();return ()
        job.state='running';job.attempts+=1;job.run_id=str(uuid4());job.lease_until=now()+timedelta(seconds=360);job.message=None
        ticket=(job.id,job.run_id,job.patient_id,job.kind,sources)
        audit(db,job,'summary.generation_started');db.commit();return ticket


def locked_current(db,jid,run_id,patient_id):
    # Same patient → job lock order as cancellation/retry endpoints.
    db.scalar(select(Patient).where(Patient.id==patient_id).with_for_update())
    job=db.scalar(select(SummaryJob).where(SummaryJob.id==jid).with_for_update())
    return job if job and job.state=='running' and job.run_id==run_id else None


def run_once(factory=SessionLocal,generator=ai.generate):
    ticket=claim(factory)
    if ticket is None:return False
    if not ticket:return True
    jid,run_id,patient_id,kind,sources=ticket
    try:
        generated=generator(sources,kind)
        with factory() as db:
            job=locked_current(db,jid,run_id,patient_id)
            if job is None:return True
            if not authorised(db,job) or not sources_current(db,patient_id,sources):
                job.state='cancelled';job.message='Generation cancelled because access or selected source records changed.';job.lease_until=None
                audit(db,job,'summary.generation_cancelled');db.commit();return True
            source_indices={s['id']:i+1 for i,s in enumerate(sources)}
            text='\n\n'.join(p['text']+' '+''.join(f"[{source_indices[sid]}]" for sid in dict.fromkeys(e['sourceId'] for e in p['evidence'])) for p in generated['paragraphs'])
            evidence=[]
            for p in generated['paragraphs']:
                for e in p['evidence']:
                    if e not in evidence:evidence.append(e)
            facts=[{**f,'id':str(uuid4()),'state':'pending','originalFact':f.copy()} for f in generated['facts']]
            payload={'text':text,'originalText':text,'reviewState':'pending','sources':sources,'evidence':evidence,
                'facts':facts,'reviewHistory':[],'model':generated['model'],'modelDigest':generated['modelDigest'],
                'promptVersion':generated['promptVersion'],'originalParagraphs':generated['paragraphs']}
            sid=str(uuid4());db.add(AISummary(id=sid,patient_id=patient_id,created_by=job.requested_by,kind=kind,
                version=1,payload=encrypt(payload,f'summary:{patient_id}:{sid}')))
            db.flush()
            job.state='completed';job.summary_id=sid;job.lease_until=None
            audit(db,job,'summary.generation_completed');db.commit()
    except Exception as exc:
        with factory() as db:
            job=locked_current(db,jid,run_id,patient_id)
            if job:
                job.state='failed';job.lease_until=None
                job.message=ERRORS.get(str(exc),'Generation failed or returned invalid structured output. No draft was saved; retry or use fewer sources.')
                audit(db,job,'summary.generation_failed','failure');db.commit()
    return True


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Process local AI summary jobs');parser.add_argument('--once',action='store_true');args=parser.parse_args()
    if args.once:run_once();return
    print('Local AI summary worker started. Press Ctrl+C to stop.',flush=True)
    try:
        while True:
            try:
                if not run_once():time.sleep(2)
            except Exception:
                print('Summary worker could not access its queue. Retrying.',flush=True);time.sleep(5)
    except KeyboardInterrupt:print('Summary worker stopped. Interrupted jobs recover after lease expiry.',flush=True)


if __name__=='__main__':main()
