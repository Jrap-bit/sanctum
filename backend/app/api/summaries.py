"""Source-version-bound AI drafts and independent clinician review of prose/facts."""
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from hashlib import sha256
from pydantic import Field
from pydantic import model_validator
from sqlalchemy import select
from sqlalchemy.orm import aliased
from typing import Literal
from uuid import UUID
from uuid import uuid4
import json

from ..adapters import llm as ai
from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..db.models import AISummary
from ..db.models import ClinicalNote
from ..db.models import SummaryJob
from ..services.audit import record_audit
from ..services.authorization import require
from ..services.authorization import scoped_patient
from ..services.summaries import current_note
from ..services.summaries import job_output
from ..services.summaries import read_summary
from ..services.summaries import review_payload
from ..services.summaries import save_review
from ..services.summaries import scoped_job
from ..services.summaries import snapshot
from ..services.summaries import sources_current
from ..services.summaries import summary_output
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


router=APIRouter(tags=['AI summaries'])


PREFIX='/api/v1/patients/{patient_id}/summaries'


class SourceVersion(Input):
    id: UUID
    version: int = Field(ge=1)
    type: Literal['session']


class CreateSummary(Input):
    kind: Literal['single_session','longitudinal']
    sourceVersions: list[SourceVersion] = Field(min_length=1,max_length=30)
    requestKey: UUID

    @model_validator(mode='after')
    def valid(self):
        if self.kind=='single_session' and len(self.sourceVersions)!=1:raise ValueError('Choose one source for a single-session summary.')
        if len({s.id for s in self.sourceVersions})!=len(self.sourceVersions):raise ValueError('Choose each source once.')
        return self


class SummaryReview(VersionInput):
    decision: Literal['accept','edit_accept','reject']
    text: str | None = Field(default=None,max_length=20000)
    @model_validator(mode='after')
    def valid(self):
        if self.decision=='edit_accept' and not (self.text or '').strip():raise ValueError('Enter the reviewed summary text.')
        return self


class FactReview(VersionInput):
    label: Literal['concern','observation','intervention','medication_reported','follow_up','other'] | None = None
    decision: Literal['confirm','correct','reject']
    text: str | None = Field(default=None,max_length=1200)
    assertion: Literal['present','denied','possible','unknown'] | None = None
    temporality: Literal['current','historical','unknown'] | None = None
    subject: Literal['patient','other','unknown'] | None = None
    @model_validator(mode='after')
    def valid(self):
        if self.decision=='correct' and (not (self.text or '').strip() or not self.assertion or not self.temporality or not self.subject):
            raise ValueError('Corrected facts need text, assertion, time and subject.')
        return self


@router.get('/api/v1/ai/status')
def model_status(user:CurrentUser):
    if not {'summaries:write','operations:manage'}&set(user.capabilities):raise HTTPException(403,'This action is outside your permissions.')
    return ai.status()


@router.get(PREFIX+'/eligible-sources')
def eligible(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    require(user,'summaries:write');patient=scoped_patient(db,user,patient_id,clinical=True)
    child=aliased(ClinicalNote)
    rows=db.scalars(select(ClinicalNote).where(ClinicalNote.patient_id==patient.id,ClinicalNote.state=='finalized',
        ~select(child.id).where(child.parent_id==ClinicalNote.id,child.state=='finalized').exists()).order_by(ClinicalNote.created_at)).all()
    items=[{k:v for k,v in snapshot(row).items() if k!='text'} for row in rows]
    record_audit(db,request,user,'summary.sources_listed',patient.id);db.commit()
    return {'items':items}


@router.post(PREFIX,status_code=202)
def create(patient_id:UUID,data:CreateSummary,user:CurrentUser,db:Db,request:Request):
    require(user,'summaries:write');patient=scoped_patient(db,user,patient_id,clinical=True,lock=True)
    if patient.status!='active':raise HTTPException(409,'Reactivate the patient before generating summaries.')
    canonical={'kind':data.kind,'sources':sorted([s.model_dump(mode='json') for s in data.sourceVersions],key=lambda s:s['id'])}
    fingerprint=sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
    old=db.scalar(select(SummaryJob).where(SummaryJob.requested_by==user.id,SummaryJob.request_key==str(data.requestKey)))
    if old:
        if old.patient_id!=patient.id or old.request_hash!=fingerprint:raise HTTPException(409,'This request key belongs to a different source selection.')
        return job_output(old)
    sources=[]
    for version in data.sourceVersions:
        note=db.scalar(select(ClinicalNote).where(ClinicalNote.id==str(version.id),ClinicalNote.patient_id==patient.id))
        if not current_note(db,note) or note.version!=version.version:raise HTTPException(409,'A selected source is unavailable, unfinished or superseded. Refresh the source list.')
        sources.append(snapshot(note))
    sources.sort(key=lambda s:(s['eventDate'] or '9999',s['id']))
    try:ai.check_size(sources,data.kind)
    except ValueError:raise HTTPException(422,'The selected records exceed the local model input limit. Choose fewer or shorter sources; nothing was truncated.') from None
    jid=str(uuid4())
    job=SummaryJob(id=jid,patient_id=patient.id,requested_by=user.id,request_key=str(data.requestKey),request_hash=fingerprint,kind=data.kind,
                   payload=encrypt({'sources':sources},f'summary-job:{patient.id}:{jid}'),state='queued')
    db.add(job);record_audit(db,request,user,'summary.generation_requested',jid);db.flush();result=job_output(job);db.commit();return result


@router.get(PREFIX)
def list_summaries(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    rows=db.scalars(select(AISummary).where(AISummary.patient_id==patient.id).order_by(AISummary.created_at.desc())).all()
    result={'items':[summary_output(db,user,patient,row) for row in rows]}
    record_audit(db,request,user,'summary.list',patient.id);db.commit();return result


@router.get(PREFIX+'/generation-jobs')
def patient_jobs(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    rows=db.scalars(select(SummaryJob).where(SummaryJob.patient_id==patient.id,SummaryJob.requested_by==user.id).order_by(SummaryJob.created_at.desc()).limit(20)).all()
    result={'items':[job_output(row) for row in rows]}
    record_audit(db,request,user,'summary.jobs_listed',patient.id);db.commit();return result


@router.get(PREFIX+'/{summary_id}')
def get_summary(patient_id:UUID,summary_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient,row=read_summary(db,user,patient_id,summary_id)
    result=summary_output(db,user,patient,row);record_audit(db,request,user,'summary.read',row.id);db.commit();return result


@router.post(PREFIX+'/{summary_id}/review')
def review_summary(patient_id:UUID,summary_id:UUID,data:SummaryReview,user:CurrentUser,db:Db,request:Request):
    patient,row=read_summary(db,user,patient_id,summary_id,True);payload=review_payload(db,patient,row,data.expectedVersion)
    if payload['reviewState']!='pending':raise HTTPException(409,'This summary already has a review decision.')
    payload['reviewState']='rejected' if data.decision=='reject' else 'accepted'
    if data.decision=='edit_accept':payload['text']=data.text.strip()
    return save_review(db,request,user,patient,row,payload,'summary.'+data.decision)


@router.post(PREFIX+'/{summary_id}/facts/{fact_id}/review')
def review_fact(patient_id:UUID,summary_id:UUID,fact_id:UUID,data:FactReview,user:CurrentUser,db:Db,request:Request):
    patient,row=read_summary(db,user,patient_id,summary_id,True);payload=review_payload(db,patient,row,data.expectedVersion)
    fact=next((f for f in payload['facts'] if f['id']==str(fact_id)),None)
    if fact is None:raise HTTPException(404,'Suggested fact unavailable.')
    if fact['state']!='pending':raise HTTPException(409,'This fact already has a review decision.')
    if payload['reviewState']=='rejected':raise HTTPException(409,'Facts from a rejected summary cannot be confirmed. Generate a new draft.')
    fact['state']='rejected' if data.decision=='reject' else 'confirmed'
    if data.decision=='correct':
        fact.update(text=data.text.strip(),assertion=data.assertion,temporality=data.temporality,subject=data.subject)
        if data.label is not None:fact['label']=data.label
    return save_review(db,request,user,patient,row,payload,'summary.fact_'+data.decision)


@router.get('/api/v1/jobs/{job_id}')
def get_job(job_id:UUID,user:CurrentUser,db:Db,request:Request):
    job=scoped_job(db,user,job_id);result=job_output(job);record_audit(db,request,user,'summary.job_read',job.id);db.commit();return result


@router.post('/api/v1/jobs/{job_id}/cancel')
def cancel_job(job_id:UUID,user:CurrentUser,db:Db,request:Request):
    job=scoped_job(db,user,job_id,True)
    if job.state not in {'queued','running'}:raise HTTPException(409,'This job is no longer active.')
    job.state='cancelled';job.run_id=None;job.lease_until=None
    record_audit(db,request,user,'summary.generation_cancelled',job.id);result=job_output(job);db.commit();return result


@router.post('/api/v1/jobs/{job_id}/retry',status_code=202)
def retry_job(job_id:UUID,user:CurrentUser,db:Db,request:Request):
    job=scoped_job(db,user,job_id,True)
    if job.state not in {'failed','cancelled'}:raise HTTPException(409,'Only failed or cancelled generation can be retried.')
    patient=scoped_patient(db,user,job.patient_id,clinical=True)
    if patient.status!='active':raise HTTPException(409,'Reactivate the patient first.')
    payload=decrypt(job.payload,f'summary-job:{job.patient_id}:{job.id}')
    if not sources_current(db,job.patient_id,payload['sources']):raise HTTPException(409,'The source selection is stale. Create a new request.')
    job.state='queued';job.run_id=None;job.lease_until=None;job.attempts=0;job.message=None
    record_audit(db,request,user,'summary.generation_retried',job.id);result=job_output(job);db.commit();return result
